import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import psutil
import pytest

from tui_gateway.compute_host import ComputeHost, HostSession


def _stdout_queue(proc: subprocess.Popen) -> queue.Queue[dict]:
    out: queue.Queue[dict] = queue.Queue()
    assert proc.stdout is not None

    def drain() -> None:
        for line in proc.stdout or []:
            out.put(json.loads(line))

    threading.Thread(target=drain, daemon=True).start()
    return out


def _read_json_line(out: queue.Queue[dict], timeout: float = 2.0) -> dict:
    try:
        return out.get(timeout=timeout)
    except queue.Empty as exc:
        raise AssertionError("timed out waiting for compute host JSON") from exc


def _owned_host_child(proc: subprocess.Popen, host_pid: int):
    """Return the reported host only when this test's launcher owns it."""
    if host_pid == proc.pid:
        return None
    assert os.name == "nt", "only the Windows venv launcher may report a child PID"
    launcher = psutil.Process(proc.pid)
    child = next(
        (candidate for candidate in launcher.children(recursive=True)
         if candidate.pid == host_pid),
        None,
    )
    assert child is not None, "reported compute host is not owned by this test launcher"
    parent = child.parent()
    assert parent is not None and parent.pid == proc.pid
    return child


def _terminate_owned_child(child, pid: int, created_at: float) -> None:
    """Stop only a child previously verified under this test's launcher."""
    try:
        if child.pid != pid or child.create_time() != created_at:
            return
        try:
            child.wait(timeout=2)
        except psutil.TimeoutExpired:
            if child.create_time() == created_at:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except psutil.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
    except psutil.NoSuchProcess:
        pass


def test_compute_host_line_json_seed_turn_interrupt():
    repo = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tui_gateway.compute_host"],
        cwd=str(repo),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None
    out = _stdout_queue(proc)
    owned_host = None
    owned_host_pid = None
    owned_host_created_at = None
    try:
        hello = _read_json_line(out)
        assert hello["type"] == "hello"
        host_pid = int(hello["host_pid"])
        owned_host = _owned_host_child(proc, host_pid)
        if owned_host is not None:
            owned_host_pid = owned_host.pid
            owned_host_created_at = owned_host.create_time()

        proc.stdin.write(json.dumps({"type": "session.seed", "sid": "s1", "request_id": "seed"}) + "\n")
        proc.stdin.flush()
        assert _read_json_line(out)["type"] == "session.seeded"

        proc.stdin.write(
            json.dumps(
                {
                    "type": "turn.start",
                    "sid": "s1",
                    "request_id": "turn",
                    "prompt": "hello",
                    "delta_count": 3,
                    "delay_s": 0,
                }
            )
            + "\n"
        )
        proc.stdin.flush()

        seen = []
        while True:
            frame = _read_json_line(out)
            seen.append(frame["type"])
            if frame["type"] == "turn.end":
                assert frame["history_version"] == 1
                assert frame["message_count"] == 2
                break
        assert seen.count("delta") == 3

        proc.stdin.write(json.dumps({"type": "shutdown", "request_id": "stop"}) + "\n")
        proc.stdin.flush()
        assert _read_json_line(out)["type"] == "shutdown.ack"
        proc.wait(timeout=2)
    finally:
        # Closing stdin lets a started compute host exit through its normal
        # EOF shutdown path when an assertion fails before the explicit frame.
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
        if owned_host is not None:
            _terminate_owned_child(
                owned_host, owned_host_pid, owned_host_created_at
            )
        if proc.poll() is None:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)


@pytest.mark.parametrize("kind", ["legacy", "hard-only", "dynamic-getattr"])
def test_compute_host_interrupt_uses_explicit_stop_compatibility(kind):
    calls = []

    class _Legacy:
        def interrupt(self):
            calls.append("legacy")

    class _HardOnly:
        def hard_interrupt(self):
            calls.append("hard")

    class _Dynamic:
        def interrupt(self):
            calls.append("legacy")

        def __getattr__(self, name):
            if name == "hard_interrupt":
                return lambda: calls.append("fabricated-hard")
            raise AttributeError(name)

    agent = {
        "legacy": _Legacy(),
        "hard-only": _HardOnly(),
        "dynamic-getattr": _Dynamic(),
    }[kind]
    host = ComputeHost(heartbeat_secs=0)
    host._sessions["s1"] = HostSession(sid="s1", agent=agent)
    emitted = []
    host.emit = emitted.append
    try:
        host._handle_interrupt({"sid": "s1", "request_id": "stop"})
    finally:
        host.close()

    assert calls == ["hard" if kind == "hard-only" else "legacy"]
    assert emitted[-1]["applied"] is True
