"""Native Windows behavioral proof for delegated process isolation."""

from __future__ import annotations

import sys
import ctypes
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from socket import socket, AF_INET, SOCK_DGRAM

import pytest

from agent.delegation_context import delegated_child_context
from downstream.platform.windows.delegated_execution import (
    NativeExecutionDenied,
    NativeExecutionProfile,
    NativeExecutionUnavailable,
    bind_native_execution_profile,
    launch_restricted,
    new_native_execution_profile,
)

EPHEMERAL_PROFILE_NAME = "HermesDelegated-T06Pytest-20260924"


class _SecurityAttributesForTest(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.c_uint32),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
    ]


def test_process_launch_requires_a_bound_delegated_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from downstream.platform.windows import delegated_execution

    workspace = tmp_path / "workspace"
    private_temp = workspace / ".private-temp"
    workspace.mkdir()
    private_temp.mkdir()
    profile = new_native_execution_profile(
        workspace=workspace,
        working_directory=workspace,
        toolchain_roots=(workspace,),
        private_temp=private_temp,
        generation=1,
    )
    monkeypatch.setattr(delegated_execution.sys, "platform", "win32")
    with pytest.raises(NativeExecutionDenied, match="authorized host profile"):
        launch_restricted([r"C:\synthetic\python.exe"], profile)


def test_removed_profile_cleanup_switch_is_rejected_during_collection(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    node_id = f"{Path(__file__).resolve()}::test_process_launch_requires_a_bound_delegated_profile"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            node_id,
            "--cleanup-t06-ephemeral-appcontainer-profile",
            "--t06-appcontainer-recovery-marker",
            str(tmp_path / "caller-controlled-marker.json"),
            "--t06-confirm-appcontainer-profile",
            EPHEMERAL_PROFILE_NAME,
            "--collect-only",
            "-q",
            "--basetemp",
            str(tmp_path / "nested-pytest"),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}".casefold()
    assert completed.returncode != 0 and "unrecognized arguments" in output, (
        "caller-controlled recovery switches must be rejected before pytest can collect or run them; "
        f"returncode={completed.returncode}, output={output}"
    )


@pytest.mark.windows_only
def test_acl_helper_ignores_mutable_systemroot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_root = tmp_path / "pytest-owned"
    owned_root.mkdir()
    attacker_root = tmp_path / "attacker-controlled"
    fake_system = attacker_root / "System32"
    fake_system.mkdir(parents=True)
    fake_icacls = fake_system / "icacls.exe"
    fake_icacls.write_text("synthetic executable path", encoding="utf-8")
    monkeypatch.setenv("SystemRoot", str(attacker_root))
    invoked = []

    def capture_run(argv, **kwargs):
        invoked.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", capture_run)
    _grant_test_access(owned_root, "S-1-15-2-12345", "M", tmp_path)
    _revoke_test_access(owned_root, "S-1-15-2-12345", tmp_path)

    assert len(invoked) == 2
    for argv in invoked:
        executable = Path(argv[0]).resolve(strict=True)
        assert executable.name.casefold() == "icacls.exe"
        assert not executable.is_relative_to(attacker_root.resolve())
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_system_directory = kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.POINTER(ctypes.c_wchar), ctypes.c_uint32]
    get_system_directory.restype = ctypes.c_uint32
    system_directory = ctypes.create_unicode_buffer(32768)
    length = get_system_directory(system_directory, len(system_directory))
    assert 0 < length < len(system_directory)
    assert Path(invoked[0][0]).resolve(strict=True) == (
        Path(system_directory.value) / "icacls.exe"
    ).resolve(strict=True)
    assert invoked[1][1:] == [
        str(owned_root.resolve()),
        "/remove:g",
        "*S-1-15-2-12345",
        "/T",
        "/C",
        "/Q",
    ]
    outside_target = tmp_path.parent / "external-acl-target"
    outside_target.mkdir()
    with pytest.raises(AssertionError, match="outside pytest tmp_path"):
        _revoke_test_access(outside_target, "S-1-15-2-12345", tmp_path)
    assert len(invoked) == 2


@pytest.mark.windows_only
@pytest.mark.parametrize(
    ("path", "reason"),
    [
        (Path(r"C:\synthetic\workspace\secret.txt:stream"), "alternate data stream"),
        (Path(r"\\synthetic-server\share\secret.txt"), "remote or device path"),
    ],
)
def test_profile_path_policy_rejects_ads_and_unc_without_opening_them(
    path: Path,
    reason: str,
) -> None:
    from downstream.platform.windows.delegated_execution import _resolve_plain_path

    with pytest.raises(NativeExecutionDenied, match=reason):
        _resolve_plain_path(path, "synthetic probe")


def _synthetic_profile(safe_environment: tuple[tuple[str, str], ...] = ()) -> NativeExecutionProfile:
    return NativeExecutionProfile(
        workspace=Path(r"C:\synthetic\workspace"),
        working_directory=Path(r"C:\synthetic\workspace"),
        toolchain_roots=(Path(r"C:\synthetic\python"),),
        private_temp=Path(r"C:\synthetic\workspace\.private-temp"),
        generation=1,
        appcontainer_name=EPHEMERAL_PROFILE_NAME,
        safe_environment=safe_environment,
    )


@pytest.mark.parametrize("name", ["LOCALAPPDATA", "localappdata"])
def test_profile_cannot_override_localappdata(name: str) -> None:
    with pytest.raises(ValueError, match="controlled by the host"):
        _synthetic_profile(((name, r"C:\attacker"),))


def test_child_environment_carries_localappdata_and_no_other_host_values() -> None:
    from downstream.platform.windows.delegated_execution import _build_child_environment

    host = {
        "LOCALAPPDATA": r"C:\Users\synthetic\AppData\Local",
        "SystemRoot": r"C:\Windows",
        "HERMES_T06_SYNTHETIC_PARENT_SECRET": "must-not-cross-boundary",
        "USERPROFILE": r"C:\Users\synthetic",
    }
    env = _build_child_environment(_synthetic_profile(), host)
    assert env["LOCALAPPDATA"] == host["LOCALAPPDATA"]
    assert "HERMES_T06_SYNTHETIC_PARENT_SECRET" not in env
    assert "USERPROFILE" not in env


def test_child_environment_refuses_by_name_without_localappdata() -> None:
    from downstream.platform.windows.delegated_execution import _build_child_environment

    with pytest.raises(NativeExecutionUnavailable, match="LOCALAPPDATA"):
        _build_child_environment(_synthetic_profile(), {"SystemRoot": r"C:\Windows"})


def _assert_inside_worktree(path: Path, repo_root: Path) -> None:
    assert path.drive.casefold() == repo_root.drive.casefold(), (
        "native T06 probe basetemp must share the isolated worktree volume"
    )
    assert path.is_relative_to(repo_root), (
        f"native T06 probe files must remain inside pytest tmp_path: {path}"
    )


class _SharedToolchains:
    """Toolchain copies made once per session; each copy of Git alone is ~0.5 GB."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._python: Path | None = None
        self._node_git: tuple[Path, Path, Path, Path] | None = None
        self._granted: dict[str, set[Path]] = {}

    def python(self) -> Path:
        if self._python is None:
            python_root = self.root / "python"
            python_root.mkdir(parents=True)
            source = Path(sys.base_prefix)
            for name in (
                "python.exe",
                f"python{sys.version_info.major}{sys.version_info.minor}.dll",
                "python3.dll",
                "vcruntime140.dll",
                "vcruntime140_1.dll",
            ):
                source_file = source / name
                if source_file.is_file():
                    shutil.copy2(source_file, python_root / name)
            shutil.copytree(source / "DLLs", python_root / "DLLs")
            shutil.copytree(
                source / "Lib",
                python_root / "Lib",
                ignore=shutil.ignore_patterns("site-packages", "__pycache__"),
            )
            self._python = python_root
        return self._python

    def node_and_git(self) -> tuple[Path, Path, Path, Path]:
        if self._node_git is None:
            node_location = shutil.which("node.exe")
            git_location = shutil.which("git.exe")
            if not node_location or not git_location:
                pytest.skip("native Node.js and Git executables are required for the T06 positive probes")
            node_source = Path(node_location).resolve(strict=True)
            git_source = Path(git_location).resolve(strict=True)
            node_root = self.root / "node"
            git_root = self.root / "git"
            node_root.mkdir(parents=True)
            shutil.copy2(node_source, node_root / node_source.name)
            git_source_root = (
                git_source.parent.parent if git_source.parent.name.casefold() == "cmd" else git_source.parent
            )
            shutil.copytree(git_source_root, git_root)
            self._node_git = (
                node_root,
                git_root,
                node_root / node_source.name,
                git_root / git_source.relative_to(git_source_root),
            )
        return self._node_git

    def grant(self, path: Path, sid: str) -> None:
        granted = self._granted.setdefault(sid, set())
        if path not in granted:
            _grant_test_access(path, sid, "RX", self.root)
            granted.add(path)

    def revoke_all(self) -> None:
        if not (self._granted and self.root.exists()):
            return
        failures = []
        for sid in self._granted:
            try:
                _revoke_test_access(self.root, sid, self.root)
            except AssertionError as exc:
                failures.append(f"{sid}: {exc}")
        assert not failures, f"shared toolchain ACL revocation failed: {failures}"


@pytest.fixture(scope="session")
def shared_toolchains(tmp_path_factory: pytest.TempPathFactory, pytestconfig: pytest.Config):
    root = tmp_path_factory.mktemp("shared-toolchains").resolve()
    _assert_inside_worktree(root, Path(pytestconfig.rootpath).resolve())
    toolchains = _SharedToolchains(root)
    yield toolchains
    toolchains.revoke_all()


@pytest.fixture
def native_python_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request,
    shared_toolchains: _SharedToolchains,
):
    repo_root = Path(request.config.rootpath).resolve()
    test_root = tmp_path.resolve()
    _assert_inside_worktree(test_root, repo_root)
    workspace = tmp_path / "workspace"
    private_temp = workspace / ".private-temp"
    workspace.mkdir()
    private_temp.mkdir()
    python_root = shared_toolchains.python()
    toolchain_roots = [python_root]
    node_executable = None
    git_executable = None
    if getattr(request, "param", None):
        node_root, git_root, node_executable, git_executable = shared_toolchains.node_and_git()
        toolchain_roots.extend((node_root, git_root))

    profile = new_native_execution_profile(
        workspace=workspace,
        working_directory=workspace,
        toolchain_roots=tuple(toolchain_roots),
        private_temp=private_temp,
        generation=1,
        appcontainer_name=getattr(request, "param", None),
        safe_environment=(
            ("GIT_CONFIG_NOSYSTEM", "1"),
            ("GIT_CONFIG_GLOBAL", str(workspace / ".t06-no-global-gitconfig")),
            ("GIT_TEMPLATE_DIR", str(workspace / ".t06-empty-git-template")),
        ),
    )
    sid_ptr = _derive_test_sid(profile.appcontainer_name)
    try:
        sid = _sid_to_text(sid_ptr)
    finally:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.FreeSid.argtypes = [ctypes.c_void_p]
        advapi.FreeSid.restype = ctypes.c_void_p
        advapi.FreeSid(sid_ptr)
    request.addfinalizer(lambda: _revoke_test_access(test_root, sid, test_root))
    _grant_test_access(workspace, sid, "M", test_root)
    for toolchain_root in toolchain_roots:
        shared_toolchains.grant(toolchain_root, sid)
    _grant_test_access(private_temp, sid, "M", test_root)

    monkeypatch.setenv("HERMES_T06_SYNTHETIC_PARENT_SECRET", "must-not-cross-boundary")
    return profile, python_root / "python.exe", workspace, node_executable, git_executable


@pytest.fixture(scope="session")
def ephemeral_appcontainer_profile(pytestconfig: pytest.Config):
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    create_profile = userenv.CreateAppContainerProfile
    create_profile.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    create_profile.restype = ctypes.c_long
    delete_profile = userenv.DeleteAppContainerProfile
    delete_profile.argtypes = [ctypes.c_wchar_p]
    delete_profile.restype = ctypes.c_long

    if not pytestconfig.getoption("--allow-t06-ephemeral-appcontainer-profile"):
        pytest.skip(
            "requires explicit approval: creates per-user AppContainer profile storage outside pytest basetemp"
        )
    assert pytestconfig.getoption("--t06-confirm-appcontainer-profile") == EPHEMERAL_PROFILE_NAME, (
        "profile creation requires exact confirmation of the fixed T06 profile name"
    )

    marker_path = _recovery_marker_path(pytestconfig)
    assert not marker_path.exists(), (
        f"recovery marker already exists; use a fresh H-drive --basetemp: {marker_path}"
    )
    user_sid = _current_user_sid()
    derived_sid = _derive_test_sid(EPHEMERAL_PROFILE_NAME)
    try:
        appcontainer_sid = _sid_to_text(derived_sid)
    finally:
        _free_sid(derived_sid)
    marker = {
        "profile_name": EPHEMERAL_PROFILE_NAME,
        "user_sid": user_sid,
        "appcontainer_sid": appcontainer_sid,
        "state": "creating",
    }
    marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")

    sid_ptr = ctypes.c_void_p()
    result = create_profile(
        EPHEMERAL_PROFILE_NAME,
        "Hermes T06 isolated test",
        "Ephemeral pytest profile for native delegation boundary verification",
        None,
        0,
        ctypes.byref(sid_ptr),
    )
    if result != 0:
        marker["state"] = "create-failed"
        marker["create_hresult"] = f"0x{result & 0xffffffff:08x}"
        marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        _free_sid(sid_ptr)
        raise AssertionError(
            f"CreateAppContainerProfile failed or the fixed name already exists: "
            f"0x{result & 0xffffffff:08x}; nothing was deleted"
        )
    try:
        marker["state"] = "created"
        marker["create_hresult"] = f"0x{result & 0xffffffff:08x}"
        marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        marker["local_appdata_path"] = _appcontainer_folder_path(appcontainer_sid)
        marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        yield EPHEMERAL_PROFILE_NAME
    finally:
        _free_sid(sid_ptr)
        # DeleteAppContainerProfile can leave storage behind if a child or
        # profile file handle is still open. The test closes owned processes
        # before fixture teardown; retry once as the API guidance recommends.
        result = delete_profile(EPHEMERAL_PROFILE_NAME)
        if result != 0:
            time.sleep(0.25)
            result = delete_profile(EPHEMERAL_PROFILE_NAME)
        marker["delete_hresult"] = f"0x{result & 0xffffffff:08x}"
        marker["state"] = "deleted" if result == 0 else "cleanup-failed"
        try:
            marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        except OSError:
            if result == 0:
                raise AssertionError(
                    "profile was deleted but recovery marker could not be updated; retain evidence for review"
                )
            raise
        assert result == 0, (
            f"ephemeral AppContainer profile cleanup failed: 0x{result & 0xffffffff:08x}; "
            "retain the diagnostic marker and request manual state review; no recovery cleanup switch exists"
        )


def _recovery_marker_path(pytestconfig: pytest.Config) -> Path:
    basetemp = pytestconfig.option.basetemp
    if not basetemp:
        raise AssertionError("profile experiment requires an explicit unique H-drive --basetemp")
    base_path = Path(basetemp).absolute()
    if not base_path.drive:
        raise AssertionError("--basetemp must be an absolute path on the test volume")
    repo_root = Path(pytestconfig.rootpath).resolve()
    resolved_base = base_path.resolve()
    assert resolved_base.drive.casefold() == repo_root.drive.casefold(), (
        "T06 basetemp and repository must be on the same volume"
    )
    assert resolved_base.is_relative_to(repo_root), (
        f"T06 basetemp must remain inside the isolated H worktree: {resolved_base}"
    )
    marker_path = base_path.with_name(base_path.name + ".t06-appcontainer-recovery.json")
    resolved_marker = marker_path.parent.resolve() / marker_path.name
    assert resolved_marker.drive.casefold() == repo_root.drive.casefold(), (
        "T06 recovery marker must remain on the isolated worktree volume"
    )
    assert resolved_marker.is_relative_to(repo_root), (
        f"T06 recovery marker must remain inside the isolated H worktree: {resolved_marker}"
    )
    assert not resolved_marker.is_relative_to(resolved_base), (
        "T06 recovery marker must remain outside pytest basetemp so recovery can use a fresh basetemp"
    )
    if resolved_marker.exists():
        assert not resolved_marker.is_symlink(), "refusing to follow a recovery marker symlink"
    return resolved_marker


def _free_sid(sid) -> None:
    if not sid:
        return
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.FreeSid.argtypes = [ctypes.c_void_p]
    advapi.FreeSid.restype = ctypes.c_void_p
    advapi.FreeSid(sid)


def _current_user_sid() -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi.OpenProcessToken.restype = ctypes.c_int
    advapi.GetTokenInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi.GetTokenInformation.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    token = ctypes.c_void_p()
    if not advapi.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = ctypes.c_uint32()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if not required.value:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi.GetTokenInformation(
            token, 1, buffer, required.value, ctypes.byref(required)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        return _sid_to_text(sid)
    finally:
        kernel32.CloseHandle(token)


def _appcontainer_folder_path(sid: str) -> str:
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    get_path = userenv.GetAppContainerFolderPath
    get_path.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_wchar_p)]
    get_path.restype = ctypes.c_long
    path = ctypes.c_wchar_p()
    result = get_path(sid, ctypes.byref(path))
    if result < 0:
        raise OSError(f"GetAppContainerFolderPath failed: 0x{result & 0xffffffff:08x}")
    try:
        return path.value
    finally:
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        ole32.CoTaskMemFree(ctypes.cast(path, ctypes.c_void_p))


def _derive_test_sid(name: str):
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    derive = userenv.DeriveAppContainerSidFromAppContainerName
    derive.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)]
    derive.restype = ctypes.c_long
    sid = ctypes.c_void_p()
    result = derive(name, ctypes.byref(sid))
    assert result >= 0, f"DeriveAppContainerSidFromAppContainerName failed: 0x{result & 0xffffffff:08x}"
    return sid


def _sid_to_text(sid) -> str:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    converted = ctypes.c_wchar_p()
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    advapi.ConvertSidToStringSidW.restype = ctypes.c_int
    assert advapi.ConvertSidToStringSidW(sid, ctypes.byref(converted))
    text = converted.value
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree(ctypes.cast(converted, ctypes.c_void_p))
    return text


def _grant_test_access(path: Path, sid: str, rights: str, pytest_tmp_root: Path) -> None:
    target = path.resolve()
    root = pytest_tmp_root.resolve()
    assert target.is_relative_to(root), (
        f"refusing to grant AppContainer ACL outside pytest tmp_path: {target}"
    )
    icacls = _trusted_icacls_executable()
    result = subprocess.run(
        [str(icacls), str(target), "/grant", f"*{sid}:(OI)(CI){rights}", "/T", "/C", "/Q"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"temporary test ACL grant failed: {result.stderr or result.stdout}"


def _revoke_test_access(path: Path, sid: str, pytest_tmp_root: Path) -> None:
    target = path.resolve()
    root = pytest_tmp_root.resolve()
    assert target.is_relative_to(root), (
        f"refusing to revoke AppContainer ACL outside pytest tmp_path: {target}"
    )
    icacls = _trusted_icacls_executable()
    result = subprocess.run(
        [str(icacls), str(target), "/remove:g", f"*{sid}", "/T", "/C", "/Q"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"temporary test ACL revocation failed: {result.stderr or result.stdout}"


def _trusted_icacls_executable() -> Path:
    if os.name != "nt":
        raise OSError("native T06 ACL operations require Windows")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_system_directory = kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.POINTER(ctypes.c_wchar), ctypes.c_uint32]
    get_system_directory.restype = ctypes.c_uint32
    system_directory_buffer = ctypes.create_unicode_buffer(32768)
    length = get_system_directory(system_directory_buffer, len(system_directory_buffer))
    if length == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    if length >= len(system_directory_buffer):
        raise OSError("GetSystemDirectoryW returned an oversized system directory")

    system_directory = Path(system_directory_buffer.value)
    if not system_directory.is_absolute() or system_directory.drive.startswith("\\\\"):
        raise OSError("GetSystemDirectoryW did not return an absolute local Windows system directory")
    try:
        resolved_directory = system_directory.resolve(strict=True)
        executable = (system_directory / "icacls.exe").resolve(strict=True)
    except OSError as exc:
        raise OSError("cannot resolve icacls.exe from the Windows system directory") from exc
    if (
        not resolved_directory.is_dir()
        or executable.parent != resolved_directory
        or executable.name.casefold() != "icacls.exe"
        or not executable.is_file()
    ):
        raise OSError("Windows system icacls.exe failed path and regular-file validation")
    return executable


@pytest.mark.windows_only
def test_unregistered_appcontainer_name_fails_closed(native_python_profile) -> None:
    profile, interpreter, workspace, *_ = native_python_profile
    with delegated_child_context("t06-native-no-profile"), bind_native_execution_profile(profile):
        with pytest.raises(NativeExecutionUnavailable, match="WinError 2"):
            launch_restricted([str(interpreter), "-S", "-c", "pass"], profile, cwd=workspace)


@pytest.mark.windows_only
@pytest.mark.parametrize("native_python_profile", [EPHEMERAL_PROFILE_NAME], indirect=True)
def test_delegated_python_runs_inside_the_native_boundary(
    ephemeral_appcontainer_profile,
    native_python_profile,
) -> None:
    profile, interpreter, workspace, *_ = native_python_profile
    code = (
        "import ctypes,json,os,sys;"
        "from ctypes import wintypes as w;"
        "k=ctypes.WinDLL('kernel32',use_last_error=True);"
        "a=ctypes.WinDLL('advapi32',use_last_error=True);"
        "k.GetCurrentProcess.restype=w.HANDLE;"
        "a.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)];"
        "a.OpenProcessToken.restype=w.BOOL;"
        "a.GetTokenInformation.argtypes=[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD)];"
        "a.GetTokenInformation.restype=w.BOOL;"
        "token=w.HANDLE(); needed=w.DWORD(); app=w.DWORD();"
        "assert a.OpenProcessToken(k.GetCurrentProcess(),8,ctypes.byref(token));"
        "assert a.GetTokenInformation(token,29,ctypes.byref(app),ctypes.sizeof(app),ctypes.byref(needed));"
        "k.CloseHandle(token);"
        "sys.stdout.write(json.dumps({'appcontainer':bool(app.value),'cwd':os.getcwd(),"
        "'secret':os.getenv('HERMES_T06_SYNTHETIC_PARENT_SECRET')}))"
    )

    with delegated_child_context("t06-native-positive"), bind_native_execution_profile(profile):
        with launch_restricted(
            [str(interpreter), "-S", "-c", code], profile, cwd=workspace
        ) as process:
            stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0
        result = json.loads(stdout)
        assert result["appcontainer"] is True, "child token must be a real AppContainer token"
        assert result["cwd"] == str(workspace)
        assert result["secret"] is None, "parent synthetic secret must not enter child environment"
        assert stderr in (None, "")


@pytest.mark.windows_only
@pytest.mark.parametrize("native_python_profile", [EPHEMERAL_PROFILE_NAME], indirect=True)
def test_node_can_do_useful_workspace_work(
    ephemeral_appcontainer_profile,
    native_python_profile,
) -> None:
    profile, _interpreter, workspace, node_exe, _git_exe = native_python_profile
    node_output = workspace / "node-result.json"
    # A script *file* makes Node realpath its main module from the drive root, and the
    # AppContainer cannot read attributes of the workspace's ancestors (EPERM on lstat 'C:\').
    node_code = (
        "const fs = require('fs'); "
        f"fs.writeFileSync({json.dumps(str(node_output))}, JSON.stringify({{ok: true}}));"
    )
    with delegated_child_context("t06-native-node-positive"), bind_native_execution_profile(profile):
        with launch_restricted([str(node_exe), "-e", node_code], profile, cwd=workspace) as process:
            stdout, _stderr = process.communicate(timeout=20)
    assert process.returncode == 0, stdout
    assert node_output.read_text(encoding="utf-8") == '{"ok":true}'
    assert stdout in (None, "")


@pytest.mark.windows_only
@pytest.mark.parametrize("native_python_profile", [EPHEMERAL_PROFILE_NAME], indirect=True)
def test_local_git_can_initialise_a_workspace_repository(
    ephemeral_appcontainer_profile,
    native_python_profile,
) -> None:
    profile, _interpreter, workspace, _node_exe, git_exe = native_python_profile
    repo = workspace / "git-sandbox"
    repo.mkdir()
    (workspace / ".t06-empty-git-template").mkdir()
    with delegated_child_context("t06-native-git-init"), bind_native_execution_profile(profile):
        with launch_restricted(
            [str(git_exe), "-C", str(repo), "init", "--quiet", "--template="],
            profile,
            cwd=workspace,
        ) as process:
            stdout, _stderr = process.communicate(timeout=20)
    if process.returncode != 0 and "could not open '/dev/null'" in (stdout or ""):
        pytest.xfail(
            "AppContainers are denied the NUL device and Git opens /dev/null at startup; "
            "granting it needs a privileged, system-wide device DACL change (microsoft/win32-app-isolation#73)"
        )
    assert process.returncode == 0, stdout
    assert (repo / ".git").is_dir(), "Git must initialize only the synthetic workspace repository"


@pytest.mark.windows_only
@pytest.mark.parametrize("native_python_profile", [EPHEMERAL_PROFILE_NAME], indirect=True)
def test_appcontainer_cannot_read_synthetic_secret_outside_workspace(
    ephemeral_appcontainer_profile,
    native_python_profile,
    tmp_path: Path,
) -> None:
    profile, interpreter, workspace, *_ = native_python_profile
    outside_secret = tmp_path / "synthetic-outside-secret.txt"
    outside_secret.write_text("T06-OUTSIDE-SYNTHETIC-SECRET", encoding="utf-8")
    code = (
        "import json,sys\n"
        "try:\n"
        f"    data=open({str(outside_secret)!r},encoding='utf-8').read()\n"
        "    result={'read':True,'value':data}\n"
        "except OSError as exc:\n"
        "    result={'read':False,'error':type(exc).__name__}\n"
        "sys.stdout.write(json.dumps(result))"
    )
    with delegated_child_context("t06-native-outside-secret"), bind_native_execution_profile(profile):
        with launch_restricted(
            [str(interpreter), "-S", "-c", code], profile, cwd=workspace
        ) as process:
            stdout, _stderr = process.communicate(timeout=20)
    assert process.returncode == 0
    result = json.loads(stdout)
    assert result["read"] is False, "AppContainer read a synthetic secret outside its workspace"
    assert "value" not in result


@pytest.mark.windows_only
@pytest.mark.parametrize("native_python_profile", [EPHEMERAL_PROFILE_NAME], indirect=True)
def test_appcontainer_cannot_duplicate_a_parent_process_file_handle(
    ephemeral_appcontainer_profile,
    native_python_profile,
    tmp_path: Path,
) -> None:
    profile, interpreter, workspace, *_ = native_python_profile
    synthetic_file = tmp_path / "parent-owned-synthetic-handle.txt"
    synthetic_file.write_text("T06-PARENT-HANDLE-SYNTHETIC", encoding="utf-8")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(_SecurityAttributesForTest),
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    security = _SecurityAttributesForTest(ctypes.sizeof(_SecurityAttributesForTest), None, True)
    parent_file_handle = kernel32.CreateFileW(
        str(synthetic_file), 0x80000000, 0x00000007, ctypes.byref(security), 3, 0x80, None
    )
    assert parent_file_handle not in (None, ctypes.c_void_p(-1).value)
    try:
        parent_pid = os.getpid()
        handle_value = int(parent_file_handle)
        code = f"""import ctypes, json, sys
k = ctypes.WinDLL('kernel32', use_last_error=True)
k.GetCurrentProcess.restype = ctypes.c_void_p
k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
k.OpenProcess.restype = ctypes.c_void_p
k.DuplicateHandle.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32,
                              ctypes.c_int, ctypes.c_uint32]
k.DuplicateHandle.restype = ctypes.c_int
k.CloseHandle.argtypes = [ctypes.c_void_p]
parent = k.OpenProcess(0x0040, 0, {parent_pid})
duplicated = False
if parent:
    target = ctypes.c_void_p()
    duplicated = bool(k.DuplicateHandle(parent, {handle_value}, k.GetCurrentProcess(),
                                         ctypes.byref(target), 0, 0, 2))
    if duplicated:
        k.CloseHandle(target)
    k.CloseHandle(parent)
sys.stdout.write(json.dumps({{'open_parent_for_dup': bool(parent), 'duplicated': duplicated}}))
"""
        with delegated_child_context("t06-native-parent-handle"), bind_native_execution_profile(profile):
            with launch_restricted(
                [str(interpreter), "-S", "-c", code], profile, cwd=workspace
            ) as process:
                stdout, _stderr = process.communicate(timeout=20)
        assert process.returncode == 0
        result = json.loads(stdout)
        assert result["duplicated"] is False, "AppContainer duplicated a parent process file handle"
    finally:
        kernel32.CloseHandle(parent_file_handle)


@pytest.mark.windows_only
@pytest.mark.parametrize("native_python_profile", [EPHEMERAL_PROFILE_NAME], indirect=True)
def test_appcontainer_denies_loopback_http_tcp_and_udp(
    ephemeral_appcontainer_profile,
    native_python_profile,
) -> None:
    profile, interpreter, workspace, *_ = native_python_profile
    udp_sink = socket(AF_INET, SOCK_DGRAM)
    udp_sink.bind(("127.0.0.1", 0))
    udp_sink.settimeout(0.4)
    http_hits: list[bool] = []

    class SinkHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            http_hits.append(True)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"synthetic-loopback")

        def log_message(self, fmt, *args):
            return

    http_sink = HTTPServer(("127.0.0.1", 0), SinkHandler)
    server_thread = threading.Thread(target=http_sink.serve_forever, daemon=True)
    server_thread.start()
    tcp_port = http_sink.server_port
    udp_port = udp_sink.getsockname()[1]
    code = f"""import json, socket, sys, urllib.request
results = {{}}
try:
    socket.create_connection(('127.0.0.1', {tcp_port}), timeout=1)
    results['tcp'] = 'connected'
except OSError:
    results['tcp'] = 'denied'
try:
    urllib.request.urlopen('http://127.0.0.1:{tcp_port}/', timeout=1)
    results['http'] = 'connected'
except Exception:
    results['http'] = 'denied'
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.sendto(b'T06-DNS-SYNTHETIC', ('127.0.0.1', {udp_port}))
    results['udp'] = 'sent'
except OSError:
    results['udp'] = 'denied'
sys.stdout.write(json.dumps(results))
"""
    # The DNS payload is synthetic and targets only the local UDP sink; no
    # external resolver or internet endpoint is touched.
    dns_message = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x03t06\x07invalid\x00\x00\x01\x00\x01"
    code = code.replace("b'T06-DNS-SYNTHETIC'", repr(dns_message))
    try:
        with delegated_child_context("t06-native-network-denial"), bind_native_execution_profile(profile):
            with launch_restricted([str(interpreter), "-S", "-c", code], profile, cwd=workspace) as process:
                stdout, _ = process.communicate(timeout=15)
        assert process.returncode == 0, stdout
        results = json.loads(stdout)
        assert results["tcp"] == "denied" and results["http"] == "denied", results
        # WFP may drop an AppContainer datagram silently, so sendto can report success;
        # the boundary is that nothing reaches the sink.
        assert results["udp"] in ("sent", "denied"), results
        with pytest.raises(TimeoutError):
            udp_sink.recvfrom(2048)
        assert not http_hits, "AppContainer reached the synthetic loopback HTTP sink"
    finally:
        http_sink.shutdown()
        http_sink.server_close()
        server_thread.join(timeout=2)
        udp_sink.close()


def _open_for_wait(pid: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION; held open so the PID cannot be reused.
    handle = kernel32.OpenProcess(0x00100000 | 0x00001000, 0, pid)
    assert handle, f"cannot open process {pid}: WinError {ctypes.get_last_error()}"
    return handle


def _exited_within(handle, seconds: float) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    return kernel32.WaitForSingleObject(handle, int(seconds * 1000)) == 0


def _close_handle(handle) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle(handle)


@pytest.mark.windows_only
@pytest.mark.parametrize("cancel", ["kill_tree", "close"])
@pytest.mark.parametrize("native_python_profile", [EPHEMERAL_PROFILE_NAME], indirect=True)
def test_cancellation_stops_the_owned_descendants_and_nothing_else(
    ephemeral_appcontainer_profile,
    native_python_profile,
    cancel: str,
) -> None:
    profile, interpreter, workspace, *_ = native_python_profile
    # Pipes rather than DEVNULL: the AppContainer is denied the NUL device.
    code = (
        "import subprocess,sys,time\n"
        "g=subprocess.Popen([sys.executable,'-S','-c','import time; time.sleep(120)'],"
        "stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)\n"
        "sys.stdout.write(f'{g.pid}\\n'); sys.stdout.flush()\n"
        "time.sleep(120)\n"
    )
    # A process the host owns outside the delegated job: cancellation must leave it running.
    bystander = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    handles = []
    try:
        with delegated_child_context("t06-native-cancel"), bind_native_execution_profile(profile):
            process = launch_restricted([str(interpreter), "-S", "-c", code], profile, cwd=workspace)
            try:
                line: list[str] = []
                reader = threading.Thread(target=lambda: line.append(process.stdout.readline()), daemon=True)
                reader.start()
                reader.join(20)
                if not (line and line[0].strip().isdigit()):
                    process.kill_tree()
                    reader.join(5)
                    rest, _ = process.communicate(timeout=20)
                    pytest.fail(f"delegated child never reported its descendant: {''.join(line)}{rest}")
                child = _open_for_wait(process.pid)
                grandchild = _open_for_wait(int(line[0]))
                handles.extend((child, grandchild))
                assert not _exited_within(grandchild, 0), "descendant exited before cancellation"
                if cancel == "kill_tree":
                    process.kill_tree()
                    assert _exited_within(child, 10) and _exited_within(grandchild, 10)
            finally:
                process.close()
        assert _exited_within(child, 10), "cancelled delegated child is still running"
        assert _exited_within(grandchild, 10), "descendant outlived the cancelled delegated job"
        assert process.returncode is not None and process.returncode != 0
        assert bystander.poll() is None, "cancellation stopped a process outside the delegated job"
    finally:
        for handle in handles:
            _close_handle(handle)
        bystander.kill()
        bystander.wait(10)
