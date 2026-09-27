"""Native local Python snippets must use a working interpreter on Windows."""

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


def test_delete_file_uses_local_interpreter_for_unicode_and_quoted_path(tmp_path):
    folder = tmp_path / "folder with space"
    folder.mkdir()
    target = folder / "café's.txt"
    target.write_text("keep until deletion", encoding="utf-8")
    env = LocalEnvironment(cwd=str(tmp_path))
    try:
        operations = ShellFileOperations(env, cwd=str(tmp_path))
        result = operations.delete_file(str(target))
        assert result.error is None
        assert not target.exists()
        directory_result = operations.delete_file(str(folder))
        assert directory_result.error is not None
        assert folder.is_dir()
    finally:
        env.cleanup()
