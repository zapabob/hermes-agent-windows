"""Offline contract for the real optional Mistral SDK's audio interfaces."""

import base64
import io
import json

import httpx
import pytest

mistral = pytest.importorskip("mistralai.client", reason="optional Mistral SDK not installed")


def test_real_sdk_preserves_speech_and_transcription_interfaces():
    audio = b"offline-audio-fixture"
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/audio/speech"):
            payload = json.loads(request.content)
            assert payload["input"] == "Offline compatibility check"
            assert payload["response_format"] == "mp3"
            return httpx.Response(200, json={"audio_data": base64.b64encode(audio).decode()})
        if request.url.path.endswith("/audio/transcriptions"):
            assert b"fixture.wav" in request.content
            return httpx.Response(200, json={
                "text": "Offline transcription", "model": "offline-model",
                "usage": {"prompt_audio_seconds": 1}, "language": "en",
            })
        raise AssertionError(f"Unexpected SDK request: {request.method} {request.url.path}")

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        with mistral.Mistral(api_key="offline-test-key", client=transport) as client:
            speech = client.audio.speech.complete(
                model="offline-model",
                input="Offline compatibility check",
                voice_id="00000000-0000-4000-8000-000000000001",
                response_format="mp3",
            )
            transcription = client.audio.transcriptions.complete(
                model="offline-model",
                file={"content": io.BytesIO(audio), "file_name": "fixture.wav"},
            )

    assert base64.b64decode(speech.audio_data) == audio
    assert transcription.text == "Offline transcription"
    assert len(requests) == 2
