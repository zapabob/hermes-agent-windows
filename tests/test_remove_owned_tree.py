"""Storage cleanup must not widen its authority when retrying Git objects."""
from pathlib import Path
import stat
import pytest
from utils import remove_owned_tree


def test_removes_readonly_owned_files_without_changing_sibling(tmp_path):
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "object").write_bytes(b"OWNED_FIXTURE")
    (owned / "object").chmod(stat.S_IREAD)
    sibling = tmp_path / "sibling"
    sibling.write_bytes(b"KEEP")
    remove_owned_tree(owned, boundary=tmp_path)
    assert not owned.exists()
    assert sibling.read_bytes() == b"KEEP"


@pytest.mark.parametrize("mode", ["boundary", "outside"])
def test_refuses_boundary_and_outside_targets(tmp_path, mode):
    boundary = tmp_path / "boundary"
    boundary.mkdir()
    target = boundary if mode == "boundary" else tmp_path / "outside"
    target.mkdir(exist_ok=True)
    (target / "keep").write_bytes(b"KEEP")
    with pytest.raises(ValueError, match="boundary"):
        remove_owned_tree(target, boundary=boundary)
    assert (target / "keep").read_bytes() == b"KEEP"


def test_refuses_directory_symlink(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "keep").write_bytes(b"KEEP")
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink creation is unavailable")
    with pytest.raises(ValueError):
        remove_owned_tree(link, boundary=tmp_path)
    assert (target / "keep").read_bytes() == b"KEEP"
