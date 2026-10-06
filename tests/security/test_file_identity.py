"""File-generation comparisons retain platform-specific timestamp meaning."""
from types import SimpleNamespace

import pytest

from downstream.security import file_identity


@pytest.mark.parametrize("windows,birth,ctime,expected", [
    (True, 123, 456, 123), (True, None, 456, 456),
    (False, 123, 456, 456), (False, None, 456, 456),
])
def test_generation_timestamp_preserves_stat_contract(monkeypatch, windows, birth, ctime, expected):
    monkeypatch.setattr(file_identity, "_IS_WINDOWS", windows)
    metadata = SimpleNamespace(st_dev=1, st_ino=2, st_size=3,
                               st_mtime_ns=4, st_ctime_ns=ctime)
    if birth is not None:
        metadata.st_birthtime_ns = birth
    assert file_identity.stable_stat_identity(metadata) == (1, 2, 3, 4, expected)


def test_windows_path_and_handle_ctime_difference_is_not_a_replacement(monkeypatch):
    monkeypatch.setattr(file_identity, "_IS_WINDOWS", True)
    path = SimpleNamespace(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4,
                           st_ctime_ns=123, st_birthtime_ns=123)
    handle = SimpleNamespace(**vars(path))
    handle.st_ctime_ns = 456
    assert file_identity.stable_stat_identity(path) == file_identity.stable_stat_identity(handle)
    handle.st_mtime_ns = 5
    assert file_identity.stable_stat_identity(path) != file_identity.stable_stat_identity(handle)
    handle.st_mtime_ns = 4
    handle.st_ino = 6
    assert file_identity.stable_stat_identity(path) != file_identity.stable_stat_identity(handle)
