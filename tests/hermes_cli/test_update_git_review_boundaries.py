"""Indeterminate recovery must retain its authority and shared time budget."""
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from hermes_cli import _subprocess_compat as compat, update_cmd as update


@pytest.mark.parametrize('code', [124, 127])
@pytest.mark.parametrize('check', [False, True])
def test_recovery_execution_failure_is_typed_without_zip_fallback(tmp_path, monkeypatch, code, check):
    monkeypatch.setattr(compat, 'run_internal_git', lambda args, cwd, **kw:
        subprocess.CompletedProcess(['git', *args], code, '', 'owned unavailable execution'))
    monkeypatch.setattr(update._m(), '_is_windows', lambda: True)
    with pytest.raises(update._UpdateGitExecutionError) as failure:
        update._run_update_recovery_git(['git', 'status', '--porcelain'], cwd=tmp_path, check=check)
    assert failure.value.returncode == code
    assert not update._should_zip_fallback_on_update_error(failure.value)


def test_recovery_confirmation_timeout_retains_actual_saved_stash(tmp_path, monkeypatch):
    git = shutil.which('git')
    assert git
    repo = tmp_path/'owned-recovery'
    repo.mkdir()
    env = compat.noninteractive_git_env()
    def raw(*args):
        return subprocess.run([git, *args], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding='utf-8', timeout=10, check=True)
    raw('init','-q')
    raw('config','user.name','Owned fixture')
    raw('config','user.email','fixture@example.invalid')
    raw('config','core.autocrlf','false')
    tracked = repo/'owned.txt'
    tracked.write_bytes(b'baseline\n')
    raw('add','--','owned.txt')
    raw('commit','-qm','Owned baseline')
    tracked.write_bytes(b'saved user content\n')
    raw('stash','push','-qm','Owned recovery entry')
    saved = raw('rev-parse','refs/stash').stdout.strip()
    original_config = (repo/'.git/config').read_bytes()
    calls = []
    def recovery(args, cwd, **kw):
        calls.append(args)
        return subprocess.CompletedProcess([git,*args], 124 if args[0]=='diff' else 0, '', '')
    monkeypatch.setattr(compat,'run_internal_git',recovery)
    monkeypatch.setattr(update._m(),'_is_windows',lambda:True)
    with pytest.raises(update._UpdateGitExecutionError) as failure:
        update._restore_stashed_changes([git],repo,saved)
    zip_calls = []
    if update._should_zip_fallback_on_update_error(failure.value):
        zip_calls.append('zip fallback')
    assert zip_calls == []
    assert not any('drop' in args or 'reset' in args for args in calls)
    assert raw('rev-parse','refs/stash').stdout.strip() == saved
    assert raw('show', saved+':owned.txt').stdout == 'saved user content\n'
    assert tracked.read_bytes() == b'baseline\n'
    assert (repo/'.git/config').read_bytes() == original_config


def test_eol_discovery_exhaustion_does_not_start_actual_git(tmp_path, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(compat,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    def discover(*a,**kw):
        clock[0] = 41.0
        return {'GIT_CONFIG_COUNT':'0'}
    monkeypatch.setattr(compat,'noninteractive_repo_git_env',discover)
    monkeypatch.setattr(compat,'git_policy_environment_valid',lambda *a,**kw:True)
    launches = []
    def no_launch(*args,**kwargs):
        launches.append(args)
        raise AssertionError('Actual Git launched after exhausted discovery')
    monkeypatch.setattr(subprocess,'Popen',no_launch)
    previous = compat._INTERNAL_GIT_DEADLINE.get()
    with pytest.raises(update._UpdateGitExecutionError):
        update._run_update_eol_git(['git','-c','core.autocrlf=false','diff','--name-only'],cwd=tmp_path)
    assert launches == []
    assert compat._INTERNAL_GIT_DEADLINE.get() == previous


@pytest.mark.parametrize('code',[124,127])
def test_eol_execution_failure_is_typed_without_check(tmp_path, monkeypatch, code):
    monkeypatch.setattr(compat,'noninteractive_repo_git_env',lambda *a,**kw:{'GIT_CONFIG_COUNT':'0'})
    monkeypatch.setattr(compat,'git_policy_environment_valid',lambda *a,**kw:True)
    monkeypatch.setattr(compat,'bounded_probe_run',lambda argv,**kw:
        subprocess.CompletedProcess(argv,code,b'',b'owned unavailable execution'))
    with pytest.raises(update._UpdateGitExecutionError):
        update._run_update_eol_git(['git','-c','core.autocrlf=false','diff','--name-only'],cwd=tmp_path)
