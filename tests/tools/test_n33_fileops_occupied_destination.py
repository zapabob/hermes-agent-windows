"""A failed path read must never make a V4A destination appear free."""

from types import SimpleNamespace

import pytest

from tools.file_operations import ShellFileOperations
from tools.patch_parser import apply_v4a_operations, parse_v4a_patch


class _DanglingLinkBackend:
    cwd = "/"

    def execute(self, command, **_kwargs):
        # Model a POSIX backend with a dangling symlink at /virtual/link.txt:
        # -f and -e follow its missing target, while -L sees the directory entry.
        if " -L " in command:
            return {"output": "__hermes_not_regular__\n", "returncode": 0}
        return {"output": "", "returncode": 1}


@pytest.mark.parametrize("reader", ["read_file", "read_file_raw", "read_file_bytes"])
def test_dangling_link_is_not_reported_missing_by_shell_readers(reader):
    result = getattr(ShellFileOperations(_DanglingLinkBackend()), reader)(
        "/virtual/link.txt"
    )
    assert result.error and "not a regular file" in result.error
    assert not getattr(result, "not_found", False)


@pytest.mark.parametrize(
    "reply,expected_missing",
    [
        ({"output": "__hermes_missing__\n", "returncode": 0}, True),
        ({"output": "", "returncode": 1}, False),
    ],
    ids=["confirmed-absent", "backend-failure"],
)
def test_raw_read_distinguishes_missing_entry_from_backend_failure(
    reply, expected_missing
):
    class Backend:
        cwd = "/"

        def execute(self, _command, **_kwargs):
            return reply

    result = ShellFileOperations(Backend()).read_file_raw("/virtual/entry.txt")
    assert bool(result.not_found) is expected_missing
    assert result.error


class _PatchOps:
    def __init__(self, destination):
        self.destination = destination
        self.writes = []

    def read_file_raw(self, path):
        if path == "src.txt":
            return SimpleNamespace(content="SOURCE\n", error=None, not_found=False)
        if path == "link.txt":
            if isinstance(self.destination, list):
                return self.destination.pop(0)
            return self.destination
        return SimpleNamespace(content="", error="File not found", not_found=True)

    def write_file(self, path, content):
        self.writes.append(("write", path, content))
        return SimpleNamespace(error=None)

    def move_file(self, source, destination):
        self.writes.append(("move", source, destination))
        return SimpleNamespace(error=None)


@pytest.mark.parametrize("operation", ["Add", "Move"])
@pytest.mark.parametrize(
    "destination",
    [
        SimpleNamespace(content="", error="not a regular file", not_found=False),
        SimpleNamespace(content="", error="backend read failed", not_found=False),
    ],
    ids=["dangling-link", "backend-error"],
)
def test_patch_refuses_unproven_destination_without_writing(operation, destination):
    header = (
        "*** Add File: link.txt\n+NEW\n"
        if operation == "Add"
        else "*** Move File: src.txt -> link.txt\n"
    )
    operations, parse_error = parse_v4a_patch(
        f"*** Begin Patch\n{header}*** End Patch"
    )
    assert parse_error is None
    file_ops = _PatchOps(destination)
    result = apply_v4a_operations(operations, file_ops)
    assert not result.success
    assert not file_ops.writes


@pytest.mark.parametrize("operation", ["Add", "Move"])
def test_patch_accepts_proven_missing_destination(operation):
    header = (
        "*** Add File: link.txt\n+NEW\n"
        if operation == "Add"
        else "*** Move File: src.txt -> link.txt\n"
    )
    operations, parse_error = parse_v4a_patch(
        f"*** Begin Patch\n{header}*** End Patch"
    )
    assert parse_error is None
    file_ops = _PatchOps(
        SimpleNamespace(content="", error="File not found", not_found=True)
    )
    result = apply_v4a_operations(operations, file_ops)
    assert result.success, result.error
    assert len(file_ops.writes) == 1


@pytest.mark.parametrize("operation", ["Add", "Move"])
def test_patch_refuses_existing_destination(operation):
    header = (
        "*** Add File: link.txt\n+NEW\n"
        if operation == "Add"
        else "*** Move File: src.txt -> link.txt\n"
    )
    operations, parse_error = parse_v4a_patch(
        f"*** Begin Patch\n{header}*** End Patch"
    )
    assert parse_error is None
    file_ops = _PatchOps(
        SimpleNamespace(content="ORIGINAL", error=None, not_found=False)
    )
    result = apply_v4a_operations(operations, file_ops)
    assert not result.success
    assert not file_ops.writes


@pytest.mark.parametrize("operation", ["Add", "Move"])
def test_patch_rechecks_destination_after_validation(operation):
    header = (
        "*** Add File: link.txt\n+NEW\n"
        if operation == "Add"
        else "*** Move File: src.txt -> link.txt\n"
    )
    operations, parse_error = parse_v4a_patch(
        f"*** Begin Patch\n{header}*** End Patch"
    )
    assert parse_error is None
    file_ops = _PatchOps(
        [
            SimpleNamespace(content="", error="File not found", not_found=True),
            SimpleNamespace(content="ORIGINAL", error=None, not_found=False),
        ]
    )
    result = apply_v4a_operations(operations, file_ops)
    assert not result.success
    assert not file_ops.writes


def test_occupied_later_add_rejects_whole_patch_before_earlier_write():
    operations, parse_error = parse_v4a_patch(
        "*** Begin Patch\n"
        "*** Add File: free.txt\n+FIRST\n"
        "*** Add File: link.txt\n+SECOND\n"
        "*** End Patch"
    )
    assert parse_error is None
    file_ops = _PatchOps(
        SimpleNamespace(content="ORIGINAL", error=None, not_found=False)
    )
    result = apply_v4a_operations(operations, file_ops)
    assert not result.success
    assert not file_ops.writes
