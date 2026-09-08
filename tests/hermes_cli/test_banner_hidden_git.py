"""Native console suppression through the banner's actual Git helper."""
import subprocess
import sys
import pytest
from hermes_cli import banner


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows console visibility')
def test_git_probe_does_not_create_console(tmp_path, monkeypatch):
    original_run = subprocess.run
    outputs = []

    def probe(command, **kwargs):
        assert kwargs.get('creationflags', 0) & subprocess.CREATE_NO_WINDOW
        result = original_run([
            sys.executable, '-I', '-c',
            'import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())',
        ], **kwargs)
        outputs.append(result)
        return result

    monkeypatch.setattr(banner.subprocess, 'run', probe)
    assert banner._git_stdout(['--version'], cwd=tmp_path) == '0'
    assert len(outputs) == 1
    assert outputs[0].returncode == 0
    assert outputs[0].stderr == ''
