"""Normal cron writes must preserve an unreadable baseline for recovery."""

import json
import pytest

from cron import jobs


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    jobs.ensure_dirs()
    return jobs._current_cron_store().jobs_file


@pytest.mark.parametrize("payload", [b'{"jobs": [{"id": "broken', b"null", b'{"jobs": 7}'])
def test_normal_save_preserves_corrupt_store_bytes(store, payload):
    jobs.save_jobs([{"id": "first"}, {"id": "second"}], replace=True)
    store.write_bytes(payload)
    with pytest.raises(RuntimeError, match="(?i)(corrupt|unreadable|baseline)"):
        jobs.save_jobs([{"id": "first"}])
    assert store.read_bytes() == payload
    assert not list(store.parent.glob(".jobs_*.tmp"))


def test_unreadable_baseline_never_publishes(store, monkeypatch):
    jobs.save_jobs([{"id": "first"}], replace=True)
    original = store.read_bytes()

    def denied(_path):
        raise PermissionError("test-owned locked baseline")

    monkeypatch.setattr(jobs, "_parse_jobs_file", denied)
    with pytest.raises(RuntimeError, match="(?i)(corrupt|unreadable|baseline)"):
        jobs.save_jobs([])
    assert store.read_bytes() == original


def test_baseline_becoming_unreadable_after_staging_never_publishes(store, monkeypatch):
    jobs.save_jobs([{"id": "first"}], replace=True)
    original = store.read_bytes()
    peeks = iter([[{"id": "first"}], None])
    monkeypatch.setattr(jobs, "_peek_jobs_unlocked", lambda: next(peeks))
    monkeypatch.setattr(jobs, "_jobs_file_stamp", lambda path: None)
    with pytest.raises(RuntimeError, match="(?i)(corrupt|unreadable|baseline)"):
        jobs.save_jobs([{"id": "first"}, {"id": "second"}])
    assert store.read_bytes() == original
    assert not list(store.parent.glob(".jobs_*.tmp"))


def test_continuous_concurrent_changes_refuse_unverified_final_write(store, monkeypatch):
    jobs.save_jobs([{"id": "original"}], replace=True)
    original = store.read_bytes()
    reads = []

    def changing_baseline():
        reads.append(len(reads))
        return [{"id": f"concurrent-{len(reads)}"}]

    monkeypatch.setattr(jobs, "_peek_jobs_unlocked", changing_baseline)
    monkeypatch.setattr(jobs, "_jobs_file_stamp", lambda path: None)
    with pytest.raises(RuntimeError, match="kept changing"):
        jobs.save_jobs([])
    assert len(reads) == 10
    assert store.read_bytes() == original
    assert not list(store.parent.glob(".jobs_*.tmp"))


def test_explicit_repair_then_create_and_remove_have_effect(store):
    store.write_bytes(b"unrecoverable")
    jobs.save_jobs([], replace=True)
    created = jobs.create_job(prompt="owned recovery control", schedule="every 5m", deliver="local")
    assert created["id"] in {job["id"] for job in json.loads(store.read_text(encoding="utf-8"))["jobs"]}
    assert jobs.remove_job(created["id"]) is True
    assert json.loads(store.read_text(encoding="utf-8"))["jobs"] == []


def test_id_keyed_load_repair_preserves_records(store):
    store.write_text(json.dumps({"jobs": {"first": {"name": "retained"}}}), encoding="utf-8")
    assert jobs.load_jobs() == [{"id": "first", "name": "retained"}]
    assert json.loads(store.read_text(encoding="utf-8"))["jobs"] == [{"id": "first", "name": "retained"}]


def test_stale_save_preserves_new_job_but_respects_removed_ids(store):
    jobs.save_jobs([{"id": "first"}, {"id": "new"}], replace=True)
    jobs.save_jobs([], removed_ids={"first"})
    assert json.loads(store.read_text(encoding="utf-8"))["jobs"] == [{"id": "new"}]
