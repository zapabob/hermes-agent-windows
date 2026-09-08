"""Actual fixed-head delivery and SQLite; synthetic unavailable owner only."""
import asyncio
import threading
import time
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from gateway.run import GatewayRunner
from tools import async_delegation as delegation


@pytest.mark.parametrize("batch_size", [1, 2])
def test_temporary_owner_unavailability_does_not_spend_attempts(tmp_path, monkeypatch, batch_size):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = []
    for index in range(batch_size):
        event = dict(type="async_delegation", delegation_id=f"owner-budget-{index}",
                     session_key="agent:main:telegram:dm:fixture", parent_session_id="fixture-parent",
                     goal="fixture", summary="fixture complete", status="completed",
                     dispatched_at=time.time(), completed_at=time.time())
        delegation._persist_dispatch(event)
        delegation._persist_completion(event, {"status": "completed", "summary": "fixture complete"})
        events.append(event)
    observations = []
    for iteration in range(10):
        runner = object.__new__(GatewayRunner)
        runner.adapters = {}
        runner.session_store = SimpleNamespace(_ensure_loaded=lambda: None, _entries={})
        runner._session_source_cache = {}
        runner._completion_delivery_lock = threading.Lock()
        runner._completion_deliveries_inflight = set()
        runner._completion_deliveries_delivered = OrderedDict()
        runner._completion_delivery_retention = 2048
        runner._background_tasks = set()
        runner._classify_completion_target = AsyncMock(return_value="retry")
        result = asyncio.run(runner._deliver_async_delegation_group(events))
        observations.append(dict(iteration=iteration, result=result, rows=[
            {key: delegation.get_durable_delegation(event["delegation_id"])[key]
             for key in ("delivery_state", "delivery_attempts")} for event in events]))
    assert all(row == {"delivery_state": "pending", "delivery_attempts": 0}
               for observation in observations for row in observation["rows"]), observations


def _native_restart_worker(seed):
    """Invoked only by the owned test subprocess, using a synthetic home."""
    import queue
    if seed:
        for index in range(2):
            event = dict(type='async_delegation', delegation_id=f'native-retry-{index}',
                         session_key='agent:main:telegram:dm:fixture', parent_session_id='fixture-parent',
                         goal='fixture', summary='fixture complete', status='completed',
                         dispatched_at=time.time(), completed_at=time.time())
            delegation._persist_dispatch(event)
            delegation._persist_completion(event, {'status': 'completed', 'summary': 'fixture complete'})
    pending = queue.Queue()
    assert delegation.restore_undelivered_completions(pending) == 2
    events = [pending.get_nowait(), pending.get_nowait()]
    assert all(event['restored'] for event in events)
    runner = object.__new__(GatewayRunner)
    runner.adapters = {}
    runner.session_store = SimpleNamespace(_ensure_loaded=lambda: None, _entries={})
    runner._session_source_cache = {}
    runner._completion_delivery_lock = threading.Lock()
    runner._completion_deliveries_inflight = set()
    runner._completion_deliveries_delivered = OrderedDict()
    runner._completion_delivery_retention = 2048
    runner._background_tasks = set()
    runner._classify_completion_target = AsyncMock(return_value='retry')
    for _ in range(5):
        assert asyncio.run(runner._deliver_async_delegation_group(events)) is False
    for event in events:
        row = delegation.get_durable_delegation(event['delegation_id'])
        assert row['delivery_state'] == 'pending'
        assert row['delivery_attempts'] == 0
    print('native restart preservation PASS')


def test_pending_completion_survives_native_windows_process_restart(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    if sys.platform != 'win32':
        pytest.skip('Native Windows process restart')
    from hermes_cli._subprocess_compat import windows_hide_flags
    root = Path(__file__).resolve().parents[2]
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT'}}
    home = tmp_path / 'home'
    home.mkdir()
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
               APPDATA=str(home), LOCALAPPDATA=str(home), TEMP=str(tmp_path), TMP=str(tmp_path),
               PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', HERMES_TEST_ISOLATION='1')
    script = "import runpy,sys;sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[2])['_native_restart_worker'](sys.argv[3]=='seed')"
    for phase in ['seed', 'restore']:
        result = subprocess.run([sys.executable, '-I', '-c', script, str(root), __file__, phase],
                                cwd=root, env=env, capture_output=True, encoding='utf-8',
                                creationflags=windows_hide_flags(), timeout=40)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'native restart preservation PASS' in result.stdout
