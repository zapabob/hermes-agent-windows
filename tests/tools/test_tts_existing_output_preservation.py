"""Provider and delivery failures may only clean this attempt's artifacts."""

import json
import sys
from pathlib import Path

import pytest

from tools import tts_tool


@pytest.fixture
def local_tts(monkeypatch):
    monkeypatch.setattr(tts_tool, "_load_tts_config", lambda: {"provider": "piper"})
    monkeypatch.setattr(tts_tool, "_get_provider", lambda config: "piper")
    monkeypatch.setattr(tts_tool, "_resolve_command_provider_config", lambda *args: None)
    monkeypatch.setattr(tts_tool, "_resolve_max_text_length", lambda *args: 100)
    # Only the external synthesis boundary is replaced. Delivery/cleanup stay real.
    return tts_tool


@pytest.mark.parametrize("failure", ["error", "invalid_json", "empty_audio", "exception"])
def test_provider_failure_preserves_existing_audio(local_tts, tmp_path, monkeypatch, failure):
    destination = tmp_path / "利用者の音声.mp3"
    destination.write_bytes(b"ORIGINAL-OWNED-TEST-AUDIO")

    def synthesize(*, output_path, **kwargs):
        Path(output_path).write_bytes(b"" if failure == "empty_audio" else b"partial")
        if failure == "exception":
            raise RuntimeError("synthetic provider failure")
        if failure == "invalid_json":
            return "not json"
        return json.dumps({"success": failure == "empty_audio", "error": "synthetic failure", "file_path": output_path})

    monkeypatch.setattr(local_tts, "_text_to_speech_single", synthesize)
    result = json.loads(local_tts.text_to_speech_tool("hello", output_path=str(destination)))
    assert result["success"] is False
    assert destination.read_bytes() == b"ORIGINAL-OWNED-TEST-AUDIO"
    assert [path for path in tmp_path.iterdir() if path.is_file()] == [destination]


def test_success_publishes_new_audio_at_requested_path(local_tts, tmp_path, monkeypatch):
    destination = tmp_path / "audio.mp3"
    destination.write_bytes(b"original")

    def synthesize(*, output_path, **kwargs):
        Path(output_path).write_bytes(b"GENERATED-TEST-AUDIO")
        return json.dumps({"success": True, "file_path": output_path, "provider": "piper"})

    monkeypatch.setattr(local_tts, "_text_to_speech_single", synthesize)
    result = json.loads(local_tts.text_to_speech_tool("hello", output_path=str(destination)))
    assert result["success"] is True
    assert Path(result["file_path"]) == destination
    assert destination.read_bytes() == b"GENERATED-TEST-AUDIO"
    assert [path for path in tmp_path.iterdir() if path.is_file()] == [destination]


def test_delivery_failure_preserves_existing_audio(local_tts, tmp_path, monkeypatch):
    destination = tmp_path / "audio.mp3"
    destination.write_bytes(b"original")

    def synthesize(*, output_path, **kwargs):
        Path(output_path).write_bytes(b"GENERATED-TEST-AUDIO")
        return json.dumps({"success": True, "file_path": output_path})

    def fail_delivery(*args, **kwargs):
        raise ValueError("synthetic delivery failure")

    monkeypatch.setattr(local_tts, "_text_to_speech_single", synthesize)
    monkeypatch.setattr(local_tts, "_build_audio_delivery_files", fail_delivery)
    result = json.loads(local_tts.text_to_speech_tool("hello", output_path=str(destination)))
    assert result["success"] is False
    assert destination.read_bytes() == b"original"
    assert [path for path in tmp_path.iterdir() if path.is_file()] == [destination]


@pytest.mark.parametrize("had_originals", [True, False])
def test_partial_multipart_publish_rolls_back_all_outputs(local_tts, tmp_path, monkeypatch, had_originals):
    base = tmp_path / "audio.mp3"
    destinations = [tmp_path / f"audio.part{i:02}.mp3" for i in (1, 2)]
    chunks = [tmp_path / f".owned-chunk{i}.mp3" for i in (1, 2)]
    for index, chunk in enumerate(chunks):
        chunk.write_bytes(f"generated-{index}".encode())
    if had_originals:
        for index, destination in enumerate(destinations):
            destination.write_bytes(f"original-{index}".encode())
    monkeypatch.setattr(local_tts, "_pack_audio_files_for_delivery", lambda paths, profile: [[p] for p in paths])
    replace = local_tts.os.replace

    def fail_second_publish(source, destination):
        if Path(source) == chunks[1] and Path(destination) == destinations[1]:
            raise PermissionError("owned second-output sharing failure")
        return replace(source, destination)

    monkeypatch.setattr(local_tts.os, "replace", fail_second_publish)
    profile = local_tts.AudioDeliveryProfile(platform="owned", max_file_bytes=100)
    with pytest.raises(PermissionError):
        local_tts._build_audio_delivery_files([str(p) for p in chunks], str(base), profile)
    for index, destination in enumerate(destinations):
        if had_originals:
            assert destination.read_bytes() == f"original-{index}".encode()
        else:
            assert not destination.exists()
    assert not list(tmp_path.glob("*.rollback*"))


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows multipart sharing contract")
def test_native_locked_second_original_restores_first_original(local_tts, tmp_path, monkeypatch):
    import ctypes
    from ctypes import wintypes

    outputs = [tmp_path / f"audio.part{i:02}.mp3" for i in (1, 2)]
    chunks = [tmp_path / f"owned-chunk{i}.mp3" for i in (1, 2)]
    for index, output in enumerate(outputs):
        output.write_bytes(f"original-{index}".encode())
        chunks[index].write_bytes(f"new-{index}".encode())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(outputs[1]), 0x80000000, 3, None, 3, 0, None)
    assert handle != wintypes.HANDLE(-1).value
    monkeypatch.setattr(local_tts, "_pack_audio_files_for_delivery", lambda paths, profile: [[p] for p in paths])
    try:
        with pytest.raises(PermissionError):
            local_tts._build_audio_delivery_files(
                [str(p) for p in chunks], str(tmp_path / "audio.mp3"),
                local_tts.AudioDeliveryProfile(platform="owned", max_file_bytes=100),
            )
        assert [p.read_bytes() for p in outputs] == [b"original-0", b"original-1"]
    finally:
        assert kernel.CloseHandle(handle)
    assert not list(tmp_path.glob("*.rollback*"))


def test_failed_rollback_retains_original_backup(local_tts, tmp_path, monkeypatch):
    output = tmp_path / "audio.mp3"
    output.write_bytes(b"original")
    chunk = tmp_path / "owned.mp3"
    chunk.write_bytes(b"new")
    replace = local_tts.os.replace

    def fail_publish_and_rollback(source, destination):
        if Path(destination) == output:
            raise PermissionError("owned publication and rollback failure")
        return replace(source, destination)

    monkeypatch.setattr(local_tts.os, "replace", fail_publish_and_rollback)
    with pytest.raises(RuntimeError, match="retained recovery files"):
        local_tts._build_audio_delivery_files(
            [str(chunk)], str(output), local_tts.AudioDeliveryProfile(platform="owned", max_file_bytes=100),
        )
    backups = list(tmp_path.glob("*.rollback"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"original"


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows sharing contract")
def test_locked_publish_preserves_original_and_cleans_attempt(local_tts, tmp_path, monkeypatch):
    import ctypes
    from ctypes import wintypes

    destination = tmp_path / "locked.mp3"
    destination.write_bytes(b"original")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(destination), 0x80000000, 3, None, 3, 0, None)
    assert handle != wintypes.HANDLE(-1).value

    def synthesize(*, output_path, **kwargs):
        Path(output_path).write_bytes(b"generated")
        return json.dumps({"success": True, "file_path": output_path})

    monkeypatch.setattr(local_tts, "_text_to_speech_single", synthesize)
    try:
        result = json.loads(local_tts.text_to_speech_tool("hello", output_path=str(destination)))
        assert result["success"] is False
        assert destination.read_bytes() == b"original"
    finally:
        assert kernel.CloseHandle(handle)
    assert [path for path in tmp_path.iterdir() if path.is_file()] == [destination]
