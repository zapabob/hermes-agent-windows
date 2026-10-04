"""Native console suppression through the banner's actual Git helper."""
import subprocess
import sys
import pytest
from hermes_cli import banner


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows console visibility')
def test_git_probe_does_not_create_console(tmp_path, monkeypatch):
    original_popen = subprocess.Popen
    outputs = []

    def probe(command, **kwargs):
        assert kwargs.get('creationflags', 0) & subprocess.CREATE_NO_WINDOW
        if '--version' in command:
            command = [sys.executable, '-I', '-c',
                'import ctypes,sys;sys.stdout.write(str(ctypes.windll.kernel32.GetConsoleWindow()))']
            result = original_popen(command, **kwargs)
            outputs.append(result)
        else:
            result = original_popen(command, **kwargs)
        return result

    monkeypatch.setattr(subprocess, 'Popen', probe)
    assert banner._git_stdout(['--version'], cwd=tmp_path) == '0'
    assert len(outputs) == 1
    assert outputs[0].returncode == 0
