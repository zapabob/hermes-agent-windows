"""Windows native spawn contracts using only test-owned homes and probes."""

import json
import os
import shlex
import subprocess
import sys
import time
from contextlib import nullcontext

import pytest

from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from tools.environments import local

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="native Windows spawn proof")
KEYS = ("CUSTOM_PROFILE_SECRET", "OPENAI_API_KEY", "TELEGRAM_WEBHOOK_SECRET", "BOUNDARY_BENIGN", "HERMES_HOME")


@pytest.fixture(autouse=True)
def isolated_launch_identity(monkeypatch):
    from hermes_cli import env_loader
    monkeypatch.setattr(env_loader, "_LAUNCH_PROFILE_HOME", None, raising=False)


@pytest.mark.parametrize("surface", ["terminal", "background", "pty", "cron", "cli", "subagent"])
def test_native_spawn_honors_served_profile_and_secret_minimization(tmp_path, monkeypatch, surface):
    launch, served = tmp_path / "launch profile", tmp_path / "served profile"
    launch.mkdir()
    (served / "home").mkdir(parents=True)
    scripts = served / "scripts"
    scripts.mkdir()
    output = served / "observed.json"
    (launch / ".env").write_text("CUSTOM_PROFILE_SECRET=TEST_ONLY_SECRET_DO_NOT_USE\n", encoding="utf-8")
    (served / ".env").write_text("BOUNDARY_BENIGN=served-value\n", encoding="utf-8")
    script = scripts / "probe.py"
    script.write_text(
        "import json,os,pathlib,sys\npathlib.Path(" + repr(str(output)) + ").write_text("
        "json.dumps({k:os.environ.get(k) for k in " + repr(KEYS) + "}),encoding='utf-8')\n"
        "sys.stdout.write('PROBE_DONE\\n')\n", encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(launch))
    for key in KEYS[:3]:
        monkeypatch.setenv(key, "TEST_ONLY_SECRET_DO_NOT_USE")
    monkeypatch.setenv("BOUNDARY_BENIGN", "launch-value")
    monkeypatch.setenv("HOME", str(served / "home"))
    monkeypatch.setenv("USERPROFILE", str(served / "home"))
    monkeypatch.setenv("HERMES_REAL_HOME", str(served / "home"))
    monkeypatch.setenv("TERMINAL_HOME_MODE", "profile")
    monkeypatch.setattr(local, "_resolve_shell_init_files", lambda: [])
    command = shlex.quote(sys.executable.replace("\\", "/")) + " " + shlex.quote(script.as_posix())
    token = set_hermes_home_override(served)
    registry = None
    terminal = None
    try:
        if surface == "terminal":
            terminal = local.LocalEnvironment(cwd=str(served), timeout=20)
            result = terminal.execute(command)
            assert result["returncode"] == 0, result
        elif surface in {"background", "pty"}:
            from tools.process_registry import ProcessRegistry
            registry = ProcessRegistry()
            session = registry.spawn_local(command, cwd=str(served), use_pty=surface == "pty")
            if surface == "pty":
                assert getattr(session, "_pty", None) is not None, "pipe fallback is not PTY proof"
            deadline = time.monotonic() + 25
            while not session.exited and time.monotonic() < deadline:
                time.sleep(0.05)
            assert session.exited, "test-owned native child did not finish"
            assert session.exit_code == 0
        elif surface == "cron":
            from cron.scheduler import _run_job_script
            ok, result = _run_job_script(str(script), workdir=str(served))
            assert ok, result
        elif surface == "subagent":
            from agent.delegation_context import delegated_child_context, delegated_child_subprocess_env
            with delegated_child_context("test-only-child"):
                env = delegated_child_subprocess_env()
            subprocess.run([sys.executable, "-I", str(script)], env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=True)
        else:
            subprocess.run([sys.executable, "-I", str(script)], env=local.hermes_subprocess_env(), stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=True)
        observed = json.loads(output.read_text(encoding="utf-8"))
        assert observed["BOUNDARY_BENIGN"] == "served-value"
        assert observed["HERMES_HOME"] == str(served)
        assert all(observed[key] is None for key in KEYS[:3])
    finally:
        if terminal is not None:
            terminal.cleanup()
        if registry is not None:
            for session_id in list(registry._running):
                registry.kill_process(session_id)
        reset_hermes_home_override(token)


@pytest.mark.parametrize("readonly", [False, True])
@pytest.mark.parametrize("handoff", ["new-secret-declaration", "absent-target", "benign-target"])
def test_reused_terminal_snapshot_cannot_restore_profile_secrets(tmp_path, monkeypatch, handoff, readonly):
    launch, target = tmp_path / "launch", tmp_path / "target"
    launch.mkdir()
    target.mkdir()
    (launch / "home").mkdir()
    (target / "home").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv("HOME", str(launch / "home"))
    monkeypatch.setenv("USERPROFILE", str(launch / "home"))
    monkeypatch.setenv("TERMINAL_HOME_MODE", "profile")
    monkeypatch.setattr(local, "_resolve_shell_init_files", lambda: [])
    key = "CUSTOM_SNAPSHOT_VALUE"
    output = tmp_path / "observed.json"
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json,os,pathlib;pathlib.Path(" + repr(str(output)) + ").write_text("
        "json.dumps({k:os.environ.get(k) for k in " + repr((key, "ORDINARY_EXPORT")) + "}),encoding='utf-8')",
        encoding="utf-8",
    )
    command = shlex.quote(sys.executable.replace("\\", "/")) + " " + shlex.quote(probe.as_posix())
    environment = local.LocalEnvironment(cwd=str(launch), timeout=20)
    token = None
    try:
        readonly_command = f"; readonly {key}" if readonly else ""
        seeded = environment.execute(f"export {key}=TEST_ONLY_SECRET_DO_NOT_USE{readonly_command}; export ORDINARY_EXPORT=kept")
        assert seeded["returncode"] == 0, seeded
        assert environment.execute(command)["returncode"] == 0
        assert json.loads(output.read_text(encoding="utf-8"))[key] == "TEST_ONLY_SECRET_DO_NOT_USE"
        directory = launch / "plugins" / "platforms" / "snapshot-test"
        directory.mkdir(parents=True)
        (directory / "plugin.yaml").write_text(
            f"kind: platform\nrequires_env:\n  - name: {key}\n    password: true\n",
            encoding="utf-8",
        )
        if handoff != "new-secret-declaration":
            if handoff == "benign-target":
                (target / ".env").write_text(f"{key}=served-benign\n", encoding="utf-8")
            token = set_hermes_home_override(target)
        if readonly:
            # Refuse before source: a protected readonly binding cannot be
            # unset or replaced by the served profile's benign value.
            output.unlink()
            with pytest.raises(RuntimeError, match="readonly.*snapshot"):
                environment.execute(command)
            assert not output.exists()
            return
        result = environment.execute(command)
        assert result["returncode"] == 0, result
        observed = json.loads(output.read_text(encoding="utf-8"))
        assert observed[key] == ("served-benign" if handoff == "benign-target" else None)
        assert observed["ORDINARY_EXPORT"] == "kept"
    finally:
        if token is not None:
            reset_hermes_home_override(token)
        environment.cleanup()


def test_many_accumulated_snapshot_names_refuse_before_windows_spawn(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(local, "_resolve_shell_init_files", lambda: [])
    environment = local.LocalEnvironment(cwd=str(tmp_path), timeout=20)
    spawned = []
    try:
        for batch in range(3):
            for index in range(20):
                environment.env[f"GATEWAY_RELAY_{batch}_{index}_" + "X" * 180 + "_SECRET"] = "TEST_ONLY_SECRET_DO_NOT_USE"
            wrapped = environment._wrap_command("true", str(tmp_path))
        from types import SimpleNamespace
        def record_spawn(*args, **kwargs):
            spawned.append(args)
            return SimpleNamespace()
        monkeypatch.setattr(local.subprocess, "Popen", record_spawn)
        with pytest.raises(RuntimeError, match="(?i)(command.*limit|command.*length)"):
            environment._run_bash(wrapped)
        assert not spawned
    finally:
        environment.cleanup()


@pytest.mark.parametrize("runner", ["tts", "stt"])
@pytest.mark.parametrize("delegated", [False, True])
@pytest.mark.parametrize("routed", [False, True])
def test_native_voice_command_keeps_only_approved_profile_key(tmp_path, monkeypatch, runner, delegated, routed):
    from agent.delegation_context import delegated_child_context
    from tools.tts_tool import _run_command_tts
    from tools.transcription_tools import _run_command_stt
    launch, target = tmp_path / "launch", tmp_path / "served"
    launch.mkdir()
    target.mkdir()
    (target / ".env").write_text("OPENAI_API_KEY=TEST_ONLY_SERVED\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv("OPENAI_API_KEY", "TEST_ONLY_LAUNCH")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_ONLY_ADAPTER")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "TEST_ONLY_UNREQUESTED")
    probe = tmp_path / "voice probe.py"
    probe.write_text("import json,os,sys;sys.stdout.write(json.dumps({k:os.environ.get(k) for k in ['OPENAI_API_KEY','TELEGRAM_BOT_TOKEN','ANTHROPIC_API_KEY']}))", encoding="utf-8")
    command = subprocess.list2cmdline([sys.executable, "-I", str(probe)])
    home_token = set_hermes_home_override(target) if routed else None
    try:
        context = delegated_child_context("test-only-voice") if delegated else nullcontext()
        with context:
            result = (_run_command_tts if runner == "tts" else _run_command_stt)(
                command, timeout=20, env_passthrough=["OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN"],
            )
        assert result.returncode == 0, result
        observed = json.loads(result.stdout)
        assert observed["OPENAI_API_KEY"] == ("TEST_ONLY_SERVED" if routed else "TEST_ONLY_LAUNCH")
        assert observed["TELEGRAM_BOT_TOKEN"] is None
        assert observed["ANTHROPIC_API_KEY"] is None
    finally:
        if home_token is not None:
            reset_hermes_home_override(home_token)


def test_snapshot_atomic_replacement_after_validation_cannot_restore_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(local, "_resolve_shell_init_files", lambda: [])
    environment = local.LocalEnvironment(cwd=str(tmp_path), timeout=20)
    output, probe = tmp_path / "observed.json", tmp_path / "probe.py"
    probe.write_text("import os,json,pathlib;pathlib.Path(" + repr(str(output)) + ").write_text(json.dumps({k:os.environ.get(k) for k in ['TELEGRAM_BOT_TOKEN','ORDINARY_EXPORT']}),encoding='utf-8')", encoding="utf-8")
    original_run = environment._run_bash
    try:
        assert environment.execute("export ORDINARY_EXPORT=$'first\\nsecond'")["returncode"] == 0
        def concurrent_snapshot_publication(script, **kwargs):
            from pathlib import Path
            replacement = Path(environment._snapshot_path + ".test-replacement")
            replacement.write_text('declare -rx TELEGRAM_BOT_TOKEN="TEST_ONLY_RACING_SECRET"\n', encoding="utf-8")
            replacement.replace(environment._snapshot_path)
            return original_run(script, **kwargs)
        monkeypatch.setattr(environment, "_run_bash", concurrent_snapshot_publication)
        result = environment.execute(shlex.quote(sys.executable.replace("\\", "/")) + " " + shlex.quote(probe.as_posix()))
        assert result["returncode"] == 0, result
        observed = json.loads(output.read_text(encoding="utf-8"))
        assert observed["TELEGRAM_BOT_TOKEN"] is None
        assert observed["ORDINARY_EXPORT"] == "first\nsecond"
    finally:
        environment.cleanup()
    from pathlib import Path
    assert not list(Path(environment._snapshot_path).parent.glob(Path(environment._snapshot_path).name + ".validated.*"))


@pytest.mark.parametrize("failure", ["spawn", "timeout"])
def test_validated_snapshot_copy_is_removed_on_failed_execution(tmp_path, monkeypatch, failure):
    from pathlib import Path
    import psutil
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(local, "_resolve_shell_init_files", lambda: [])
    environment = local.LocalEnvironment(cwd=str(tmp_path), timeout=20)
    owned_processes = []
    try:
        if failure == "spawn":
            def failed_spawn(*args, **kwargs):
                raise OSError("test-only spawn refusal")
            monkeypatch.setattr(local.subprocess, "Popen", failed_spawn)
            with pytest.raises(OSError, match="test-only"):
                environment.execute("true")
        else:
            pid_file = tmp_path / "timeout-child.pid"
            probe = tmp_path / "timeout child.py"
            probe.write_text(
                "import os,pathlib,time\npathlib.Path(" + repr(str(pid_file)) +
                ").write_text(str(os.getpid()),encoding='utf-8')\ntime.sleep(30)\n",
                encoding="utf-8",
            )
            original_wait = environment._wait_for_process
            def record_owned_tree(proc, *args, **kwargs):
                parent = psutil.Process(proc.pid)
                owned_processes.append((parent.pid, parent.create_time()))
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    # Record before every possible setup refusal, not only
                    # after the probe has published its PID file.
                    owned_processes.extend((item.pid, item.create_time()) for item in parent.children(recursive=True))
                    if pid_file.exists():
                        break
                    time.sleep(0.02)
                assert pid_file.exists(), "owned timeout probe did not initialize"
                child = psutil.Process(int(pid_file.read_text(encoding="utf-8")))
                owned_processes.extend((item.pid, item.create_time()) for item in [parent, *parent.children(recursive=True), child])
                return original_wait(proc, *args, **kwargs)
            monkeypatch.setattr(environment, "_wait_for_process", record_owned_tree)
            command = " ".join(shlex.quote(value.replace("\\", "/")) for value in [sys.executable, "-I", str(probe)])
            result = environment.execute(command, timeout=1)
            assert result["returncode"] == 124 and "timed out" in result["output"], result
        assert not list(Path(environment._snapshot_path).parent.glob(Path(environment._snapshot_path).name + ".validated.*"))
    finally:
        # Base's existing Windows timeout can leave MSYS descendants alive;
        # this fixture records its probe's Windows PID even if MSYS reparents it.
        for pid, started in reversed(owned_processes):
            try:
                child = psutil.Process(pid)
                if child.create_time() != started:
                    continue
                child.terminate()
                try:
                    child.wait(timeout=3)
                except psutil.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
            except psutil.NoSuchProcess:
                pass
        environment.cleanup()


@pytest.mark.parametrize("readonly", [False, True])
def test_late_declaration_between_wrap_and_spawn_refuses_stale_wrapper(tmp_path, monkeypatch, readonly):
    from agent import terminal_env_registry as registry
    from agent.terminal_env_provider import TerminalEnvironmentProvider
    class LateProvider(TerminalEnvironmentProvider):
        name = "test-only-late-snapshot-provider"
        @property
        def strip_env_keys(self):
            return frozenset({"CUSTOM_LOGIN"})
        def is_available(self):
            return True
        def create_environment(self, **kwargs):
            raise AssertionError("declaration must not start provider")
    provider = LateProvider()
    previous = registry.snapshot_registration(provider.name)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(local, "_resolve_shell_init_files", lambda: [])
    environment = local.LocalEnvironment(cwd=str(tmp_path), timeout=20)
    output = tmp_path / "must-not-run.txt"
    original_run = environment._run_bash
    try:
        suffix = "; readonly CUSTOM_LOGIN" if readonly else ""
        assert environment.execute("export CUSTOM_LOGIN=TEST_ONLY_SECRET" + suffix)["returncode"] == 0
        def late_registration(script, **kwargs):
            registry.register_provider(provider)
            return original_run(script, **kwargs)
        monkeypatch.setattr(environment, "_run_bash", late_registration)
        with pytest.raises(RuntimeError, match="(?i)(declaration|readonly|authority)"):
            environment.execute("printf executed > " + shlex.quote(output.as_posix()))
        assert not output.exists()
    finally:
        registry.restore_registration(provider.name, provider, previous)
        environment.cleanup()


def test_parallel_benign_scope_history_does_not_refuse_native_commands(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(local, "_resolve_shell_init_files", lambda: [])
    environment = local.LocalEnvironment(cwd=str(tmp_path), timeout=20, env={
        "CUSTOM_FLAG_A": "benign-A", "CUSTOM_FLAG_B": "benign-B",
    })
    wrapped_a, wrapped_b = Event(), Event()
    def run(name):
        scope = set_secret_scope({"CUSTOM_FLAG_" + name: "benign-" + name})
        try:
            if name == "B":
                assert wrapped_a.wait(10)
            script = environment._wrap_command('printf "%s" "$CUSTOM_FLAG_' + name + '"', str(tmp_path))
            if name == "A":
                wrapped_a.set()
                assert wrapped_b.wait(10)
            else:
                wrapped_b.set()
            proc = environment._run_bash(script)
            return environment._wait_for_process(proc, timeout=20)
        finally:
            reset_secret_scope(scope)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a, future_b = executor.submit(run, "A"), executor.submit(run, "B")
            results = [future_a.result(timeout=30), future_b.result(timeout=30)]
        assert all(result["returncode"] == 0 for result in results), results
        assert "benign-A" in results[0]["output"] and "benign-B" in results[1]["output"]
    finally:
        environment.cleanup()


def test_readonly_prior_scope_history_refuses_foreign_snapshot(tmp_path, monkeypatch):
    from pathlib import Path
    from agent import secret_scope
    from tools import env_passthrough
    launch, served_a, served_b = (tmp_path / name for name in ("launch", "served-A", "served-B"))
    for home in (launch, served_a, served_b):
        home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setattr(local, "_resolve_shell_init_files", lambda: [])
    environment = local.LocalEnvironment(cwd=str(launch), timeout=20)
    monkeypatch.setattr(secret_scope, "_MULTIPLEX_ACTIVE", True)
    home_token = set_hermes_home_override(served_a)
    scope_token = secret_scope.set_secret_scope({"SERVICE_TOKEN": "TEST_ONLY_SCOPE_A"})
    try:
        env_passthrough.register_env_passthrough(["SERVICE_TOKEN"])
        assert environment.execute("readonly SERVICE_TOKEN")["returncode"] == 0
        assert "declare -rx SERVICE_TOKEN=" in Path(environment._snapshot_path).read_text(encoding="utf-8")
        secret_scope.reset_secret_scope(scope_token)
        reset_hermes_home_override(home_token)
        home_token = set_hermes_home_override(served_b)
        scope_token = secret_scope.set_secret_scope({})
        env_passthrough.clear_env_passthrough()
        assert "SERVICE_TOKEN" not in local._make_run_env(environment.env)
        marker = tmp_path / "foreign-value.txt"
        command = "printf '%s' \"$SERVICE_TOKEN\" > " + shlex.quote(marker.as_posix())
        with pytest.raises(RuntimeError, match="readonly.*snapshot"):
            environment.execute(command)
            assert marker.read_text(encoding="utf-8") == "TEST_ONLY_SCOPE_A"
        assert not marker.exists()
    finally:
        secret_scope.reset_secret_scope(scope_token)
        reset_hermes_home_override(home_token)
        env_passthrough.clear_env_passthrough()
        environment.cleanup()
