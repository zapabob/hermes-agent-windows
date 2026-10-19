"""Deterministic native process ownership at session-kernel cell boundaries."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import socket
import threading
import time
import uuid

import pytest

pytestmark = pytest.mark.windows_only


class ObservedLock:
    """Signal an acquisition after the real registry lock has been released."""

    def __init__(self, lock, thread_name, selected):
        self.lock, self.thread_name, self.selected = lock, thread_name, selected

    def __enter__(self):
        self.lock.acquire()
        return self

    def __exit__(self, *_exc):
        self.lock.release()
        if threading.current_thread().name == self.thread_name:
            self.selected.set()


@pytest.fixture
def native_probe(monkeypatch, record_property):
    from tools import code_execution_tool as tool
    from tools import code_kernel as kernel
    from tools.approval import reset_current_session_key, set_current_session_key

    kernel.shutdown_all_kernels()
    cfg = {'mode': 'strict', 'kernel_mode': 'session', 'timeout': 8,
           'max_session_kernels': 8, 'kernel_idle_timeout': 1800}
    monkeypatch.setattr(tool, '_load_config', lambda: cfg)
    monkeypatch.setenv('TERMINAL_ENV', 'local')
    monkeypatch.setenv('OWNED_SYNTHETIC_SECRET', 'synthetic-cell-secret')
    children, kernels, threads, responses = [], [], [], []
    actual_popen, actual_spawn = kernel.subprocess.Popen, kernel._spawn

    def popen(args, *a, **kw):
        args = list(args)
        if len(args) > 1 and Path(str(args[1])).name == 'hermes_kernel_runner.py':
            args.append('--owned-kernel-nonce=' + uuid.uuid4().hex)
        proc = actual_popen(args, *a, **kw)
        if len(args) > 1 and Path(str(args[1])).name == 'hermes_kernel_runner.py':
            children.append(proc)
        return proc

    def spawn(owned_kernel, **kwargs):
        kernels.append(owned_kernel)
        return actual_spawn(owned_kernel, **kwargs)

    monkeypatch.setattr(kernel.subprocess, 'Popen', popen)
    monkeypatch.setattr(kernel, '_spawn', spawn)

    class Probe:
        def run(self, code, *, owner='owned-conversation', reset=False):
            token = set_current_session_key(owner)
            try:
                response = json.loads(tool.execute_code(code, task_id='owned-turn', reset=reset))
                responses.append(response)
                return response
            finally:
                reset_current_session_key(token)

        def start(self, code, *, name='owned-first', owner='owned-conversation', reset=False):
            result = {}

            def work():
                try:
                    result['response'] = self.run(code, owner=owner, reset=reset)
                except BaseException as exc:
                    result['exception'] = repr(exc)

            thread = threading.Thread(target=work, name=name)
            threads.append(thread)
            thread.start()
            return thread, result

        def finish(self, thread, result):
            thread.join(10)
            assert not thread.is_alive(), 'Owned cell failed to settle after its barrier release'
            assert 'exception' not in result, result
            return result['response']

        def counter(self, *, owner='owned-conversation', reset=False):
            return self.run(COUNTER, owner=owner, reset=reset)

        @property
        def registered(self):
            return list(kernel._KERNELS.values())

    probe = Probe()
    probe.kernel, probe.cfg, probe.children, probe.kernels = kernel, cfg, children, kernels
    yield probe
    # Every kernel seen by _spawn is retained, including a process orphaned by a bad registry pop.
    for owned_kernel in list(kernel._KERNELS.values()) + kernels:
        kernel._teardown(owned_kernel)
    kernel.shutdown_all_kernels()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
    records = []
    for proc in children:
        proc.wait(timeout=10)
        records.append({'pid': proc.pid, 'argv': [str(a) for a in proc.args],
                        'exit': proc.returncode, 'retained_process_handle': int(proc._handle)})
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    # A buffered late write to an exited Windows child may
                    # fail again on close; the stream must still be closed.
                    assert proc.poll() is not None and pipe.closed
    record_property('all_actual_kernel_popen', json.dumps(records))
    record_property('cell_responses', json.dumps(responses))
    assert all(proc.poll() is not None for proc in children)
    assert not kernel._OWNED_KERNELS, 'Disposed kernels retained ownership after all cells settled'


COUNTER = '''import json, os, sys
counter = globals().get('counter', 0) + 1
print(json.dumps({'counter': counter, 'pid': os.getpid(), 'exe': sys.executable,
                  'nonce': sys.argv[-1], 'secret_absent': 'OWNED_SYNTHETIC_SECRET' not in os.environ}))
'''


def observation(response, *, check_secret=True):
    assert response['status'] == 'success', response
    value = json.loads(response['output'].strip())
    if check_secret:
        assert value['secret_absent']
    assert value['nonce'].startswith('--owned-kernel-nonce=')
    assert value['pid'] > 0 and Path(value['exe']).is_file()
    return value


def test_pending_same_owner_cells_keep_one_actual_process(native_probe, monkeypatch):
    probe = native_probe
    ready, release, selected = threading.Event(), threading.Event(), threading.Event()
    original_spawn = probe.kernel._spawn

    def paused_spawn(kernel, **kwargs):
        if threading.current_thread().name == 'owned-first':
            ready.set()
            assert release.wait(10)
        return original_spawn(kernel, **kwargs)

    monkeypatch.setattr(probe.kernel, '_spawn', paused_spawn)
    monkeypatch.setattr(probe.kernel, '_KERNELS_LOCK', ObservedLock(
        probe.kernel._KERNELS_LOCK, 'owned-second', selected))
    first = second = None
    try:
        first = probe.start(COUNTER)
        assert ready.wait(10), 'First cell never reached proc=None spawn barrier'
        second = probe.start(COUNTER, name='owned-second')
        assert selected.wait(10), 'Second cell never completed registry selection'
    finally:
        release.set()
    first_response, second_response = [probe.finish(*item) for item in (first, second)]
    a, b = observation(first_response), observation(second_response)
    assert len(probe.children) == len(probe.registered) == 1
    assert [a['counter'], b['counter']] == [1, 2]
    assert (a['pid'], a['nonce']) == (b['pid'], b['nonce'])
    assert probe.registered[0].proc is probe.children[0]
    assert not first_response['kernel']['reused'] and second_response['kernel']['reused']
    assert not probe.registered[0].cell_authority.active


@pytest.mark.parametrize('sweep', ['idle', 'cap'])
def test_active_cell_survives_other_owner_cleanup(native_probe, sweep):
    probe = native_probe
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(10)
    port = listener.getsockname()[1]
    code = (f"import socket\nbarrier = socket.create_connection(('127.0.0.1', {port}))\n"
            "barrier.sendall(b'owned-ready')\nassert barrier.recv(1) == b'g'\nbarrier.close()\n" +
            COUNTER.replace(", 'secret_absent': 'OWNED_SYNTHETIC_SECRET' not in os.environ", ''))
    connection = None
    thread, result = probe.start(code)
    try:
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            pytest.fail(f'Owned cell did not enter its native barrier: {result!r}')
        connection.settimeout(10)
        assert connection.recv(64) == b'owned-ready'
        active = probe.registered[0]
        if sweep == 'idle':
            probe.cfg['kernel_idle_timeout'] = 1
            active.last_used = time.monotonic() - 10
        else:
            probe.cfg['max_session_kernels'] = 1
        other = observation(probe.counter(owner='owned-other'))
        assert other['counter'] == 1
        assert active.alive(), 'An attached native cell was torn down by another owner'
        assert active in probe.registered
    finally:
        if connection is not None:
            try:
                connection.sendall(b'g')
            except OSError:
                pass
            connection.close()
        listener.close()
    value = observation(probe.finish(thread, result), check_secret=False)
    assert value['counter'] == 1
    again = observation(probe.counter())
    assert again['counter'] == 2 and again['pid'] == value['pid']


@pytest.mark.parametrize('ending', ['reset-success', 'timeout', 'exit', 'death', 'failure'])
def test_old_cell_settlement_cannot_remove_reset_replacement(native_probe, monkeypatch, ending):
    probe = native_probe
    ready, release = threading.Event(), threading.Event()
    original_spawn = probe.kernel._spawn
    offset = {'value': 0.0}

    class Clock:
        def monotonic(self):
            return time.monotonic() + (offset['value'] if threading.current_thread().name == 'owned-first' else 0)

    monkeypatch.setattr(probe.kernel, 'time', Clock())

    class HeldResponse:
        def __init__(self, source):
            self.source = source
            self.held = False

        def put(self, value):
            self.source.put(value)

        def get(self, **kwargs):
            value = self.source.get(**kwargs)
            if not self.held:
                self.held = True
                ready.set()
                assert release.wait(10)
                if ending == 'failure':
                    raise OSError('owned injected response failure')
                if ending == 'timeout':
                    offset['value'] = 100.0
                    raise queue.Empty
            return value

    def capture_response(kernel, **kwargs):
        original_spawn(kernel, **kwargs)
        if threading.current_thread().name == 'owned-first':
            kernel.response_q = HeldResponse(kernel.response_q)

    monkeypatch.setattr(probe.kernel, '_spawn', capture_response)
    code = 'import sys; sys.exit(0)' if ending == 'exit' else (
        'import os; os._exit(23)' if ending == 'death' else COUNTER)
    thread, result = probe.start(code)
    try:
        assert ready.wait(10), 'No actual child response reached the settlement barrier'
        old = probe.kernels[0]
        fresh = observation(probe.counter(reset=True))
        replacement = probe.registered[0]
        assert replacement is not old
    finally:
        release.set()
    settled = probe.finish(thread, result)
    expected = {'reset-success': 'success', 'timeout': 'timeout', 'exit': 'success',
                'death': 'error', 'failure': 'error'}
    assert settled['status'] == expected[ending], settled
    assert probe.registered == [replacement], 'Old cleanup removed the replacement registry entry'
    assert not old.alive() and not old.cell_authority.active
    again = observation(probe.counter())
    assert again['counter'] == 2 and (again['pid'], again['nonce']) == (fresh['pid'], fresh['nonce'])


@pytest.mark.parametrize('cleanup', ['idle', 'cap'])
def test_settled_kernel_cleanup_remains_effective(native_probe, cleanup):
    probe = native_probe
    first = observation(probe.counter())
    old = probe.registered[0]
    if cleanup == 'idle':
        probe.cfg['kernel_idle_timeout'] = 1
        old.last_used = time.monotonic() - 10
    else:
        probe.cfg['max_session_kernels'] = 1
    second = observation(probe.counter(owner='owned-other'))
    old.proc.wait(timeout=10)
    assert not old.alive() and old not in probe.registered
    assert len(probe.registered) == 1
    assert first['pid'] != second['pid'] and first['nonce'] != second['nonce']


def test_clear_finds_a_settled_orphan_until_native_disposal(native_probe, monkeypatch, record_property):
    import ctypes
    from ctypes import wintypes
    from tools.approval import clear_session

    probe = native_probe
    response_ready, release_response = threading.Event(), threading.Event()
    disposal_ready, release_disposal = threading.Event(), threading.Event()
    original_spawn, original_teardown = probe.kernel._spawn, probe.kernel._teardown
    captured = {}

    class HeldResponse:
        def __init__(self, source):
            self.source = source

        def put(self, value):
            self.source.put(value)

        def get(self, **kwargs):
            value = self.source.get(**kwargs)
            captured['native'] = json.loads(value['stdout'].strip())
            response_ready.set()
            assert release_response.wait(10)
            return value

    def hold_response(kernel, **kwargs):
        original_spawn(kernel, **kwargs)
        if threading.current_thread().name == 'owned-first':
            captured['old'] = kernel
            kernel.response_q = HeldResponse(kernel.response_q)

    def hold_final_disposal(kernel):
        if threading.current_thread().name == 'owned-first' and kernel is captured.get('old'):
            disposal_ready.set()
            assert release_disposal.wait(10)
        return original_teardown(kernel)

    monkeypatch.setattr(probe.kernel, '_spawn', hold_response)
    monkeypatch.setattr(probe.kernel, '_teardown', hold_final_disposal)
    thread, result = probe.start(COUNTER)
    native = ctypes.WinDLL('kernel32', use_last_error=True)
    native.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    native.OpenProcess.restype = wintypes.HANDLE
    native.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    native.WaitForSingleObject.restype = wintypes.DWORD
    native.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = None
    try:
        assert response_ready.wait(10)
        old = captured['old']
        first = captured['native']
        handle = native.OpenProcess(0x100000 | 0x1000, False, first['pid'])
        assert handle, ctypes.get_last_error()
        observation(probe.counter(reset=True))
        reset_replacement = probe.registered[0]
        release_response.set()
        assert disposal_ready.wait(10), 'Old cell never reached its final disposal barrier'
        assert old.attached == 0 and old not in probe.registered and old.alive()
        assert not old.cell_authority.active
        clear_session('owned-conversation')
        assert native.WaitForSingleObject(handle, 0) == 0, 'settled orphan survived owner clear return'
        assert old.proc.poll() is not None and not reset_replacement.alive()
        assert probe.registered == []
        fresh = observation(probe.counter())
        replacement = probe.registered[0]
    finally:
        release_response.set()
        release_disposal.set()
        if handle:
            native.CloseHandle(handle)
    settled = observation(probe.finish(thread, result))
    assert settled['pid'] == first['pid'] and settled['nonce'] == first['nonce']
    assert old not in probe.kernel._OWNED_KERNELS and not old.alive()
    assert probe.registered == [replacement]
    again = observation(probe.counter())
    assert fresh['counter'] == 1 and again['counter'] == 2
    assert (fresh['pid'], fresh['nonce']) == (again['pid'], again['nonce'])
    record_property('settled_orphan_clear_boundary', json.dumps({
        'native_pid': first['pid'], 'nonce': first['nonce'], 'attached_at_barrier': 0,
        'not_in_reusable_registry_at_barrier': True, 'native_alive_before_clear': True,
        'native_handle_signaled_at_clear_return': True, 'final_disposal_released_after_clear': True,
        'replacement_counter': again['counter'], 'tracking_removed_after_disposal': True}))


@pytest.mark.parametrize('disposal', ['idle', 'cap', 'reset', 'owner-clear', 'all-shutdown'])
def test_second_clear_finds_settled_kernel_pending_disposal(native_probe, monkeypatch, record_property, disposal):
    import ctypes
    from ctypes import wintypes
    from tools.approval import clear_session

    probe = native_probe
    first = observation(probe.counter())
    old = probe.registered[0]
    ready, release = threading.Event(), threading.Event()
    original_teardown = probe.kernel._teardown

    def pause(kernel):
        if threading.current_thread().name == 'owned-sweeper' and kernel is old:
            ready.set()
            assert release.wait(10)
        return original_teardown(kernel)

    monkeypatch.setattr(probe.kernel, '_teardown', pause)
    if disposal == 'idle':
        probe.cfg['kernel_idle_timeout'] = 1
        old.last_used = time.monotonic() - 10
    elif disposal == 'cap':
        probe.cfg['max_session_kernels'] = 1
    if disposal in {'idle', 'cap', 'reset'}:
        thread, result = probe.start(COUNTER, name='owned-sweeper',
            owner='owned-conversation' if disposal == 'reset' else 'owned-other', reset=disposal == 'reset')
    else:
        result = {}

        def dispose():
            try:
                if disposal == 'owner-clear':
                    clear_session('owned-conversation')
                else:
                    probe.kernel.shutdown_all_kernels()
            except BaseException as exc:
                result['exception'] = repr(exc)

        thread = threading.Thread(target=dispose, name='owned-sweeper')
        thread.start()

    native = ctypes.WinDLL('kernel32', use_last_error=True)
    native.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    native.OpenProcess.restype = wintypes.HANDLE
    native.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    native.WaitForSingleObject.restype = wintypes.DWORD
    native.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = native.OpenProcess(0x100000 | 0x1000, False, first['pid'])
    assert handle, ctypes.get_last_error()
    try:
        assert ready.wait(10), 'Sweeper did not reach the actual pending-disposal barrier'
        assert old not in probe.registered and old.alive()
        clear_session('owned-conversation')
        assert native.WaitForSingleObject(handle, 0) == 0, f'{disposal} kernel survived second clear return'
        assert old.proc.poll() is not None
    finally:
        release.set()
        thread.join(10)
        native.CloseHandle(handle)
    assert not thread.is_alive() and 'exception' not in result, result
    if disposal in {'idle', 'cap', 'reset'}:
        response = probe.finish(thread, result)
        if disposal == 'reset':
            assert response['status'] == 'error', response
        else:
            assert observation(response)['counter'] == 1
    fresh = observation(probe.counter())
    again = observation(probe.counter())
    assert fresh['counter'] == 1 and again['counter'] == 2
    assert (fresh['pid'], fresh['nonce']) == (again['pid'], again['nonce'])
    assert first['nonce'] != fresh['nonce']
    record_property('settled_disposal_clear_boundary', json.dumps({
        'disposal': disposal, 'native_pid': first['pid'], 'nonce': first['nonce'],
        'attached_at_barrier': 0, 'not_in_reusable_registry_at_barrier': True,
        'native_handle_signaled_at_second_clear_return': True, 'replacement_counter': again['counter']}))


def test_second_clear_waits_for_actual_native_kill(native_probe, monkeypatch, record_property):
    import ctypes
    from ctypes import wintypes
    from tools import code_execution_tool as tool
    from tools.approval import clear_session

    probe = native_probe
    first = observation(probe.counter())
    old = probe.registered[0]
    killing, release_kill, second_discovered, second_returned = (threading.Event() for _ in range(4))
    original_kill, original_teardown = tool._kill_process_group, probe.kernel._teardown
    errors = []

    def pause_kill(proc, **kwargs):
        if threading.current_thread().name == 'owned-first-clear' and proc is old.proc:
            killing.set()
            assert release_kill.wait(10)
        return original_kill(proc, **kwargs)

    def observe_second(kernel):
        if threading.current_thread().name == 'owned-second-clear' and kernel is old:
            second_discovered.set()
        return original_teardown(kernel)

    def clear(second=False):
        try:
            clear_session('owned-conversation')
            if second:
                second_returned.set()
        except BaseException as exc:
            errors.append(repr(exc))

    monkeypatch.setattr(tool, '_kill_process_group', pause_kill)
    monkeypatch.setattr(probe.kernel, '_teardown', observe_second)
    first_clear = threading.Thread(target=clear, name='owned-first-clear')
    second_clear = threading.Thread(target=lambda: clear(True), name='owned-second-clear')
    native = ctypes.WinDLL('kernel32', use_last_error=True)
    native.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    native.OpenProcess.restype = wintypes.HANDLE
    native.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    native.WaitForSingleObject.restype = wintypes.DWORD
    native.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = native.OpenProcess(0x100000 | 0x1000, False, first['pid'])
    assert handle, ctypes.get_last_error()
    try:
        first_clear.start()
        assert killing.wait(10)
        assert old not in probe.registered and old.alive()
        second_clear.start()
        assert not second_returned.wait(0.1), 'Second clear returned before the pending native kill'
        assert second_discovered.wait(3), 'Second clear lost disposal ownership inside teardown'
    finally:
        release_kill.set()
        first_clear.join(10)
        if second_clear.ident is not None:
            second_clear.join(10)
        try:
            assert native.WaitForSingleObject(handle, 0) == 0
        finally:
            native.CloseHandle(handle)
    assert not first_clear.is_alive() and not second_clear.is_alive() and not errors, errors
    assert second_returned.is_set() and old not in probe.kernel._OWNED_KERNELS
    fresh = observation(probe.counter())
    assert fresh['counter'] == 1 and fresh['nonce'] != first['nonce']
    assert observation(probe.counter())['counter'] == 2
    record_property('inside_native_disposal_clear_boundary', json.dumps({
        'native_pid': first['pid'], 'nonce': first['nonce'],
        'second_clear_discovered_kernel_during_native_kill': True,
        'second_clear_returned_only_after_native_kill': True,
        'native_handle_signaled_at_clear_return': True, 'replacement_counter': 2}))


def test_clear_session_remains_an_immediate_native_boundary(native_probe):
    from tools.approval import clear_session

    probe = native_probe
    value = observation(probe.counter())
    old = probe.registered[0]
    clear_session('owned-conversation')
    old.proc.wait(timeout=10)
    assert probe.registered == [] and old.stop_event.is_set() and not old.alive()
    assert not old.cell_authority.active
    result = observation(probe.counter())
    assert result['counter'] == 1 and result['nonce'] != value['nonce']


def test_clear_session_kills_even_an_attached_native_cell(native_probe, monkeypatch):
    from tools.approval import clear_session

    probe = native_probe
    ready, release = threading.Event(), threading.Event()
    original_spawn = probe.kernel._spawn

    class HeldResponse:
        def __init__(self, source):
            self.source = source

        def put(self, value):
            self.source.put(value)

        def get(self, **kwargs):
            value = self.source.get(**kwargs)
            ready.set()
            assert release.wait(10)
            return value

    def hold(kernel, **kwargs):
        original_spawn(kernel, **kwargs)
        kernel.response_q = HeldResponse(kernel.response_q)

    monkeypatch.setattr(probe.kernel, '_spawn', hold)
    thread, result = probe.start(COUNTER)
    try:
        assert ready.wait(10)
        old = probe.registered[0]
        assert old.cell_authority.active and old.alive()
        clear_session('owned-conversation')
        old.proc.wait(timeout=10)
        assert not old.alive() and old.stop_event.is_set() and probe.registered == []
    finally:
        release.set()
    observation(probe.finish(thread, result))
    assert not old.cell_authority.active
    fresh = observation(probe.counter())
    assert fresh['counter'] == 1


@pytest.mark.parametrize('queued', [False, True])
@pytest.mark.parametrize('detached', [False, True])
def test_clear_before_spawn_cancels_selected_cells(native_probe, monkeypatch, tmp_path, queued, detached):
    from tools.approval import clear_session

    probe = native_probe
    ready, release, selected = threading.Event(), threading.Event(), threading.Event()
    original_spawn = probe.kernel._spawn
    marker = tmp_path / 'cancelled-cell-effect.txt'
    code = COUNTER + f"from pathlib import Path\nPath({str(marker)!r}).write_text('effect', encoding='utf-8')\n"

    def pause(kernel, **kwargs):
        if threading.current_thread().name == 'owned-first':
            ready.set()
            assert release.wait(10)
        return original_spawn(kernel, **kwargs)

    monkeypatch.setattr(probe.kernel, '_spawn', pause)
    monkeypatch.setattr(probe.kernel, '_KERNELS_LOCK', ObservedLock(
        probe.kernel._KERNELS_LOCK, 'owned-second', selected))
    pending = []
    try:
        pending.append(probe.start(code))
        assert ready.wait(10)
        old = probe.registered[0]
        assert old.proc is None
        if queued:
            pending.append(probe.start(code, name='owned-second'))
            assert selected.wait(10)
        if detached:
            observation(probe.counter(reset=True))
        clear_session('owned-conversation')
        assert old.stop_event.is_set() and probe.registered == []
        fresh = observation(probe.counter())
        replacement = probe.registered[0]
    finally:
        release.set()
    responses = [probe.finish(*item) for item in pending]
    assert all(response['status'] == 'error' for response in responses), responses
    assert old.proc is None and not marker.exists()
    assert len(probe.children) == (2 if detached else 1) and probe.registered == [replacement]
    again = observation(probe.counter())
    assert fresh['counter'] == 1 and again['counter'] == 2
    assert (fresh['pid'], fresh['nonce']) == (again['pid'], again['nonce'])


@pytest.mark.parametrize('publication', ['before-popen', 'after-popen'])
def test_clear_waits_for_atomic_process_publication(native_probe, monkeypatch, tmp_path, publication):
    from tools.approval import clear_session

    probe = native_probe
    ready, release, clearing, cleared = (threading.Event() for _ in range(4))
    original_popen, original_teardown = probe.kernel.subprocess.Popen, probe.kernel._teardown
    marker = tmp_path / 'publication-effect.txt'
    code = COUNTER + f"from pathlib import Path\nPath({str(marker)!r}).write_text('effect', encoding='utf-8')\n"

    def pause_popen(args, *a, **kw):
        if threading.current_thread().name != 'owned-first':
            return original_popen(args, *a, **kw)
        if publication == 'after-popen':
            proc = original_popen(args, *a, **kw)
        ready.set()
        assert release.wait(10)
        return proc if publication == 'after-popen' else original_popen(args, *a, **kw)

    def observe_clear(kernel):
        if threading.current_thread().name == 'owned-clear':
            clearing.set()
        return original_teardown(kernel)

    def clear():
        clear_session('owned-conversation')
        cleared.set()

    monkeypatch.setattr(probe.kernel.subprocess, 'Popen', pause_popen)
    monkeypatch.setattr(probe.kernel, '_teardown', observe_clear)
    thread, result = probe.start(code)
    clearer = threading.Thread(target=clear, name='owned-clear')
    try:
        assert ready.wait(10)
        old = probe.registered[0]
        assert old.proc is None
        clearer.start()
        assert clearing.wait(10)
        # Disposal must not return while an un-published Popen can still escape.
        assert not cleared.wait(0.1)
    finally:
        release.set()
        if clearer.ident is not None:
            clearer.join(10)
    assert cleared.is_set() and not clearer.is_alive()
    response = probe.finish(thread, result)
    assert response['status'] == 'error', response
    assert old.proc is not None and old.proc.poll() is not None
    assert not marker.exists() and probe.registered == []
    assert not old.cell_authority or not old.cell_authority.active
    assert observation(probe.counter())['counter'] == 1


def test_clear_after_check_before_pipe_write_has_no_native_effect(native_probe, monkeypatch, tmp_path, record_property):
    import ctypes
    from ctypes import wintypes
    from tools.approval import clear_session

    probe = native_probe
    initial = observation(probe.counter())
    old = probe.registered[0]
    ready, release, cleared = threading.Event(), threading.Event(), threading.Event()
    marker = tmp_path / 'late-pipe-write-effect.txt'
    code = COUNTER + f"from pathlib import Path\nPath({str(marker)!r}).write_text('effect', encoding='utf-8')\n"
    real_stdin = old.proc.stdin

    class HeldWrite:
        def write(self, data):
            ready.set()
            assert release.wait(10)
            return real_stdin.write(data)

        def __getattr__(self, name):
            return getattr(real_stdin, name)

    native = ctypes.WinDLL('kernel32', use_last_error=True)
    native.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    native.OpenProcess.restype = wintypes.HANDLE
    native.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    native.WaitForSingleObject.restype = wintypes.DWORD
    native.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = native.OpenProcess(0x100000 | 0x1000, False, initial['pid'])
    assert handle, ctypes.get_last_error()

    def clear():
        clear_session('owned-conversation')
        cleared.set()

    monkeypatch.setattr(old.proc, 'stdin', HeldWrite())
    thread, result = probe.start(code)
    clearer = threading.Thread(target=clear, name='owned-clear')
    try:
        assert ready.wait(10)
        assert old.cell_authority.active
        clearer.start()
        # clear must finish while write remains paused outside lifecycle_lock.
        assert cleared.wait(3), 'clear waited for the blocked pipe writer'
        assert native.WaitForSingleObject(handle, 0) == 0, 'actual interpreter survived clear return'
        assert old.proc.poll() is not None and probe.registered == []
        fresh = observation(probe.counter())
        replacement = probe.registered[0]
    finally:
        release.set()
        if clearer.ident is not None:
            clearer.join(10)
        native.CloseHandle(handle)
    response = probe.finish(thread, result)
    assert response['status'] == 'error' and not marker.exists(), response
    assert not old.cell_authority.active and probe.registered == [replacement]
    again = observation(probe.counter())
    assert fresh['counter'] == 1 and again['counter'] == 2
    assert (fresh['pid'], fresh['nonce']) == (again['pid'], again['nonce'])
    record_property('clear_write_boundary', json.dumps({
        'native_pid': initial['pid'], 'nonce': initial['nonce'],
        'actual_interpreter_handle_signaled_at_clear_return': True,
        'write_released_after_clear_return': True, 'late_cell_status': response['status'],
        'marker_exists_after_settlement': marker.exists(), 'replacement_counter': again['counter']}))


def test_reset_preserves_a_selected_pending_cell(native_probe, monkeypatch):
    probe = native_probe
    ready, release = threading.Event(), threading.Event()
    original_spawn = probe.kernel._spawn

    def pause(kernel, **kwargs):
        if threading.current_thread().name == 'owned-first':
            ready.set()
            assert release.wait(10)
        return original_spawn(kernel, **kwargs)

    monkeypatch.setattr(probe.kernel, '_spawn', pause)
    thread, result = probe.start(COUNTER)
    try:
        assert ready.wait(10)
        old = probe.registered[0]
        fresh = observation(probe.counter(reset=True))
        replacement = probe.registered[0]
        assert not old.stop_event.is_set() and old.proc is None
    finally:
        release.set()
    previous = observation(probe.finish(thread, result))
    assert previous['counter'] == fresh['counter'] == 1
    assert previous['nonce'] != fresh['nonce']
    assert not old.alive() and not old.cell_authority.active
    assert probe.registered == [replacement]
    assert observation(probe.counter())['counter'] == 2


@pytest.mark.parametrize('bad_token', [None, 'owned-wrong-token'])
def test_native_tcp_rpc_preserves_auth_and_retired_cell_refusal(native_probe, monkeypatch, bad_token):
    import model_tools

    probe = native_probe
    first = observation(probe.counter())
    kernel = probe.registered[0]
    dispatched = []
    monkeypatch.setattr(model_tools, 'handle_function_call', lambda *a, **kw: dispatched.append((a, kw)))
    replies = []
    with socket.create_connection(kernel.server_sock.getsockname(), timeout=5) as client:
        client.settimeout(5)
        for token in (bad_token, kernel.rpc_token):
            request = {'tool': 'terminal', 'args': {'command': 'owned-must-not-execute'}}
            if token is not None:
                request['token'] = token
            client.sendall((json.dumps(request) + '\n').encode())
            response = b''
            while b'\n' not in response:
                chunk = client.recv(4096)
                assert chunk
                response += chunk
            replies.append(json.loads(response.split(b'\n')[0]))
    assert 'Unauthorized RPC request' in json.dumps(replies[0])
    assert 'No active execute_code cell' in json.dumps(replies[1])
    assert dispatched == [] and not kernel.cell_authority.active
    again = observation(probe.counter())
    assert again['counter'] == 2 and (again['pid'], again['nonce']) == (first['pid'], first['nonce'])
