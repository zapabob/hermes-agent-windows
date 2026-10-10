"""Real Windows execution must survive growing credential-exclusion scripts."""
import hashlib
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.environments import local

pytestmark = pytest.mark.windows_only


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "owned-home"))
    monkeypatch.setattr(local, "_resolve_shell_init_files", lambda: [])
    instance = local.LocalEnvironment(cwd=str(tmp_path), timeout=15)
    try:
        yield instance
    finally:
        instance.cleanup()


def grow_exclusions(environment):
    # Synthetic internal names exercise the real mandatory stripping owner.
    for index in range(60):
        name = f"GATEWAY_RELAY_TEST_{index}_" + "X" * 180 + "_SECRET"
        environment.env[name] = "TEST_ONLY_SYNTHETIC_NEVER_USE"


def execute_effect(environment, command, **kwargs):
    try:
        return environment.execute(command, **kwargs)
    except RuntimeError as exc:
        assert False, f"Authorized owned command failed before its effect: {exc}"


def test_small_command_control_has_real_effect(environment, tmp_path):
    marker = tmp_path / "small-effect.txt"
    result = execute_effect(environment, "printf control > " + shlex.quote(marker.as_posix()))
    assert result["returncode"] == 0, result
    assert marker.read_bytes() == b"control"


@pytest.mark.parametrize("short_command", ["true", "echo ./", "date", "cd ."])
def test_short_command_after_accumulation_has_real_effect(environment, tmp_path, monkeypatch, short_command):
    grow_exclusions(environment)
    attempted = []
    spawn = environment._spawn_bash

    def observe(script, **kwargs):
        args = [local._find_bash(), "-c", script]
        encoded = subprocess.list2cmdline(args).encode("utf-16-le")
        attempted.append(len(encoded) // 2)
        # The script contains only synthetic references; print metrics, not values.
        print({"attempted_utf16_units": attempted[-1], "argv_sha256": hashlib.sha256(encoded).hexdigest()})
        return spawn(script, **kwargs)

    monkeypatch.setattr(environment, "_spawn_bash", observe)
    marker = tmp_path / "short-effect.txt"
    result = execute_effect(environment, short_command + " && printf once > " + shlex.quote(marker.as_posix()))
    assert attempted and attempted[0] >= 30000
    assert result["returncode"] == 0, result
    assert marker.read_bytes() == b"once"


def test_caller_stdin_is_byte_exact_with_large_wrapper(environment, tmp_path):
    grow_exclusions(environment)
    target = tmp_path / "stdin.bin"
    payload = "first\nsecond\r\n日本語\n"
    result = execute_effect(environment, "cat > " + shlex.quote(target.as_posix()), stdin_data=payload)
    assert result["returncode"] == 0, result
    assert target.read_bytes() == payload.encode("utf-8")


def test_exit_cwd_and_snapshot_survive_large_wrapper(environment, tmp_path):
    grow_exclusions(environment)
    directory = tmp_path / "working directory"
    directory.mkdir()
    result = execute_effect(environment, "cd " + environment._quote_shell_path(str(directory)) + "; export ORDINARY_TEST=retained; printf failed; false")
    assert result["returncode"] == 1, result
    assert "failed" in result["output"]
    assert Path(local._msys_to_windows_path(environment.cwd)).resolve() == directory.resolve()
    result = execute_effect(environment, 'printf "%s" "$ORDINARY_TEST"')
    assert result["returncode"] == 0 and result["output"] == "retained", result


def test_large_unicode_literal_matches_bounded_bash_parsing(environment, tmp_path):
    target = tmp_path / "unicode.bin"
    unit = "日本語 😀 ' \\\nline\rnext\n"
    control = execute_effect(environment, "printf %s " + shlex.quote(unit) + " > " + shlex.quote(target.as_posix()))
    assert control["returncode"] == 0, control
    expected_unit = target.read_bytes()
    # Native Git Bash ignores literal CR in both invocation sizes. Stdin
    # fidelity and the held payload's original bytes have separate oracles.
    assert expected_unit == unit.encode("utf-8").replace(b"\r", b"")
    payload = unit * 2500
    result = execute_effect(environment, "printf %s " + shlex.quote(payload) + " > " + shlex.quote(target.as_posix()))
    assert result["returncode"] == 0, result
    assert target.read_bytes() == expected_unit * 2500


@pytest.mark.parametrize("large", [False, True])
def test_top_level_return_keeps_exit_snapshot_and_cwd_tail(environment, tmp_path, large):
    if large:
        grow_exclusions(environment)
    directory = tmp_path / "return context"
    directory.mkdir()
    command = "cd " + environment._quote_shell_path(str(directory)) + "; export RETURN_CONTEXT=kept; return 7"
    result = execute_effect(environment, command)
    assert result["returncode"] == 2, result
    assert "return" in result["output"]
    # The rejected top-level return must still reach the ordinary snapshot tail.
    assert Path(local._msys_to_windows_path(environment.cwd)).resolve() == directory.resolve()
    result = execute_effect(environment, 'printf "%s" "$RETURN_CONTEXT"')
    assert result["returncode"] == 0 and result["output"] == "kept", result


@pytest.mark.parametrize("large", [False, True])
def test_eval_context_has_no_script_source_or_return_trap_effect(environment, tmp_path, large):
    baseline = execute_effect(environment, 'printf "%s" "$0"')
    assert baseline["returncode"] == 0
    if large:
        grow_exclusions(environment)
    target = tmp_path / "context.txt"
    command = "trap 'printf unexpected-return' RETURN; printf '%s:%s' \"${BASH_SOURCE[*]}\" \"$0\" > " + shlex.quote(target.as_posix())
    result = execute_effect(environment, command)
    assert result["returncode"] == 0 and "unexpected-return" not in result["output"], result
    observed = target.read_text(encoding="utf-8")
    assert observed == ":" + baseline["output"], observed


def test_oversized_final_invocation_still_refuses_and_cleans(environment, monkeypatch):
    launched = []
    original = local.subprocess.Popen

    def observe(*args, **kwargs):
        launched.append(args)
        if len(str(args[0][0])) >= 30000:
            raise RuntimeError("Windows terminal command length exceeds safe limit")
        return original(*args, **kwargs)

    monkeypatch.setattr(local, "_find_bash", lambda: "X" * 31000)
    monkeypatch.setattr(local.subprocess, "Popen", observe)
    before = set(Path(environment.get_temp_dir()).iterdir())
    with pytest.raises(RuntimeError, match="command length exceeds safe limit"):
        environment.execute("true")
    assert not launched
    assert set(Path(environment.get_temp_dir()).iterdir()) == before


def test_failed_spawn_removes_only_its_owned_files(environment, monkeypatch):
    grow_exclusions(environment)
    before = set(Path(environment.get_temp_dir()).iterdir())

    def fail(*args, **kwargs):
        raise OSError("owned injected spawn failure")

    monkeypatch.setattr(local.subprocess, "Popen", fail)
    with pytest.raises(OSError, match="owned injected spawn failure"):
        environment.execute("true")
    assert set(Path(environment.get_temp_dir()).iterdir()) == before


def test_held_native_children_keep_independent_scripts_and_snapshot_copies(environment, tmp_path, monkeypatch):
    import psutil

    grow_exclusions(environment)
    probe = tmp_path / "held child.py"
    probe.write_text(
        "import os,pathlib,sys,time\n"
        "ready,release=map(pathlib.Path,sys.argv[1:])\n"
        "ready.write_text(str(os.getpid()),encoding='utf-8')\n"
        "deadline=time.monotonic()+15\n"
        "while not release.exists() and time.monotonic()<deadline: time.sleep(.02)\n"
        "assert release.exists(), 'owned child release missing'\n"
        "print('owned child completed')\n", encoding="utf-8", newline="\n",
    )
    owned = []
    identities = []
    try:
        for label in ("a", "b"):
            ready, release = tmp_path / (label + ".pid"), tmp_path / (label + ".release")
            command = "# payload retains a literal CR here\r\n" + " ".join(shlex.quote(value.replace("\\", "/")) for value in [sys.executable, "-I", str(probe), str(ready), str(release)])
            wrapped = environment._wrap_command(command, str(tmp_path))
            proc = environment._run_bash(wrapped)
            owned.append((proc, release))
            parent = psutil.Process(proc.pid)
            identities.append((parent.pid, parent.create_time()))
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            assert ready.exists(), "owned real child did not initialize"
            child = psutil.Process(int(ready.read_text(encoding="utf-8")))
            identities.append((child.pid, child.create_time()))
            actual = parent.cmdline()
            units = len(subprocess.list2cmdline(actual).encode("utf-16-le")) // 2
            assert units < 30000, actual
            print({"owned_bash_pid": parent.pid, "created": parent.create_time(), "actual_argv_utf16_units": units})
            script = Path(proc._hermes_command_script)
            assert script.read_bytes() == wrapped.encode("utf-8")
        first, second = owned[0][0], owned[1][0]
        first_script, second_script = Path(first._hermes_command_script), Path(second._hermes_command_script)
        assert first_script != second_script
        second_snapshot = Path(second._hermes_snapshot_copy)
        owned[0][1].touch()
        result = environment._wait_for_process(first, timeout=10)
        assert result["returncode"] == 0 and "owned child completed" in result["output"], result
        assert not first_script.exists()
        assert second.poll() is None and second_script.exists() and second_snapshot.exists()
        from tools.environments.base import BaseEnvironment
        with monkeypatch.context() as wait_failure:
            def fail_wait(*args, **kwargs):
                raise RuntimeError("owned injected wait failure")
            wait_failure.setattr(BaseEnvironment, "_wait_for_process", fail_wait)
            with pytest.raises(RuntimeError, match="owned injected wait failure") as caught:
                environment._wait_for_process(second, timeout=5)
            assert caught.value._hermes_process is second
        assert second.poll() is None and second_script.exists() and second_snapshot.exists()
        before = set(Path(environment.get_temp_dir()).iterdir())
        with monkeypatch.context() as failure:
            def fail(*args, **kwargs):
                raise OSError("owned concurrent spawn failure")
            failure.setattr(local.subprocess, "Popen", fail)
            with pytest.raises(OSError, match="owned concurrent spawn failure"):
                environment.execute("true")
        assert set(Path(environment.get_temp_dir()).iterdir()) == before
        assert second.poll() is None and second_script.exists() and second_snapshot.exists()
        owned[1][1].touch()
        result = environment._wait_for_process(second, timeout=10)
        assert result["returncode"] == 0 and "owned child completed" in result["output"], result
        assert not second_script.exists() and not second_snapshot.exists()
        for pid, created in identities:
            assert not psutil.pid_exists(pid) or psutil.Process(pid).create_time() != created
    finally:
        for _, release in owned:
            release.touch()
        for proc, _ in owned:
            if proc.poll() is None:
                environment._kill_process(proc)
            environment._wait_for_process(proc, timeout=5)
        for pid, created in reversed(identities):
            try:
                process = psutil.Process(pid)
                if process.create_time() == created and process.is_running():
                    process.terminate()
                    process.wait(timeout=3)
            except psutil.NoSuchProcess:
                pass


def test_stdin_setup_failure_reaps_child_before_releasing_inputs(environment, monkeypatch):
    import psutil

    grow_exclusions(environment)
    original = local.subprocess.Popen
    owned = []
    before = set(Path(environment.get_temp_dir()).iterdir())

    def observe(*args, **kwargs):
        proc = original(*args, **kwargs)
        if str(args[0][0]).lower().endswith("bash.exe"):
            owned.append(proc)
        return proc

    def fail_stdin(*args, **kwargs):
        raise RuntimeError("owned injected stdin setup failure")

    monkeypatch.setattr(local.subprocess, "Popen", observe)
    monkeypatch.setattr(local, "_pipe_stdin", fail_stdin)
    try:
        with pytest.raises(RuntimeError, match="owned injected stdin setup failure"):
            environment.execute("cat", stdin_data="owned-input\n")
        assert len(owned) == 1
        assert owned[0].poll() is not None
        assert not psutil.pid_exists(owned[0].pid)
        assert set(Path(environment.get_temp_dir()).iterdir()) == before
    finally:
        for proc in owned:
            if proc.poll() is None:
                environment._kill_process(proc)
            environment._wait_for_process(proc, timeout=5)


@pytest.mark.parametrize("stop", ["timeout", "interrupt"])
def test_large_wrapper_stop_reaps_held_native_child(environment, tmp_path, stop):
    import psutil
    from tools.interrupt import set_interrupt

    grow_exclusions(environment)
    ready, release = tmp_path / "stop.pid", tmp_path / "stop.release"
    probe = tmp_path / "stop child.py"
    probe.write_text(
        "import os,pathlib,sys,time\n"
        "ready,release=map(pathlib.Path,sys.argv[1:])\n"
        "ready.write_text(str(os.getpid()),encoding='utf-8')\n"
        "deadline=time.monotonic()+15\n"
        "while not release.exists() and time.monotonic()<deadline: time.sleep(.02)\n",
        encoding="utf-8", newline="\n",
    )
    command = " ".join(shlex.quote(value.replace("\\", "/")) for value in [sys.executable, "-I", str(probe), str(ready), str(release)])
    proc = environment._run_bash(environment._wrap_command(command, str(tmp_path)))
    child = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists(), "owned stop child did not initialize"
        child = psutil.Process(int(ready.read_text(encoding="utf-8")))
        created = child.create_time()
        if stop == "interrupt":
            set_interrupt(True)
        result = environment._wait_for_process(proc, timeout=.1)
        assert result["returncode"] == (124 if stop == "timeout" else 130), result
        assert proc.poll() is not None
        assert not child.is_running(), {"surviving_owned_child_pid": child.pid, "created": created}
        assert not Path(proc._hermes_command_script).exists()
        assert not Path(proc._hermes_snapshot_copy).exists()
    finally:
        set_interrupt(False)
        release.touch()
        if child is not None:
            try:
                child.wait(timeout=3)
            except psutil.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
        if proc.poll() is None:
            environment._kill_process(proc)
        environment._wait_for_process(proc, timeout=5)
    recovered = execute_effect(environment, "printf stopped-then-recovered")
    assert recovered["returncode"] == 0 and recovered["output"] == "stopped-then-recovered", recovered


def test_large_login_initialization_keeps_snapshot_and_cleans_script(environment):
    grow_exclusions(environment)
    environment.init_session()
    assert environment._snapshot_ready
    result = execute_effect(environment, "printf login-ready")
    assert result["returncode"] == 0 and result["output"] == "login-ready", result
    prefix = Path(environment._snapshot_path).name
    assert not list(Path(environment.get_temp_dir()).glob(prefix + ".command.*"))


def test_missing_payload_is_failure_without_command_effect(environment, tmp_path, monkeypatch):
    grow_exclusions(environment)
    original = local.subprocess.Popen
    marker = tmp_path / "missing-must-not-run.txt"

    def remove_owned_payload_then_spawn(*args, **kwargs):
        scripts = list(Path(environment.get_temp_dir()).glob(Path(environment._snapshot_path).name + ".command.*"))
        assert len(scripts) == 1
        scripts[0].unlink()
        return original(*args, **kwargs)

    monkeypatch.setattr(local.subprocess, "Popen", remove_owned_payload_then_spawn)
    result = execute_effect(environment, "printf unexpected > " + shlex.quote(marker.as_posix()))
    assert result["returncode"] == 126, result
    assert not marker.exists()


@pytest.mark.parametrize("units", [4095, 4096, 4097])
def test_complete_quoted_utf16_budget_selects_transport_before_execution(environment, units):
    command = "printf budget-ok; # 日本語 😀 "
    args = [local._find_bash(), "-c", command]
    initial = len(subprocess.list2cmdline(args).encode("utf-16-le")) // 2
    command += "x" * (units - initial)
    args[-1] = command
    assert len(subprocess.list2cmdline(args).encode("utf-16-le")) // 2 == units
    proc = environment._spawn_bash(command)
    script = getattr(proc, "_hermes_command_script", None)
    try:
        assert bool(script) == (units >= 4096)
        if script:
            assert Path(script).read_bytes() == command.encode("utf-8")
        result = environment._wait_for_process(proc, timeout=5)
        assert result["returncode"] == 0 and result["output"] == "budget-ok", result
        if script:
            assert not Path(script).exists()
    finally:
        if proc.poll() is None:
            environment._kill_process(proc)
        environment._wait_for_process(proc, timeout=5)


@pytest.mark.parametrize("authority", ["capture_unavailable", "saved_missing", "saved_mismatch"])
def test_missing_or_changed_saved_identity_never_authorizes_pid_tree_kill(environment, monkeypatch, authority):
    from gateway import status

    captures = []
    actual_capture = status.get_process_start_time

    def capture(pid):
        captures.append(pid)
        if authority == "capture_unavailable":
            raise OSError("owned injected fingerprint unavailability")
        return actual_capture(pid)

    monkeypatch.setattr(status, "get_process_start_time", capture)
    # Only shell builtins run, so handle-only cancellation has no child to leave.
    proc = environment._spawn_bash("# " + "x" * 5000 + "\nwhile :; do :; done")
    script = Path(proc._hermes_command_script)
    calls = []
    original_run = status.subprocess.run

    def forbid_tree_kill(args, *positional, **kwargs):
        if args and args[0] == "taskkill":
            calls.append(args)
            raise AssertionError("missing/mismatched identity reached PID tree termination")
        return original_run(args, *positional, **kwargs)

    monkeypatch.setattr(status.subprocess, "run", forbid_tree_kill)
    try:
        assert proc.poll() is None and script.exists()
        assert captures == [proc.pid]
        if authority == "capture_unavailable":
            assert proc._hermes_start_time is None
        elif authority == "saved_missing":
            del proc._hermes_start_time
        else:
            assert proc._hermes_start_time is not None
            proc._hermes_start_time += 10000
        environment._kill_process(proc)
        assert proc.poll() is not None
        assert captures == [proc.pid], "cancellation acquired fresh PID authority"
        assert not calls
        environment._wait_for_process(proc, timeout=5)
        assert not script.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        environment._wait_for_process(proc, timeout=5)


def test_stdin_setup_and_stop_failure_retains_live_inputs_until_explicit_recovery(environment, tmp_path, monkeypatch):
    grow_exclusions(environment)
    ready, release = tmp_path / "stdin-failure.ready", tmp_path / "stdin-failure.release"
    command = (
        "printf ready > " + environment._quote_shell_path(str(ready)) +
        "; while [ ! -f " + environment._quote_shell_path(str(release)) +
        " ]; do :; done; printf recovery-tail"
    )
    original_error = RuntimeError("owned injected stdin setup failure with live stop failure")
    proc = None
    try:
        with monkeypatch.context() as failure:
            def fail_stdin(*args, **kwargs):
                raise original_error

            def fail_stop(*args, **kwargs):
                raise OSError("owned injected stop failure")

            failure.setattr(local, "_pipe_stdin", fail_stdin)
            failure.setattr(environment, "_kill_process", fail_stop)
            with pytest.raises(RuntimeError) as caught:
                environment.execute(command, stdin_data="owned unused input\n")
            assert caught.value is original_error
            proc = caught.value._hermes_process
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists() and proc.poll() is None
        script, snapshot = Path(proc._hermes_command_script), Path(proc._hermes_snapshot_copy)
        assert script.exists() and snapshot.exists()
        assert proc.stdin is not None and not proc.stdin.closed
        # The explicit recovery owner can stop the original process safely.
        environment._kill_process(proc)
        result = environment._wait_for_process(proc, timeout=5)
        assert proc.poll() is not None and result["returncode"] != 0
        assert not script.exists() and not snapshot.exists()
        assert proc.stdin.closed and proc.stdout.closed
        recovered = execute_effect(environment, "printf stdin-stop-recovered")
        assert recovered["returncode"] == 0 and recovered["output"] == "stdin-stop-recovered", recovered
    finally:
        release.touch()
        if proc is not None:
            if proc.poll() is None:
                environment._kill_process(proc)
            environment._wait_for_process(proc, timeout=5)
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    stream.close()


@pytest.mark.parametrize("initial_stop_fails", [False, True])
def test_actual_stdin_writer_start_failure_has_recoverable_partial_setup(environment, monkeypatch, initial_stop_fails):
    from tools.environments import base

    grow_exclusions(environment)
    original_start = base.threading.Thread.start
    writer_threads = []
    original_error = RuntimeError("owned injected writer Thread.start failure")
    proc = None

    def fail_only_stdin_writer(thread):
        if getattr(thread._target, "__name__", None) == "_write":
            writer_threads.append(thread)
            raise original_error
        return original_start(thread)

    try:
        with monkeypatch.context() as failure:
            failure.setattr(base.threading.Thread, "start", fail_only_stdin_writer)
            if initial_stop_fails:
                def fail_stop(*args, **kwargs):
                    raise OSError("owned injected initial stop failure")
                failure.setattr(environment, "_kill_process", fail_stop)
            with pytest.raises(RuntimeError) as caught:
                environment.execute("cat", stdin_data="owned writer input\n")
            assert caught.value is original_error
            proc = caught.value._hermes_process
        assert len(writer_threads) == 1 and writer_threads[0].ident is None
        if initial_stop_fails:
            assert proc.poll() is None
            assert Path(proc._hermes_command_script).exists()
            assert Path(proc._hermes_snapshot_copy).exists()
            environment._kill_process(proc)
        assert proc.poll() is not None
        try:
            result = environment._wait_for_process(proc, timeout=5)
        except RuntimeError as exc:
            assert False, f"Explicit recovery tried to join an unstarted stdin writer: {exc}"
        assert result["returncode"] != 0 and proc.stdin.closed and proc.stdout.closed
        assert not Path(proc._hermes_command_script).exists()
        snapshot = getattr(proc, "_hermes_snapshot_copy", None)
        assert snapshot is None or not Path(snapshot).exists()
        result = execute_effect(environment, "printf writer-start-recovered")
        assert result["returncode"] == 0 and result["output"] == "writer-start-recovered", result
    finally:
        if proc is not None:
            if proc.poll() is None:
                environment._kill_process(proc)
            proc.wait(timeout=5)
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    stream.close()


def test_writer_started_before_setup_error_keeps_its_join_owner(environment, monkeypatch):
    from tools.environments import base

    original_start = base.threading.Thread.start
    original_error = RuntimeError("owned injected error after successful writer start")
    writers = []
    proc = None

    # Inspect the target before start: a completed Thread discards _target.
    def observed_start(thread):
        is_writer = getattr(thread._target, "__name__", None) == "_write"
        result = original_start(thread)
        if is_writer:
            writers.append(thread)
            raise original_error
        return result

    try:
        with monkeypatch.context() as failure:
            failure.setattr(base.threading.Thread, "start", observed_start)
            with pytest.raises(RuntimeError) as caught:
                environment.execute("cat", stdin_data="owned started writer\n")
            assert caught.value is original_error
            proc = caught.value._hermes_process
        assert len(writers) == 1 and writers[0].ident is not None
        assert getattr(proc, "_hermes_stdin_thread", None) is writers[0]
        result = environment._wait_for_process(proc, timeout=5)
        assert proc.poll() is not None and not writers[0].is_alive()
        assert proc.stdin.closed and proc.stdout.closed
        assert "returncode" in result
    finally:
        if proc is not None:
            if proc.poll() is None:
                environment._kill_process(proc)
            proc.wait(timeout=5)
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    stream.close()
