"""Real native Docker and HTTP transport; only inference content is deterministic.

Set HERMES_TEST_ENGINEERING_IMAGE to a prepared, credential-free image digest.
No live account, real OAuth token or paid inference is used by this gate.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import threading

import pytest

IMAGE = os.getenv('HERMES_TEST_ENGINEERING_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE, reason='requires an explicitly prepared native Docker image')


def test_native_picker_parent_inference_tools_verification_and_descendants(tmp_path, monkeypatch):
    import yaml
    from hermes_cli import plugins, config as config_mod
    from plugins import implementation_router as plugin
    from plugins.implementation_router.entrypoint import run_workflow
    from plugins.implementation_router.host import NativeEngineeringHost
    from tools.environments.docker import DockerEnvironment

    home = tmp_path/'home'; home.mkdir()
    source = tmp_path/'source'; (source/'tests').mkdir(parents=True)
    (source/'answer.py').write_text('def answer():\n    return 0\n')
    test_text = 'import unittest\nfrom answer import answer\nclass Contract(unittest.TestCase):\n    def test_answer(self): self.assertEqual(answer(),42)\n'
    (source/'tests'/'test_answer.py').write_text(test_text)
    (home/'auth.json').write_text('{"token":"synthetic-host-file-secret"}')
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('ENGINEERING_SYNTHETIC_SECRET', 'synthetic-parent-secret')
    monkeypatch.setenv('SUDO_PASSWORD', 'synthetic-parent-sudo')
    # Exercise the actual native backend before the workflow so failure output
    # identifies infrastructure separately from controller errors.
    probe = DockerEnvironment.credential_free(image=IMAGE, task_id='engineering-e2e-probe')
    try:
        result = probe.execute_clean(('/usr/local/bin/python','-I','-c','print("probe-ok")'))
        assert result['returncode'] == 0, result
        assert 'probe-ok' in result['output']
    finally:
        probe.cleanup()

    requests=[]; errors=[]; state={'worker':0}
    plan={'objective':'Return 42','constraints':['Preserve acceptance tests'],
          'steps':['Write the smallest fix','Run tests'], 'acceptance_criteria':['answer() returns 42']}
    child_code = (
        "import os,subprocess,sys,pathlib; "
        "assert 'ENGINEERING_SYNTHETIC_SECRET' not in os.environ; "
        "assert 'SUDO_PASSWORD' not in os.environ; "
        "assert not pathlib.Path('/root/.hermes/auth.json').exists(); "
        "assert not pathlib.Path('/var/run/docker.sock').exists(); "
        "subprocess.run([sys.executable,'-I','-c',\"import os; assert 'ENGINEERING_SYNTHETIC_SECRET' not in os.environ\"],check=True); "
        "print('child-grandchild-credential-check-passed')"
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            length=int(self.headers['Content-Length'])
            body=json.loads(self.rfile.read(length)); requests.append(body)
            assert self.headers.get('Authorization') == 'Bearer synthetic-inference-key'
            assert 'synthetic-inference-key' not in json.dumps(body)
            model=body['model']; messages=body['messages']; count=(len(messages)-2)//2
            if model in ('fixture/planner','fixture/reviewer'):
                result={'action':'finish','result':plan}
            elif model == 'fixture/worker':
                if count == 0:
                    state['worker']+=1
                iteration=state['worker']
                if iteration == 2:
                    result={'action':'finish','result':{'status':'BLOCKED','summary':'Need the correct return value',
                                                       'decision_required':'Confirm that the acceptance value is 42'}}
                elif count == 0:
                    result={'action':'tool','name':'write_file','arguments':{
                        'path':'/workspace/answer.py','content':f'def answer():\n    return {41 if iteration==1 else 42}\n'}}
                elif count == 1:
                    result={'action':'tool','name':'terminal','arguments':{
                        'command':'/usr/local/bin/python -I -c '+shlex.quote(child_code), 'timeout':30}}
                else:
                    assert 'child-grandchild-credential-check-passed' in json.dumps(messages), messages
                    result={'action':'finish','result':{'status':'READY','summary':'Ready for host verification','decision_required':''}}
            else:
                raise AssertionError('Unexpected model route')
            response={'id':'fixture','object':'chat.completion','created':1,'model':model,
                      'choices':[{'index':0,'message':{'role':'assistant','content':json.dumps(result)},'finish_reason':'stop'}],
                      'usage':{'prompt_tokens':2,'completion_tokens':2,'total_tokens':4}}
            data=json.dumps(response).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    configuration={'model':{'provider':'custom','default':'fixture/planner'},
        'display':{'language':'ja'},
        'auxiliary':{f'engineering_{role}':{'provider':'custom','model':f'fixture/{role}',
             'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'synthetic-inference-key'}
             for role in ('planner','worker','reviewer')},
        'plugins':{'enabled':['implementation_router'],'entries':{'implementation_router':{'settings':{
            'enabled':True,'workspaces':{'sample':{'path':str(source),'image':IMAGE,
            'source_paths':['answer.py','tests'],'protected_paths':['tests'],
            'checks':[{'id':'unit','argv':['/usr/local/bin/python','-m','unittest','discover','-s','tests','-q']}]}}}}}}}
    (home/'config.yaml').write_text(yaml.safe_dump(configuration))
    manager=plugins.PluginManager(); manager._discovered=True
    monkeypatch.setattr(plugins,'_ensure_plugins_discovered',lambda:manager)
    monkeypatch.setattr(plugins,'get_plugin_manager',lambda:manager)
    ctx=plugins.PluginContext(plugins.PluginManifest(name='implementation_router'),manager)
    plugin.register(ctx)
    # Capture full synthetic test errors without changing runtime control flow.
    for name in ('stage','verify','admit'):
        original=getattr(NativeEngineeringHost,name)
        def wrapped(self,*args,_original=original,**kwargs):
            try:
                return _original(self,*args,**kwargs)
            except Exception as exc:
                errors.append((type(exc).__name__,str(exc)))
                raise
        monkeypatch.setattr(NativeEngineeringHost,name,wrapped)
    try:
        result=json.loads(run_workflow(ctx,{'workspace':'sample','task':'Fix answer() using TDD; return 42.'}))
        assert result['state']=='SUCCEEDED', (result,errors)
        assert result['locale']=='ja'
        output=Path(result['verified_workspace'])
        assert (output/'answer.py').read_text()=='def answer():\n    return 42\n'
        assert (output/'tests'/'test_answer.py').read_text()==test_text
        assert (source/'answer.py').read_text()=='def answer():\n    return 0\n'
        assert state['worker']==3
        models=[r['model'] for r in requests]
        assert models[0]=='fixture/planner' and 'fixture/reviewer' in models
        assert 'synthetic-parent-secret' not in json.dumps(requests)
        assert 'synthetic-parent-sudo' not in json.dumps(requests)
        events=[json.loads(line) for line in (output.parent/'events.jsonl').read_text().splitlines()]
        assert events[-1]['kind']=='succeeded'
        assert not list(output.parent.parent.glob('*.lease'))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_protected_probe_and_container_lifetime_are_real(tmp_path):
    from plugins.implementation_router.workspace import import_sources, snapshot
    from tools.environments.docker import DockerEnvironment
    env = DockerEnvironment.credential_free(image=IMAGE, task_id='engineering-e2e-guards')
    try:
        files={'test_contract.py':b'assert 1 == 1\n', 'subject.py':b'value=1\n'}
        import_sources(env,files,('test_contract.py',))
        overwrite=env.execute_clean(('/usr/local/bin/python','-I','-c',
                                    "open('test_contract.py','w').write('pass')"))
        assert overwrite['returncode'] != 0
        assert snapshot(env)==files
        assert env.execute_clean(('/bin/bash','-c','sleep 30 >/tmp/sleep.log 2>&1 &'))['returncode']==0
        with pytest.raises(RuntimeError,match='writer'):
            env.assert_quiescent()
    finally:
        env.cleanup()
    with pytest.raises(RuntimeError):
        env.execute_clean(('/bin/true',))
