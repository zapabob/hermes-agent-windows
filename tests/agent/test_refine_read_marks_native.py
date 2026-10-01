"""F08b full-read acceptance against real file and skill owners.

Direct owner tests intentionally do not bypass or exercise the review whitelist.
Local reads, skill provenance and patch effects are real. Failed/remote backend,
redactor, char budget, and concurrent modification controls are explicit doubles.
No upstream imports, provider transport, scanner replacement or paid API.
"""
from __future__ import annotations

import json
import os
import socket
import uuid
from types import SimpleNamespace

import pytest


@pytest.fixture
def owner(tmp_path, monkeypatch):
    home = tmp_path / "読取り所有プロフィール"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(home)
    (home / "config.yaml").write_text(
        "terminal:\n  backend: local\n  cwd: " + home.as_posix() + "\n"
        "skills:\n  external_dirs: []\n  guard_agent_created: true\n",
        encoding="utf-8",
    )
    attempts = []

    def deny_network(*args, **kwargs):
        attempts.append(str(args[:1]))
        raise AssertionError("owned read-mark test forbids network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    from tools import file_tools as files, skill_manager_tool as manager, skills_tool, skill_usage
    from tools.skill_provenance import set_current_write_origin, reset_current_write_origin, get_current_write_origin
    from tools.terminal_tool import cleanup_vm

    skills = home / "skills"
    folder = skills / "mark-owned"
    folder.mkdir(parents=True)
    content = "---\nname: mark-owned\ndescription: Preserve complete procedures.\n---\n\n# 手順\n\n旧手順\n"
    target = folder / "SKILL.md"
    target.write_text(content, encoding="utf-8")
    # Path-binding only; actual admission/scanner/ownership/guards stay real.
    monkeypatch.setattr(manager, "SKILLS_DIR", skills)
    monkeypatch.setattr(skills_tool, "SKILLS_DIR", skills)
    skill_usage.mark_agent_created("mark-owned")
    assert skill_usage.is_agent_created("mark-owned")
    task_id = "f08-mark-owned-" + uuid.uuid4().hex
    previous_marks = manager._background_review_read_paths.set(None)
    manager._reset_background_review_read_marks()
    origin = set_current_write_origin("background_review")

    def read(path=None, **kwargs):
        return json.loads(files.read_file_tool(str(path or target), task_id=task_id, **kwargs))

    def patch():
        return json.loads(manager.skill_manage(
            action="patch", name="mark-owned", old_string="旧手順", new_string="新しい完全な手順",
        ))

    def refused():
        assert manager._background_review_has_read(target) is False
        result = patch()
        assert result.get("success") is False, result
        assert result.get("_read_before_write_required") is True, result
        assert "新しい完全な手順" not in target.read_text(encoding="utf-8")
        return result

    def foreground_read(**kwargs):
        token = set_current_write_origin("foreground")
        try:
            return read(**kwargs)
        finally:
            reset_current_write_origin(token)

    try:
        yield SimpleNamespace(
            home=home, folder=folder, target=target, content=content, files=files,
            manager=manager, read=read, patch=patch, refused=refused,
            foreground_read=foreground_read, task_id=task_id,
        )
    finally:
        reset_current_write_origin(origin)
        manager._background_review_read_paths.reset(previous_marks)
        cleanup_vm(task_id)
        assert get_current_write_origin() == "foreground"
        assert not attempts, attempts


@pytest.mark.parametrize("resolved_alias", [False, True])
def test_full_stable_unredacted_host_read_marks_exact_target_and_patches(owner, resolved_alias):
    path = owner.folder / "." / "SKILL.md" if resolved_alias else owner.target
    # An actual '..' spelling is normalized by the host path resolver; no skill
    # write traversal is requested, and the resolved read stays in the owned root.
    if resolved_alias:
        (owner.folder / "references").mkdir()
        path = owner.folder / "references" / ".." / "SKILL.md"
    result = owner.read(path)
    assert "error" not in result and "旧手順" in result.get("content", ""), result
    assert not result.get("truncated") and not result.get("dedup"), result
    assert owner.manager._background_review_has_read(owner.target) is True
    patch = owner.patch()
    assert patch.get("success") is True, patch
    assert "新しい完全な手順" in owner.target.read_text(encoding="utf-8")


def test_equivalent_skill_view_control_and_fresh_review_isolation(owner):
    from tools.skills_tool import skill_view
    result = json.loads(skill_view("mark-owned"))
    assert result.get("success") is True, result
    assert owner.manager._background_review_has_read(owner.target) is True
    assert owner.patch().get("success") is True
    owner.manager._reset_background_review_read_marks()
    assert owner.manager._background_review_has_read(owner.target) is False


def test_missing_read_does_not_authorize_existing_skill(owner):
    result = owner.read(owner.folder / "missing.md")
    assert result.get("error"), result
    owner.refused()


def test_failed_backend_read_does_not_mark_or_patch(owner, monkeypatch):
    from tools.file_operations import ReadResult
    real = owner.files._get_file_ops(owner.task_id)
    backend = SimpleNamespace(env=real.env, read_file=lambda *a: ReadResult(error="owned forced backend read failure"))
    monkeypatch.setattr(owner.files, "_get_file_ops", lambda task_id: backend)
    result = owner.read()
    assert result.get("error") == "owned forced backend read failure", result
    owner.refused()


def test_partial_offset_does_not_mark_or_patch(owner):
    result = owner.read(offset=2)
    assert "error" not in result and result.get("content"), result
    assert not result["content"].startswith("1|"), result
    owner.refused()


def test_line_limit_truncation_does_not_mark_or_patch(owner):
    result = owner.read(limit=2)
    assert "error" not in result and result.get("truncated") is True, result
    owner.refused()


def test_character_cap_does_not_mark_or_patch(owner, monkeypatch):
    monkeypatch.setattr(owner.files, "_get_max_read_chars", lambda: 24)
    result = owner.read()
    assert result.get("truncated") is True and result.get("truncated_by") == "bytes", result
    owner.refused()


def test_redacted_content_does_not_mark_or_patch(owner, monkeypatch):
    original = owner.files.redact_sensitive_text

    def redactor(text, **kwargs):
        # Forced secret redaction transport boundary, no real secret used.
        return original(text, **kwargs).replace("旧手順", "[owned-redacted]")

    monkeypatch.setattr(owner.files, "redact_sensitive_text", redactor)
    result = owner.read()
    assert "[owned-redacted]" in result.get("content", ""), result
    assert "旧手順" not in result.get("content", ""), result
    owner.refused()


def test_dedup_without_returned_content_does_not_grant_new_review_mark(owner):
    first = owner.foreground_read()
    assert "旧手順" in first.get("content", ""), first
    owner.manager._reset_background_review_read_marks()
    result = owner.read()
    assert result.get("dedup") is True and result.get("content_returned") is False, result
    owner.refused()


def test_non_host_read_does_not_mark_host_target(owner, monkeypatch):
    from tools.file_operations import ReadResult
    remote = SimpleNamespace(
        env=SimpleNamespace(),
        read_file=lambda *a: ReadResult(content="1|旧手順", total_lines=1, file_size=9),
    )
    monkeypatch.setattr(owner.files, "_get_file_ops", lambda task_id: remote)
    assert owner.files._file_ops_uses_host_paths(remote) is False
    result = owner.read()
    assert "error" not in result and "旧手順" in result.get("content", ""), result
    owner.refused()


def test_file_changed_during_read_does_not_mark_or_patch(owner, monkeypatch):
    real = owner.files._get_file_ops(owner.task_id)
    original = real.read_file

    def changed_after_backend_snapshot(*args, **kwargs):
        result = original(*args, **kwargs)
        owner.target.write_text(owner.content + "\n同時更新\n", encoding="utf-8")
        stat = owner.target.stat()
        os.utime(owner.target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        return result

    monkeypatch.setattr(real, "read_file", changed_after_backend_snapshot)
    result = owner.read()
    assert "旧手順" in result.get("content", "") and "同時更新" not in result.get("content", ""), result
    assert "同時更新" in owner.target.read_text(encoding="utf-8")
    owner.refused()


def test_foreign_target_read_does_not_authorize_requested_skill(owner):
    foreign = owner.home / "foreign-owned.txt"
    foreign.write_text("別の対象\n", encoding="utf-8")
    result = owner.read(foreign)
    assert "別の対象" in result.get("content", ""), result
    owner.refused()


def test_off_origin_read_does_not_mark_or_authorize_later_review(owner):
    result = owner.foreground_read()
    assert "旧手順" in result.get("content", ""), result
    owner.refused()


def test_per_line_clamp_does_not_mark_or_authorize_incomplete_skill(owner):
    from tools.tool_output_limits import get_max_line_length
    # Real host reader clamps one long line without setting pagination's
    # truncated flag. The original complete skill was not returned.
    maximum = get_max_line_length()
    owner.target.write_text(owner.content + "\n" + "x" * (maximum + 32) + "\n", encoding="utf-8")
    result = owner.read()
    assert "error" not in result and "... [truncated]" in result.get("content", ""), result
    assert not result.get("truncated"), result
    owner.refused()
