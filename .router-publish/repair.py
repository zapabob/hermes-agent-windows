"""Apply three reviewed edits on an immutable candidate; no product execution."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = '15558731b670859cf7360f6a692a661a7d9c432f'
TREE = 'ea19b89935da42bb42ca408f04621a3cc9e15ac7'
REPO = 'zapabob/hermes-agent-windows'
BRANCH = 'feat/implementation-router-20260923'


def main():
    token = os.environ.pop('PUBLISH_TOKEN')
    def api(method, path, data=None):
        request = Request('https://api.github.com/repos/' + REPO + '/' + path,
            data=None if data is None else json.dumps(data).encode(), method=method,
            headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                     'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
        try:
            with urlopen(request, timeout=60) as response:
                raw=response.read();return json.loads(raw) if raw else None
        except HTTPError as exc:
            raise RuntimeError('GitHub request failed: '+str(exc.code)) from None
    current=api('GET','git/ref/heads/'+BRANCH)['object']['sha']
    if current != BASE:
        existing=api('GET','git/commits/'+current)
        if existing['tree']['sha'] != TREE or [x['sha'] for x in existing['parents']] != [BASE]:
            raise RuntimeError('Branch changed; refusing to overwrite')
        candidate=current
    else:
        with tempfile.TemporaryDirectory(prefix='router-reviewed-fix-') as temporary:
            root=Path(temporary);home=root/'home';home.mkdir()
            env={'PATH':'/usr/bin:/bin','HOME':str(home),'LANG':'C.UTF-8','GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0'}
            def git(*args):
                completed=subprocess.run(['/usr/bin/git','-c','core.hooksPath=/dev/null',*args],cwd=root,
                    env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True,timeout=180)
                if completed.returncode:raise RuntimeError('Git step failed: '+args[0])
                return completed.stdout
            git('init');git('fetch','--no-tags','--depth=1','https://github.com/'+REPO+'.git',BASE)
            files={name:git('show',BASE+':'+name).decode() for name in (
                'plugins/implementation_router/host.py','scripts/ci/qualify_implementation_router.py','uv.lock')}
            files['plugins/implementation_router/host.py']=files['plugins/implementation_router/host.py'].replace("os.fdopen(descriptor, 'w')","os.fdopen(descriptor, 'w', encoding='utf-8')")
            files['scripts/ci/qualify_implementation_router.py']=files['scripts/ci/qualify_implementation_router.py'].replace('capture_output=True, text=True, timeout=180','capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180')
            lock=files['uv.lock']
            lock=lock.replace('exclude-newer = "0001-01-01T00:00:00Z" # This has no effect and is included for backwards compatibility when using relative exclude-newer values.','exclude-newer = "2026-09-09T04:34:03.182598249Z"')
            lock=lock.replace('"dev", "messaging", "cron"','"dev", "messaging", "voice-push", "cron"')
            blocks=lock.split('[[package]]')
            for i,block in enumerate(blocks):
                if '\nname = "scipy"\nversion = "1.17.1"' in block:
                    blocks[i]=block.replace('{ name = "numpy" }','{ name = "numpy", marker = "python_full_version < \'3.12\'" }')
                elif '\nname = "scipy"\nversion = "1.18.0"' in block:
                    blocks[i]=block.replace('{ name = "numpy" }','{ name = "numpy", marker = "python_full_version >= \'3.12\'" }')
                elif '\nname = "vercel-workers"\n' in block:
                    for package in ('anyio','httpx','pydantic','python-dotenv','vercel'):
                        block=block.replace('{ name = "'+package+'" }','{ name = "'+package+'", marker = "python_full_version >= \'3.12\'" }')
                    blocks[i]=block
            files['uv.lock']='[[package]]'.join(blocks)
            changes=[]
            for name,content in files.items():
                blob=api('POST','git/blobs',{'encoding':'utf-8','content':content})
                changes.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
            base_tree=api('GET','git/commits/'+BASE)['tree']['sha']
            tree=api('POST','git/trees',{'base_tree':base_tree,'tree':changes})
            if tree['sha'] != TREE:raise RuntimeError('Reviewed tree identity mismatch')
            candidate=api('POST','git/commits',{'tree':TREE,'parents':[BASE],
                'message':'fix(engineering): specify UTF-8 and reconcile the existing main lock\n\nThe uv 0.9.28 regeneration reproduces on unmodified main: missing\nvoice-push extra metadata and normalised resolution markers; no package\nversion changes. Real native Docker acceptance passed with this lock.\nFull exact-head CI remains required.'})['sha']
            if api('GET','git/ref/heads/'+BRANCH)['object']['sha'] != BASE:raise RuntimeError('Branch changed')
            api('PATCH','git/refs/heads/'+BRANCH,{'sha':candidate,'force':False})
    print('Published reviewed tree',TREE,'at',candidate)
    api('POST','actions/workflows/ci.yaml/dispatches',{'ref':BRANCH})


if __name__ == '__main__':
    main()
