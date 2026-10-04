"""Exercise the Irodori launcher with a real, isolated Windows Python child."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import venv
from pathlib import Path
from urllib.request import urlopen

import psutil
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def installed_server(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "irodori server"
    environment = repo / ".venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    package = environment / "Lib" / "site-packages" / "irodori_openai_tts"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(
        textwrap.dedent(
            """\
            import argparse
            import json
            import os
            import sys
            from http.server import BaseHTTPRequestHandler, HTTPServer
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument("--host")
            parser.add_argument("--port", type=int)
            args = parser.parse_args()
            Path("server.pid").write_text(str(os.getpid()), encoding="utf-8")
            payload = json.dumps({
                "status": "ok",
                "prefix": sys.prefix,
                "module": __file__,
                "path": sys.path,
                "pid": os.getpid(),
                "model_device": os.environ.get("IRODORI_MODEL_DEVICE"),
                "codec_device": os.environ.get("IRODORI_CODEC_DEVICE"),
                "model_precision": os.environ.get("IRODORI_MODEL_PRECISION"),
                "codec_precision": os.environ.get("IRODORI_CODEC_PRECISION"),
            }).encode("utf-8")

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload)

                def log_message(self, *args):
                    pass

            HTTPServer((args.host, args.port), Handler).serve_forever()
            """
        ),
        encoding="utf-8",
    )
    return repo, package


@pytest.mark.windows_only
@pytest.mark.parametrize("pollution", ["PYTHONPATH", "PYTHONHOME", None])
def test_launcher_uses_server_venv_despite_parent_python_environment(
    tmp_path: Path, pollution: str | None, installed_server: tuple[Path, Path]
) -> None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell is required for the live launcher test")

    repo, package = installed_server
    environment = repo / ".venv"
    foreign_packages = tmp_path / "foreign Python packages"
    foreign_packages.mkdir()
    (foreign_packages / "irodori_openai_tts.py").write_text(
        'raise RuntimeError("Imported packages from the parent Python environment")\n',
        encoding="utf-8",
    )
    child_env = os.environ.copy()
    child_env.pop("PYTHONPATH", None)
    child_env.pop("PYTHONHOME", None)
    child_env["LOCALAPPDATA"] = str(tmp_path / "local-app-data")
    if pollution == "PYTHONPATH":
        child_env[pollution] = str(foreign_packages)
    elif pollution == "PYTHONHOME":
        child_env[pollution] = str(tmp_path / "missing Python installation")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    pid_file = repo / "server.pid"
    stdout_path = tmp_path / "launcher-stdout.log"
    stderr_path = tmp_path / "launcher-stderr.log"
    try:
        # File handles avoid inherited capture pipes held by the detached server.
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(REPO_ROOT / "scripts" / "windows" / "start-irodori-tts.ps1"),
                    "-RepoDir",
                    str(repo),
                    "-Port",
                    str(port),
                    "-HfCacheRoot",
                    str(tmp_path / "hf-cache"),
                    "-StartupTimeoutSeconds",
                    "10",
                ],
                env=child_env,
                stdout=stdout,
                stderr=stderr,
                timeout=30,
            )
        assert completed.returncode == 0, stdout_path.read_text(
            encoding="utf-8", errors="replace"
        ) + stderr_path.read_text(encoding="utf-8", errors="replace")
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            health = json.load(response)
        assert health["status"] == "ok"
        assert Path(health["prefix"]).resolve() == environment.resolve()
        assert Path(health["module"]).resolve().parent == package.resolve()
        assert str(foreign_packages) not in health["path"]
    finally:
        if pid_file.exists():
            try:
                child = psutil.Process(int(pid_file.read_text(encoding="utf-8")))
                child.terminate()
                child.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass


@pytest.mark.windows_only
def test_synthesis_returns_while_cold_started_server_keeps_running(
    tmp_path: Path, monkeypatch, installed_server: tuple[Path, Path]
) -> None:
    from plugins.irodori_tts import core

    if not core.powershell_path():
        pytest.skip("PowerShell is required for the live synthesis test")
    repo, _ = installed_server
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    invoke_script = tmp_path / "invoke.ps1"
    start_script = REPO_ROOT / "scripts" / "windows" / "start-irodori-tts.ps1"
    invoke_script.write_text(
        "param([string]$InputPath, [string]$OutputPath, [string]$Format, "
        "[string]$Voice, [string]$Model, [double]$Speed, [string]$BaseUrl)\n"
        "$ErrorActionPreference = 'Stop'\n"
        f"& '{start_script}' -RepoDir '{repo}' -Port {port} "
        f"-HfCacheRoot '{tmp_path / 'hf-cache'}' -StartupTimeoutSeconds 10 | Out-Null\n"
        "[IO.File]::WriteAllBytes($OutputPath, "
        "[Text.Encoding]::ASCII.GetBytes('RIFFsynthetic-test'))\n"
        "Write-Output 'synthesis complete'\n",
        encoding="utf-8",
    )
    cfg = core.IrodoriSettings(
        repo_dir=repo,
        start_script=start_script,
        invoke_script=invoke_script,
        base_url=f"http://127.0.0.1:{port}",
        model="irodori-tts",
        voice="none",
        speed=1.0,
        timeout=15,
    )
    monkeypatch.setattr(core, "settings", lambda: cfg)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    output = tmp_path / "sample.wav"
    pid_file = repo / "server.pid"
    try:
        worker_code = (
            "import json,sys; from pathlib import Path; "
            "from plugins.irodori_tts import core; "
            "config=json.loads(sys.argv[1]); "
            "config.update({key:Path(config[key]) for key in "
            "['repo_dir','start_script','invoke_script']}); "
            "core.settings=lambda:core.IrodoriSettings(**config); "
            "result=core.synthesize_text('Synthetic test only.', "
            "output_path=sys.argv[2],buffer=False); assert result['ok']"
        )
        config = dict(vars(cfg))
        for key in ["repo_dir", "start_script", "invoke_script"]:
            config[key] = str(config[key])
        worker_env = os.environ.copy()
        worker_env["PYTHONPATH"] = str(REPO_ROOT)
        stdout_path = tmp_path / "worker-stdout.log"
        stderr_path = tmp_path / "worker-stderr.log"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            worker = subprocess.Popen(
                [sys.executable, "-c", worker_code, json.dumps(config), str(output)],
                cwd=REPO_ROOT,
                env=worker_env,
                stdout=stdout,
                stderr=stderr,
            )
            try:
                try:
                    returncode = worker.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    pytest.fail(
                        "Synthesis caller did not return after the script exited"
                    )
            finally:
                if worker.poll() is None:
                    worker.terminate()
                    worker.wait(timeout=5)
        assert returncode == 0, stderr_path.read_text(
            encoding="utf-8", errors="replace"
        )
        assert output.read_bytes() == b"RIFFsynthetic-test"
        with urlopen(f"{cfg.base_url}/health", timeout=5) as response:
            assert json.load(response)["status"] == "ok"
    finally:
        if pid_file.exists():
            try:
                child = psutil.Process(int(pid_file.read_text(encoding="utf-8")))
                child.terminate()
                child.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass


@pytest.mark.windows_only
@pytest.mark.parametrize(
    "free_memory,cuda_available,device,expected",
    [
        ("6600", True, "auto", "cuda"),
        ("2500", True, "auto", "cpu"),
        ("6143", True, "auto", "cpu"),
        ("6144", True, "auto", "cuda"),
        ("6600", False, "auto", "cpu"),
        ("unavailable", True, "auto", "cpu"),
        ("6600", True, "cpu", "cpu"),
    ],
)
def test_launcher_uses_spare_gpu_memory(
    tmp_path: Path,
    installed_server: tuple[Path, Path],
    free_memory: str,
    cuda_available: bool,
    device: str,
    expected: str,
) -> None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell is required for the live launcher test")
    repo, package = installed_server
    (package.parent / "torch.py").write_text(
        "class cuda:\n"
        "    @staticmethod\n"
        f"    def is_available(): return {cuda_available}\n",
        encoding="utf-8",
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    driver = tmp_path / "launch-gpu.ps1"
    launcher = REPO_ROOT / "scripts/windows/start-irodori-tts.ps1"
    driver.write_text(
        f"function nvidia-smi {{ '{free_memory}' }}\n"
        f"& '{launcher}' -RepoDir '{repo}' -Port {port} "
        f"-ModelDevice {device} -CodecDevice {device} "
        f"-HfCacheRoot '{tmp_path / 'hf-cache'}' -StartupTimeoutSeconds 10\n",
        encoding="utf-8",
    )
    child_env = os.environ.copy()
    child_env["LOCALAPPDATA"] = str(tmp_path / "local-app-data")
    pid_file = repo / "server.pid"
    try:
        with (
            (tmp_path / "out.log").open("wb") as out,
            (tmp_path / "err.log").open("wb") as err,
        ):
            result = subprocess.run(
                [powershell, "-NoProfile", "-File", str(driver)],
                env=child_env,
                stdout=out,
                stderr=err,
                timeout=30,
            )
        assert result.returncode == 0, (tmp_path / "err.log").read_text(
            encoding="utf-8", errors="replace"
        )
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            health = json.load(response)
        assert health["model_device"] == expected
        assert health["codec_device"] == expected
        assert health["model_precision"] == ("bf16" if expected == "cuda" else "fp32")
        assert health["codec_precision"] == "fp32"
    finally:
        if pid_file.exists():
            try:
                child = psutil.Process(int(pid_file.read_text(encoding="utf-8")))
                child.terminate()
                child.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass


@pytest.mark.windows_only
def test_cold_start_targets_configured_port(tmp_path: Path) -> None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell is required for the live launcher test")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    receipt = tmp_path / "start.json"
    start_script = tmp_path / "start.ps1"
    start_script.write_text(
        "param([string]$HostName, [int]$Port)\n"
        "@{host=$HostName; port=$Port} | ConvertTo-Json | "
        f"Set-Content -LiteralPath '{receipt}' -Encoding UTF8\n"
        "throw 'Test boundary reached; no real server or synthesis is started'\n",
        encoding="utf-8",
    )
    input_path = tmp_path / "input.txt"
    input_path.write_text("Synthetic test only.", encoding="utf-8")
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-File",
            str(REPO_ROOT / "scripts/windows/invoke-irodori-tts.ps1"),
            "-InputPath",
            str(input_path),
            "-OutputPath",
            str(tmp_path / "unused.wav"),
            "-BaseUrl",
            f"http://127.0.0.1:{port}",
            "-StartScriptPath",
            str(start_script),
        ],
        capture_output=True,
        timeout=20,
    )
    assert result.returncode != 0
    actual = json.loads(receipt.read_text(encoding="utf-8-sig"))
    assert actual == {"host": "127.0.0.1", "port": port}


@pytest.mark.windows_only
def test_explicit_cuda_refuses_insufficient_headroom(
    tmp_path: Path, installed_server: tuple[Path, Path]
) -> None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell is required for the live launcher test")
    repo, _ = installed_server
    driver = tmp_path / "refuse-gpu.ps1"
    launcher = REPO_ROOT / "scripts/windows/start-irodori-tts.ps1"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    driver.write_text(
        "function nvidia-smi { '2500' }\n"
        f"& '{launcher}' -RepoDir '{repo}' -Port {port} "
        "-ModelDevice cuda -CodecDevice cuda "
        f"-HfCacheRoot '{tmp_path / 'hf-cache'}'\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp_path / "local-app-data")
    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(driver)],
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert b"6144 MiB" in result.stderr
    assert not (repo / "server.pid").exists()
