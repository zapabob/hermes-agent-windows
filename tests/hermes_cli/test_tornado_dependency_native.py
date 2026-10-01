"""Bounded Windows wheel and locked optional webhooks dependency contracts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Subprocess isolation avoids mixing two dependency versions in sys.modules.
# The target is a test-owned installed wheel, never a reference source tree.
NATIVE_SCRIPT = r'''
import importlib.util, json, os, socket, sys
from pathlib import Path
target, case, work = sys.argv[1:]
sys.path.insert(0, target)
def deny(*args, **kwargs):
    raise AssertionError('Native dependency tests must not use network')
socket.socket.connect = deny
socket.socket.bind = deny
socket.getaddrinfo = deny
import tornado
from tornado import httputil, web
origin=Path(tornado.__file__).resolve()
assert origin.is_relative_to(Path(target).resolve()), str(origin)
result={'version':tornado.version,'origin':str(origin),'case':case,'platform':sys.platform}
if case=='origin':
    import tornado.speedups
    result['speedups']=tornado.speedups.__file__
    assert Path(result['speedups']).resolve().is_relative_to(Path(target).resolve())
    assert result['speedups'].endswith('.pyd') if sys.platform=='win32' else True
elif case=='query-valid':
    req=httputil.HTTPServerRequest(method='GET',uri='/?text=%E6%97%A5%E6%9C%AC%E8%AA%9E&tag=a&tag=b&blank=')
    assert req.arguments=={'text':['日本語'.encode('utf-8')],'tag':[b'a',b'b'],'blank':[b'']}
elif case in ('query-default','query-custom'):
    limit=1000 if case=='query-default' else 2
    old=httputil._DEFAULT_PARSE_BODY_CONFIG
    if case=='query-custom':
        httputil.set_parse_body_config(httputil.ParseBodyConfig(urlencoded=httputil.ParseUrlEncodedConfig(max_arguments=limit)))
    try:
        req=httputil.HTTPServerRequest(method='GET',uri='/?'+'&'.join('a=1' for _ in range(limit)))
        assert len(req.arguments['a'])==limit
        try:
            httputil.HTTPServerRequest(method='GET',uri='/?'+'&'.join('a=1' for _ in range(limit+1)))
        except httputil.HTTPInputError as exc:
            assert 'query' in str(exc).lower()
            result['rejected']=True
        else:
            raise AssertionError('Query field limit must reject one field above the configured cap')
    finally:
        httputil.set_parse_body_config(old)
elif case=='post-control':
    config=httputil.ParseBodyConfig(urlencoded=httputil.ParseUrlEncodedConfig(max_arguments=2))
    args={}
    httputil.parse_body_arguments('application/x-www-form-urlencoded',b'a=1&a=2',args,{},config=config)
    assert args=={'a':[b'1',b'2']}
    try:
        httputil.parse_body_arguments('application/x-www-form-urlencoded',b'a=1&a=2&a=3',{}, {},config=config)
    except httputil.HTTPInputError:
        result['rejected']=True
    else:
        raise AssertionError('Existing body-count protection must remain')
else:
    root=Path(work)/'static'
    root.mkdir()
    local=root/'日本語.txt'
    local.write_text('test-owned file',encoding='utf-8')
    outside=Path(work)/'outside.txt'
    outside.write_text('test-owned outside',encoding='utf-8')
    handler=object.__new__(web.StaticFileHandler)
    handler.initialize(str(root))
    handler.path='日本語.txt'
    assert Path(handler.validate_absolute_path(str(root),str(local)))==local.resolve()
    assert b''.join(handler.get_content(str(local)))==b'test-owned file'
    if case=='static-controls':
        for candidate,expected in ((outside,403),(root/'missing.txt',404)):
            try:
                handler.validate_absolute_path(str(root),str(candidate))
            except web.HTTPError as exc:
                assert exc.status_code==expected
            else:
                raise AssertionError('Static path rejection missing')
    elif case=='static-symlink':
        link=root/'link.txt'
        try:
            link.symlink_to(outside)
        except OSError as exc:
            if getattr(exc,'winerror',None)==1314:
                result['blocked']='BLOCKED_NATIVE_SYMLINK_PRIVILEGE: WinError 1314'
                print(json.dumps(result)); sys.exit(77)
            raise
        try:
            handler.validate_absolute_path(str(root),str(link))
        except web.HTTPError as exc:
            assert exc.status_code==403
            result['rejected']=True
        else:
            raise AssertionError('Static symlink must stay within the allowed directory')
    else:
        raise AssertionError(case)
print(json.dumps(result,ensure_ascii=True))
'''


def test_locked_webhooks_dependency_is_patched_and_optional():
    lock = tomllib.loads((ROOT / 'uv.lock').read_text(encoding='utf-8'))
    packages = {p['name']: p for p in lock['package']}
    tornado = packages['tornado']
    assert tuple(map(int, tornado['version'].split('.'))) >= (6, 5, 9)
    ptb = packages['python-telegram-bot']
    assert any(p['name'] == 'tornado' for p in ptb['optional-dependencies']['webhooks'])
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    assert not any(p.split('=')[0].strip().startswith('tornado') for p in project['dependencies'])
    for extra in ('messaging', 'termux'):
        assert any(p.startswith('python-telegram-bot[webhooks]') for p in project['optional-dependencies'][extra])
    target = os.environ.get('S03B_TORNADO_TARGET')
    if target:
        metadata = next(Path(target).glob('tornado-*.dist-info/METADATA')).read_text(encoding='utf-8')
        assert f"Version: {tornado['version']}\n" in metadata
        assert any('win_amd64.whl' in w['url'] for w in tornado['wheels'])


@pytest.mark.parametrize('case', ['origin', 'query-valid', 'query-default', 'query-custom',
                                'post-control', 'static-controls', 'static-symlink'])
def test_real_tornado_native_boundary(case, tmp_path):
    target = os.environ.get('S03B_TORNADO_TARGET')
    if target is None:
        pytest.skip('Dedicated test-owned Tornado wheel target is required for native evidence')
    env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT') if k in os.environ}
    env.update(HERMES_HOME=str(tmp_path / 'hermes'), HOME=str(tmp_path), USERPROFILE=str(tmp_path),
               TEMP=str(tmp_path), TMP=str(tmp_path), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    result = subprocess.run([sys.executable, '-I', '-c', NATIVE_SCRIPT, target, case, str(tmp_path)],
                            env=env, capture_output=True, encoding='utf-8', timeout=30)
    if result.returncode == 77:
        pytest.skip(json.loads(result.stdout)['blocked'])
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['case'] == case
    assert Path(report['origin']).resolve().is_relative_to(Path(target).resolve())
