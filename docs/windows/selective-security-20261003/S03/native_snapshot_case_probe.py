"""Supplementary native proof: mixed-case shell names and served benign value."""
import json
import os
from pathlib import Path
import sys
import tempfile

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
assert os.name == "nt"
safe = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT") if name in os.environ}
with tempfile.TemporaryDirectory(dir=root / "tmp/test-temp", prefix="S03-case-") as directory:
    work = Path(directory)
    launch, target = work / "launch", work / "served"
    launch.mkdir()
    target.mkdir()
    os.environ.clear()
    os.environ.update(safe, HERMES_HOME=str(launch), HOME=str(launch), USERPROFILE=str(launch), TERMINAL_HOME_MODE="profile")
    from tools.environments import local
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli import env_loader
    env_loader._LAUNCH_PROFILE_HOME = None
    local._resolve_shell_init_files = lambda: []
    environment = local.LocalEnvironment(cwd=str(launch), timeout=20)
    token = None
    try:
        result = environment.execute("export custom_snapshot_value=TEST_ONLY_SECRET_DO_NOT_USE; export ORDINARY_EXPORT=kept")
        assert result["returncode"] == 0
        (launch / ".env").write_text("CUSTOM_SNAPSHOT_VALUE=TEST_ONLY_SECRET_DO_NOT_USE\n", encoding="utf-8")
        (target / ".env").write_text("CUSTOM_SNAPSHOT_VALUE=served-benign\n", encoding="utf-8")
        token = set_hermes_home_override(target)
        result = environment.execute("printf '%s\\n' \"${custom_snapshot_value-ABSENT}\" \"${CUSTOM_SNAPSHOT_VALUE-ABSENT}\" \"$ORDINARY_EXPORT\"")
        assert result["returncode"] == 0, result
        assert result["output"].strip().splitlines() == ["ABSENT", "served-benign", "kept"], result
    finally:
        if token is not None:
            reset_hermes_home_override(token)
        environment.cleanup()
    assert not Path(environment._snapshot_path).exists()
    assert not Path(environment._cwd_file).exists()
sys.stdout.write(json.dumps({"os": "nt", "mixed_case_foreign_secret_absent": True, "served_benign_present": True,
                           "ordinary_export_preserved": True, "snapshot_removed": True, "test_temp_removed": True}) + "\n")
