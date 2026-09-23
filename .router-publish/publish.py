"""Publish one hash-bound patch; never execute product code with a GitHub token."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO = 'zapabob/hermes-agent-windows'
BRANCH = 'feat/implementation-router-20260923'
BASE = '669039a501e13e9f48f1e995b0836944854eea33'
EXPECTED_TREE = '30f02dfcf5e5b9db8cdd91a3d047eab9cf7b7ed1'
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / '.router-publish'


def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPO:
        raise RuntimeError('Wrong repository')
    token = os.environ.pop('PUBLISH_TOKEN')
    def api(method, path, data=None):
        # All requests are fixed GitHub REST paths. The token remains here,
        # never in a shell, child environment, file, diagnostic or commit.
        req = Request('https://api.github.com/repos/' + REPO + '/' + path,
                      data=json.dumps(data).encode() if data is not None else None,
                      method=method, headers={'Authorization': 'Bearer ' + token,
                      'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                      'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urlopen(req, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            raise RuntimeError('GitHub request failed: HTTP ' + str(exc.code)) from None

    manifest = json.loads((DATA / 'manifest.json').read_text())
    if manifest['base'] != BASE or manifest['final_tree'] != EXPECTED_TREE or manifest['parts'] != 9:
        raise RuntimeError('Manifest does not match the authorised publication')
    packed = ''.join((DATA / ('part%02d' % n)).read_text() for n in range(9))
    patch = lzma.decompress(base64.b64decode(packed, validate=True), memlimit=256 * 1024 * 1024)
    finalizer = (DATA / 'finalizer.patch').read_bytes()
    if hashlib.sha256(patch).hexdigest() != manifest['patch_sha256']:
        raise RuntimeError('Patch digest mismatch')
    if hashlib.sha256(finalizer).hexdigest() != manifest['finalizer_sha256']:
        raise RuntimeError('Finalizer digest mismatch')
    current = api('GET', 'git/ref/heads/' + BRANCH)['object']['sha']
    if current != BASE:
        # A completed prior attempt may have published but not dispatched CI.
        previous = api('GET', 'git/commits/' + current)
        if previous['tree']['sha'] != EXPECTED_TREE or [p['sha'] for p in previous['parents']] != [BASE]:
            raise RuntimeError('Feature branch moved; refusing to overwrite it')
        candidate = current
    else:
        with tempfile.TemporaryDirectory(prefix='router-publish-') as temporary:
            temporary = Path(temporary)
            home = temporary / 'home'
            home.mkdir()
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'LANG': 'C.UTF-8',
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'}
            def git(*args, cwd=ROOT, input=None):
                outcome = subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
                    '-c', 'core.attributesFile=/dev/null', '-c', 'core.autocrlf=false', *args],
                    cwd=cwd, env=env, input=input, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, close_fds=True, timeout=180)
                if outcome.returncode:
                    raise RuntimeError('Git publication step failed: ' + args[0])
                return outcome.stdout
            git('fetch', '--no-tags', '--depth=1', 'https://github.com/' + REPO + '.git', BASE)
            workspace = temporary / 'candidate'
            git('worktree', 'add', '--detach', str(workspace), BASE)
            try:
                git('apply', '--index', '--unidiff-zero', '--binary', '-', cwd=workspace, input=patch)
                if git('write-tree', cwd=workspace).decode().strip() != manifest['tree']:
                    raise RuntimeError('Intermediate tree does not match the local worktree')
                git('apply', '--index', '--unidiff-zero', '--binary', '-', cwd=workspace, input=finalizer)
                if git('write-tree', cwd=workspace).decode().strip() != EXPECTED_TREE:
                    raise RuntimeError('Final tree does not match the local worktree')
                names = git('diff', '--cached', '--name-only', '-z', cwd=workspace).decode().strip('\0').split('\0')
                if len(names) != 45 or any(name.startswith('.router-publish/') for name in names):
                    raise RuntimeError('Unexpected publication scope')
                entries = []
                for name in names:
                    mode, local_sha, stage = git('ls-files', '-s', '--', name, cwd=workspace).decode().split('\t')[0].split()
                    if mode not in ('100644', '100755') or stage != '0':
                        raise RuntimeError('Unsupported tree entry')
                    content = git('show', ':' + name, cwd=workspace)
                    entries.append((name, mode, local_sha, content))
                def upload(entry):
                    name, mode, expected, content = entry
                    blob = api('POST', 'git/blobs', {'encoding': 'base64',
                               'content': base64.b64encode(content).decode()})
                    if blob['sha'] != expected:
                        raise RuntimeError('Blob identity mismatch')
                    return {'path': name, 'mode': mode, 'type': 'blob', 'sha': expected}
                with ThreadPoolExecutor(max_workers=4) as executor:
                    changes = list(executor.map(upload, entries))
                base_tree = api('GET', 'git/commits/' + BASE)['tree']['sha']
                tree = api('POST', 'git/trees', {'base_tree': base_tree, 'tree': changes})
                if tree['sha'] != EXPECTED_TREE:
                    raise RuntimeError('GitHub tree identity mismatch')
                # No new author or Co-authored-by is invented. GitHub attributes
                # this authenticated publication in its normal commit metadata.
                commit = api('POST', 'git/commits', {'tree': EXPECTED_TREE, 'parents': [BASE],
                    'message': 'feat(engineering): wire native picker routes and credential-free execution\n\nParent-owned inference; no Codex SDK or credential-bearing child agent.\nAdd strict Docker execution, native tool dispatch, bounded workflow,\nprotected host checks, five-locale UI/docs and native acceptance tests.\n\nLocal component/regression and picker tests pass; live Docker and full\nexact-head CI remain publication gates, not asserted success.'})
                candidate = commit['sha']
                if api('GET', 'git/ref/heads/' + BRANCH)['object']['sha'] != BASE:
                    raise RuntimeError('Feature branch changed during preparation')
                api('PATCH', 'git/refs/heads/' + BRANCH, {'sha': candidate, 'force': False})
            finally:
                git('worktree', 'remove', '--force', str(workspace))
    print('Published candidate:', candidate)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
        summary.write('Candidate `' + candidate + '`; tree `' + EXPECTED_TREE + '`.\n\n')
        summary.write('Publication only. No tests, merge, or live-model success are asserted.\n')
    api('POST', 'actions/workflows/ci.yaml/dispatches', {'ref': BRANCH})


if __name__ == '__main__':
    main()
