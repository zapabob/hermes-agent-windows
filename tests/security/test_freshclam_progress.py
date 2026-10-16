"""Exercise updater output limits with a real, harmless child process."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from downstream.security import updates
from downstream.security.bounded_process import run_bounded
from downstream.security.store import SecurityStore


@pytest.mark.parametrize("mode", ["success", "failure", "overflow", "invalid"])
def test_updater_suppresses_progress_and_preserves_failure_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    store = SecurityStore(tmp_path / "security")
    updater = updates.DefinitionUpdater(store)
    current = updater.root / "current"
    current.mkdir()
    old = b"previous definition" * 40
    (current / "daily.cvd").write_bytes(old)
    child = tmp_path / "inert_freshclam.py"
    child.write_text(
        "import pathlib, sys\n"
        "mode = sys.argv[1]\n"
        "root = pathlib.Path(next(a.split('=', 1)[1] for a in sys.argv if a.startswith('--datadir=')))\n"
        "(root / 'daily.cvd').write_bytes(b'x' * (1 if mode == 'invalid' else 512))\n"
        "if '--quiet' not in sys.argv or mode == 'overflow':\n"
        "    sys.stdout.write(('Time: 0.1s [====>] 275KiB/275KiB\\r') * 2000)\n"
        "if mode == 'failure':\n"
        "    sys.stderr.write('ERROR: inert update failure')\n"
        "    sys.exit(17)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(updates.shutil, "which", lambda name: "inert-freshclam" if name == "freshclam" else None)
    calls = []

    def native_child(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return run_bounded([sys.executable, "-I", str(child), mode, *arguments[1:]], **kwargs)

    monkeypatch.setattr(updates, "run_bounded", native_child)
    result = updater.update_clamav()
    feed = store.status_rows("feed_state")[0]
    assert calls[0][1]["max_output_bytes_per_stream"] == updates.MAX_UPDATE_OUTPUT_BYTES
    if mode == "success":
        assert result["ok"] is True
        assert feed["status"] == "ok"
        assert (updater.root / "previous" / "daily.cvd").read_bytes() == old
        assert (current / "daily.cvd").read_bytes() == b"x" * 512
    else:
        assert result["ok"] is False
        assert feed["status"] == "error"
        assert (current / "daily.cvd").read_bytes() == old
        if mode == "failure":
            assert result["exit_code"] == 17
            assert "inert update failure" in result["error"]
        elif mode == "overflow":
            assert json.loads(feed["details_json"])["output_truncated"] is True
        else:
            assert result["state"] == "validation_failed"
