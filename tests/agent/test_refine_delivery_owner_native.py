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



def test_unfinished_dispatch_cannot_confirm_read(owner):
    manager = owner.manager
    with manager.capture_background_review_skill_reads() as reads:
        result = owner.read()
        manager.complete_background_review_skill_read_delivery(reads, content=json.dumps(result, ensure_ascii=False))
        owner.refused()
    manager.complete_background_review_skill_read_delivery(reads, content=json.dumps(result, ensure_ascii=False))
    assert owner.patch().get("success") is True


def test_delivery_cannot_cross_review_reset(owner):
    manager = owner.manager
    with manager.capture_background_review_skill_reads() as reads:
        result = owner.read()
    manager._reset_background_review_read_marks()
    manager.complete_background_review_skill_read_delivery(reads, content=json.dumps(result, ensure_ascii=False))
    owner.refused()


@pytest.mark.parametrize("replacement", [None, "<persisted-output>preview</persisted-output>", "{truncated}"])
def test_omitted_delivery_does_not_confirm_or_replay(owner, replacement):
    manager = owner.manager
    with manager.capture_background_review_skill_reads() as reads:
        result = owner.read()
    manager.complete_background_review_skill_read_delivery(reads, content=replacement)
    owner.refused()
    if isinstance(replacement, str):
        manager.complete_background_review_skill_read_delivery(reads, content=json.dumps(result, ensure_ascii=False))
        owner.refused()


def test_complete_delivery_with_existing_hint_confirms(owner):
    manager = owner.manager
    with manager.capture_background_review_skill_reads() as reads:
        result = owner.read()
    manager.complete_background_review_skill_read_delivery(reads, content=json.dumps(result, ensure_ascii=False) + "\nExisting hint")
    assert owner.patch().get("success") is True


def test_support_file_delivery_marks_only_that_file(owner):
    from tools.skills_tool import skill_view
    support = owner.folder / "references/手順.md"
    support.parent.mkdir()
    support.write_text("旧手順\n", encoding="utf-8")
    manager = owner.manager
    with manager.capture_background_review_skill_reads() as reads:
        result = skill_view("mark-owned", file_path="references/手順.md")
    assert json.loads(result).get("success") is True
    manager.complete_background_review_skill_read_delivery(reads, content=result)
    assert manager._background_review_has_read(support) is True
    assert manager._background_review_has_read(owner.target) is False
    changed = json.loads(manager.skill_manage(action="patch", name="mark-owned", file_path="references/手順.md", old_string="旧手順", new_string="新しい完全な手順"))
    assert changed.get("success") is True, changed
    owner.refused()


def test_abandoned_worker_read_cannot_promote_after_parent_returns(owner):
    import contextvars
    import threading
    started, release, done = threading.Event(), threading.Event(), threading.Event()
    holder = {}
    manager = owner.manager
    def worker():
        with manager.capture_background_review_skill_reads() as reads:
            started.set()
            assert release.wait(5)
            holder["result"] = owner.read()
            holder["reads"] = reads
        done.set()
    ctx = contextvars.copy_context()
    thread = threading.Thread(target=ctx.run, args=(worker,))
    thread.start()
    try:
        assert started.wait(5)
        # An abandoned result has no candidate in the parent's delivery list.
        owner.refused()
    finally:
        release.set()
        thread.join(10)
    assert done.is_set() and not thread.is_alive()
    owner.refused()
