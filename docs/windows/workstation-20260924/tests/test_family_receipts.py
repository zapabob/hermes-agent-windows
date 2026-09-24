from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
from types import ModuleType

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "family_receipts.py"
receipts: ModuleType | None = None
SCOPE = ["src/input.py"]
IDENTITY = {
    "campaign": "campaign-2026-09-25",
    "family": "F00",
    "packet": "LM01",
    "rv": "RV02",
}


def subject() -> ModuleType:
    global receipts
    if receipts is None:
        spec = importlib.util.spec_from_file_location("workstation_family_receipts", MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        receipts = module
    return receipts


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    source = repo / "src" / "input.py"
    source.parent.mkdir()
    source.write_bytes(b"value = 1\n")
    git(repo, "add", "src/input.py")
    git(repo, "commit", "--quiet", "-m", "initial source")
    return repo


def capture_receipt(repo: Path, module: ModuleType):
    binding = module.capture_source_binding(repo, SCOPE)
    receipt = module.create_family_receipt(binding, **IDENTITY)
    return binding, receipt


def validate(module: ModuleType, receipt: dict, scope: list[str], binding: dict) -> dict:
    return module.validate_family_receipt(
        receipt,
        **IDENTITY,
        expected_scope=scope,
        current_binding=binding,
    )


def test_receipt_reuse_rejects_head_movement(tmp_path: Path) -> None:
    module = subject()
    repo = make_repo(tmp_path)
    old_binding, receipt = capture_receipt(repo, module)
    source_before = (repo / "src" / "input.py").read_bytes()

    evidence = repo / "evidence" / "out-of-scope.txt"
    evidence.parent.mkdir()
    evidence.write_bytes(b"new evidence outside the fixed source scope\n")
    git(repo, "add", "evidence/out-of-scope.txt")
    git(repo, "commit", "--quiet", "-m", "move repository head outside scope")

    current_binding = module.capture_source_binding(repo, SCOPE)
    assert git(repo, "rev-parse", "HEAD") != old_binding["head"]
    assert (repo / "src" / "input.py").read_bytes() == source_before
    result = validate(module, receipt, SCOPE, current_binding)

    assert result["valid"] is False
    assert result["code"] == "HEAD_MISMATCH"


def test_receipt_reuse_rejects_dirty_source_movement(tmp_path: Path) -> None:
    module = subject()
    repo = make_repo(tmp_path)
    old_binding, receipt = capture_receipt(repo, module)

    (repo / "src" / "input.py").write_bytes(b"value = 2\n")
    current_binding = module.capture_source_binding(repo, SCOPE)
    assert current_binding["head"] == old_binding["head"]
    assert current_binding["source_digest"] != old_binding["source_digest"]
    result = validate(module, receipt, SCOPE, current_binding)

    assert result["valid"] is False
    assert result["code"] == "SOURCE_FINGERPRINT_MISMATCH"


def test_receipt_reuse_rejects_staged_index_movement(tmp_path: Path) -> None:
    module = subject()
    repo = make_repo(tmp_path)
    old_binding, receipt = capture_receipt(repo, module)
    source = repo / "src" / "input.py"
    original_bytes = source.read_bytes()

    source.write_bytes(b"value = 2\n")
    git(repo, "add", "src/input.py")
    source.write_bytes(original_bytes)
    current_binding = module.capture_source_binding(repo, SCOPE)
    assert current_binding["head"] == old_binding["head"]
    assert source.read_bytes() == original_bytes
    assert current_binding["source_digest"] != old_binding["source_digest"]
    result = validate(module, receipt, SCOPE, current_binding)

    assert result["valid"] is False
    assert result["code"] == "SOURCE_FINGERPRINT_MISMATCH"


def test_receipt_validation_preserves_unrelated_ignored_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = subject()
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "--quiet", "-m", "ignore local scratch")
    ignored = repo / "scratch" / "temporary.bin"
    ignored.parent.mkdir()
    ignored_bytes = b"ignored temporary bytes that must remain untouched\x00\xff"
    ignored.write_bytes(ignored_bytes)
    before_stat = ignored.stat()
    baseline_status = git(repo, "status", "--porcelain", "--untracked-files=all")

    ignored_key = os.path.normcase(os.path.abspath(ignored))

    def guard_path(path: object) -> None:
        try:
            candidate = os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
        except (TypeError, ValueError):
            return
        assert candidate != ignored_key, "capture inspected the unrelated ignored temporary file"

    with monkeypatch.context() as patcher:
        original_stat = os.stat
        original_lstat = os.lstat
        original_open = os.open
        original_path_open = Path.open

        def guarded_stat(path: object, *args: object, **kwargs: object):
            guard_path(path)
            return original_stat(path, *args, **kwargs)

        def guarded_lstat(path: object, *args: object, **kwargs: object):
            guard_path(path)
            return original_lstat(path, *args, **kwargs)

        def guarded_open(path: object, *args: object, **kwargs: object):
            guard_path(path)
            return original_open(path, *args, **kwargs)

        def guarded_path_open(path: Path, *args: object, **kwargs: object):
            guard_path(path)
            return original_path_open(path, *args, **kwargs)

        def reject_directory_scan(*args: object, **kwargs: object):
            raise AssertionError("capture must not enumerate repository directories")

        patcher.setattr(os, "stat", guarded_stat)
        patcher.setattr(os, "lstat", guarded_lstat)
        patcher.setattr(os, "open", guarded_open)
        patcher.setattr(os, "scandir", reject_directory_scan)
        patcher.setattr(Path, "open", guarded_path_open)
        binding, receipt = capture_receipt(repo, module)
        result = validate(module, receipt, SCOPE, binding)

    after_stat = ignored.stat()

    assert result["valid"] is True
    assert result["code"] == "VALID"
    assert ignored.exists()
    assert ignored.read_bytes() == ignored_bytes
    assert (after_stat.st_dev, after_stat.st_ino, after_stat.st_size, after_stat.st_mtime_ns) == (
        before_stat.st_dev,
        before_stat.st_ino,
        before_stat.st_size,
        before_stat.st_mtime_ns,
    )
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == baseline_status


def test_scope_paths_and_receipt_schema_fail_closed(tmp_path: Path) -> None:
    module = subject()
    repo = make_repo(tmp_path)

    bad_scopes = [
        ([], "SCOPE_INVALID"),
        (["src/input.py", "src/input.py"], "SCOPE_DUPLICATE"),
        (["../outside.py"], "PATH_INVALID"),
        (["/absolute/source.py"], "PATH_INVALID"),
        (["src//input.py"], "PATH_INVALID"),
        (["src/./input.py"], "PATH_INVALID"),
        (["src\\input.py"], "PATH_INVALID"),
    ]
    for scope, code in bad_scopes:
        with pytest.raises(module.ReceiptError) as error:
            module.capture_source_binding(repo, scope)
        assert error.value.code == code

    with pytest.raises(module.ReceiptError) as missing:
        module.capture_source_binding(repo, ["src/missing.py"])
    assert missing.value.code == "SOURCE_MISSING"

    binding, receipt = capture_receipt(repo, module)
    malformed = dict(receipt)
    malformed["unexpected"] = "field"
    result = validate(module, malformed, SCOPE, binding)
    assert result["valid"] is False
    assert result["code"] == "RECEIPT_SCHEMA_INVALID"

    missing_field = dict(receipt)
    del missing_field["source_digest"]
    result = validate(module, missing_field, SCOPE, binding)
    assert result["valid"] is False
    assert result["code"] == "RECEIPT_SCHEMA_INVALID"


def test_capture_refuses_symlinked_scope_source(tmp_path: Path) -> None:
    module = subject()
    repo = make_repo(tmp_path)
    target = repo / "src" / "input.py"
    real_source = repo / "src" / "real.py"
    target.rename(real_source)
    try:
        target.symlink_to(real_source)
    except (OSError, NotImplementedError):
        pytest.skip("this Windows environment does not permit creating symlinks")

    with pytest.raises(module.ReceiptError) as error:
        module.capture_source_binding(repo, SCOPE)
    assert error.value.code == "PATH_REPARSE_REFUSED"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior is platform-specific")
def test_capture_refuses_intermediate_junction_without_reading_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = subject()
    repo = make_repo(tmp_path)
    outside = tmp_path / "outside-repository"
    outside.mkdir()
    protected = outside / "secret.py"
    protected.write_bytes(b"must not be opened through a junction\n")
    junction = repo / "src" / "linked"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("this Windows environment could not create a temporary junction")
    assert os.lstat(junction).st_file_attributes & 0x400

    protected_key = os.path.normcase(os.path.abspath(protected))

    def guard_path(path: object) -> None:
        try:
            candidate = os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
        except (TypeError, ValueError):
            return
        assert candidate != protected_key, "capture followed a junction to an outside file"

    with monkeypatch.context() as patcher:
        original_stat = os.stat
        original_lstat = os.lstat
        original_open = os.open

        def guarded_stat(path: object, *args: object, **kwargs: object):
            guard_path(path)
            return original_stat(path, *args, **kwargs)

        def guarded_lstat(path: object, *args: object, **kwargs: object):
            guard_path(path)
            return original_lstat(path, *args, **kwargs)

        def guarded_open(path: object, *args: object, **kwargs: object):
            guard_path(path)
            return original_open(path, *args, **kwargs)

        patcher.setattr(os, "stat", guarded_stat)
        patcher.setattr(os, "lstat", guarded_lstat)
        patcher.setattr(os, "open", guarded_open)
        with pytest.raises(module.ReceiptError) as error:
            module.capture_source_binding(repo, ["src/linked/secret.py"])

    assert error.value.code == "PATH_REPARSE_REFUSED"


def test_validation_rejects_identity_and_integrator_scope_mismatch(tmp_path: Path) -> None:
    module = subject()
    repo = make_repo(tmp_path)
    (repo / "src" / "other.py").write_bytes(b"other = True\n")
    git(repo, "add", "src/other.py")
    git(repo, "commit", "--quiet", "-m", "add another source")
    binding, receipt = capture_receipt(repo, module)

    result = module.validate_family_receipt(
        receipt,
        **{**IDENTITY, "campaign": "different-campaign"},
        expected_scope=SCOPE,
        current_binding=binding,
    )
    assert result["valid"] is False
    assert result["code"] == "IDENTITY_MISMATCH"

    other_scope = ["src/other.py"]
    other_binding = module.capture_source_binding(repo, other_scope)
    result = validate(module, receipt, other_scope, other_binding)
    assert result["valid"] is False
    assert result["code"] == "SCOPE_MISMATCH"
