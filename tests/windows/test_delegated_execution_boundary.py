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


@pytest.fixture
def native_python_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    repo_root = Path(request.config.rootpath).resolve()
    test_root = tmp_path.resolve()
    assert test_root.drive.casefold() == repo_root.drive.casefold(), (
        "native T06 probe basetemp must share the isolated worktree volume"
    )
    assert test_root.is_relative_to(repo_root), (
        f"native T06 probe files must remain inside pytest tmp_path: {test_root}"
    )
    workspace = tmp_path / "workspace"
    toolchains = tmp_path / "toolchains"
    python_root = toolchains / "python"
    private_temp = workspace / ".private-temp"
    workspace.mkdir()
    toolchains.mkdir()
    python_root.mkdir()
    private_temp.mkdir()
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
    toolchain_roots = [python_root]
    node_executable = None
    git_executable = None
    if getattr(request, "param", None):
        node_location = shutil.which("node.exe")
        git_location = shutil.which("git.exe")
        if not node_location or not git_location:
            pytest.skip("native Node.js and Git executables are required for the T06 positive probes")
        node_source = Path(node_location).resolve(strict=True)
        git_source = Path(git_location).resolve(strict=True)
        node_root = toolchains / "node"
        git_root = toolchains / "git"
        node_root.mkdir()
        shutil.copy2(node_source, node_root / node_source.name)
        git_source_root = (
            git_source.parent.parent if git_source.parent.name.casefold() == "cmd" else git_source.parent
        )
        shutil.copytree(git_source_root, git_root)
        git_executable = git_root / git_source.relative_to(git_source_root)
        node_executable = node_root / node_source.name
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
    _grant_test_access(workspace, sid, "M", test_root)
    _grant_test_access(python_root, sid, "RX", test_root)
    if getattr(request, "param", None):
        _grant_test_access(node_root, sid, "RX", test_root)
        _grant_test_access(git_root, sid, "RX", test_root)
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

    if pytestconfig.getoption("--cleanup-t06-ephemeral-appcontainer-profile"):
        assert pytestconfig.getoption("--t06-confirm-appcontainer-profile") == EPHEMERAL_PROFILE_NAME, (
            "cleanup requires exact confirmation of the fixed T06 profile name"
        )
        marker_path = _recovery_marker_path(pytestconfig)
        assert marker_path.is_file(), f"recovery marker not found: {marker_path}"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        assert marker.get("state") in {"created", "cleanup-failed"}, (
            "recovery marker does not prove this test invocation created the profile"
        )
        assert marker.get("profile_name") == EPHEMERAL_PROFILE_NAME
        assert marker.get("user_sid") == _current_user_sid(), (
            "profile belongs to a different Windows user"
        )
        derived_sid = _derive_test_sid(EPHEMERAL_PROFILE_NAME)
        try:
            assert marker.get("appcontainer_sid") == _sid_to_text(derived_sid)
        finally:
            _free_sid(derived_sid)
        result = delete_profile(EPHEMERAL_PROFILE_NAME)
        if result != 0:
            time.sleep(0.25)
            result = delete_profile(EPHEMERAL_PROFILE_NAME)
        assert result == 0, (
            f"DeleteAppContainerProfile cleanup failed: 0x{result & 0xffffffff:08x}; "
            "profile state is undetermined, retain the marker and request manual review"
        )
        marker["state"] = "deleted"
        marker["delete_hresult"] = f"0x{result & 0xffffffff:08x}"
        marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        pytest.skip("interrupted-run cleanup completed; no process probe requested")
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
            "retain the recovery marker and rerun the explicitly approved cleanup gate"
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
    configured_marker = pytestconfig.getoption("--t06-appcontainer-recovery-marker")
    marker_path = (
        Path(configured_marker).absolute()
        if configured_marker
        else base_path.with_name(base_path.name + ".t06-appcontainer-recovery.json")
    )
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
    icacls = Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe"
    result = subprocess.run(
        [str(icacls), str(target), "/grant", f"*{sid}:(OI)(CI){rights}", "/T", "/C", "/Q"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"temporary test ACL grant failed: {result.stderr or result.stdout}"


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
def test_node_and_local_git_can_do_useful_workspace_work(
    ephemeral_appcontainer_profile,
    native_python_profile,
) -> None:
    profile, _interpreter, workspace, node_exe, git_exe = native_python_profile
    node_output = workspace / "node-result.json"
    node_script = workspace / "write-result.js"
    node_script.write_text(
        "const fs = require('fs'); "
        f"fs.writeFileSync({json.dumps(str(node_output))}, JSON.stringify({{ok: true}}));",
        encoding="utf-8",
    )
    with delegated_child_context("t06-native-node-positive"), bind_native_execution_profile(profile):
        with launch_restricted([str(node_exe), str(node_script)], profile, cwd=workspace) as process:
            stdout, stderr = process.communicate(timeout=20)
    assert process.returncode == 0, stderr
    assert node_output.read_text(encoding="utf-8") == '{"ok":true}'
    assert stdout in (None, "")

    repo = workspace / "git-sandbox"
    repo.mkdir()
    (workspace / ".t06-empty-git-template").mkdir()
    with delegated_child_context("t06-native-git-init"), bind_native_execution_profile(profile):
        with launch_restricted(
            [str(git_exe), "-C", str(repo), "init", "--quiet", "--template="],
            profile,
            cwd=workspace,
        ) as process:
            _stdout, stderr = process.communicate(timeout=20)
    assert process.returncode == 0, stderr
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
        assert process.returncode == 0
        results = json.loads(stdout)
        assert results == {"tcp": "denied", "http": "denied", "udp": "denied"}
        with pytest.raises(TimeoutError):
            udp_sink.recvfrom(2048)
        assert not http_hits, "AppContainer reached the synthetic loopback HTTP sink"
    finally:
        http_sink.shutdown()
        http_sink.server_close()
        server_thread.join(timeout=2)
        udp_sink.close()
