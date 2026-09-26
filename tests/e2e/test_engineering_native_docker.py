"""Native Docker guards for the reusable credential-free backend.

The fixed-stage engineering entrypoint is retired and is not exercised here.
Set HERMES_TEST_ENGINEERING_IMAGE to an explicitly prepared image digest.
"""
from __future__ import annotations

import os
import shlex
import textwrap

import pytest

IMAGE = os.getenv('HERMES_TEST_ENGINEERING_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE, reason='requires an explicitly prepared native Docker image')


def test_parent_credentials_do_not_reach_container_or_grandchild(tmp_path, monkeypatch):
    from tools.environments.docker import DockerEnvironment

    host_home = tmp_path / 'host-home'
    host_home.mkdir()
    host_auth = host_home / 'auth.json'
    host_auth.write_text('{"token":"synthetic-host-file-secret"}', encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(host_home))
    monkeypatch.setenv('ENGINEERING_SYNTHETIC_SECRET', 'synthetic-parent-secret')
    monkeypatch.setenv('SUDO_PASSWORD', 'synthetic-parent-sudo')

    checks = textwrap.dedent('''\
        import os, pathlib
        assert 'ENGINEERING_SYNTHETIC_SECRET' not in os.environ
        assert 'SUDO_PASSWORD' not in os.environ
        assert not pathlib.Path('/var/run/docker.sock').exists()
        assert not pathlib.Path('/root/.hermes/auth.json').exists()
    ''')
    code = textwrap.dedent(f'''\
        import pathlib, subprocess, sys
        exec({checks!r})
        assert not pathlib.Path({str(host_auth)!r}).exists()
        child = subprocess.run([sys.executable, '-I', '-c', {checks!r}],
                               capture_output=True, text=True, check=True)
        assert child.returncode == 0
        print('credential-boundary-ok')
    ''')
    env = DockerEnvironment.credential_free(image=IMAGE, task_id='credential-free-e2e-secrets')
    try:
        for result in (
            env.execute_clean(('/usr/local/bin/python', '-I', '-c', code)),
            env.execute(f'/usr/local/bin/python -I -c {shlex.quote(code)}'),
        ):
            assert result['returncode'] == 0, result
            assert 'credential-boundary-ok' in result['output']
            assert 'synthetic-parent-secret' not in result['output']
            assert 'synthetic-parent-sudo' not in result['output']
            assert 'synthetic-host-file-secret' not in result['output']
    finally:
        env.cleanup()


def test_protected_probe_and_container_lifetime_are_real():
    from plugins.implementation_router.workspace import import_sources, snapshot
    from tools.environments.docker import DockerEnvironment
    env = DockerEnvironment.credential_free(image=IMAGE, task_id='credential-free-e2e-guards')
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
