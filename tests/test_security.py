from __future__ import annotations

import io
import os
import wave
from urllib.error import HTTPError

import pytest

from jarvis_app.app_config import DEFAULT_SETTINGS, MAX_CLOUD_TEXT_CHARS
from jarvis_app.cloud_text import CloudTextClient
from jarvis_app.env_loader import load_project_env
from jarvis_app.local_speech import LocalTextToSpeech, generate_elevenlabs_wav
from jarvis_app.openai_config import get_openai_api_key, openai_key_status, sanitize_openai_error, set_openai_api_key
from jarvis_app.security import ApprovalLevel, SecurityManager, SecurityViolation
from jarvis_app.storage import JsonStore, redact_sensitive_text


def test_cloud_audio_payload_is_rejected() -> None:
    security = SecurityManager({"allow_cloud_text_ai": True})
    with pytest.raises(SecurityViolation):
        security.assert_cloud_text_allowed({"prompt": "hello", "context": {"jarvis_invoked": True}, "audio": "voice.wav"})


def test_binary_cloud_payload_is_rejected() -> None:
    security = SecurityManager({"allow_cloud_text_ai": True})
    with pytest.raises(SecurityViolation):
        security.assert_cloud_text_allowed({"prompt": b"raw audio bytes", "context": {"jarvis_invoked": True}})


def test_shell_action_requires_confirmation() -> None:
    security = SecurityManager({})
    policy = security.assert_action_allowed("automation.shell")
    assert policy.approval is ApprovalLevel.CONFIRM


def test_notepad_text_action_is_auto_allowed() -> None:
    security = SecurityManager({})
    policy = security.assert_action_allowed("desktop.open_notepad_text")
    assert policy.approval is ApprovalLevel.AUTO


def test_cloud_text_requires_jarvis_metadata() -> None:
    security = SecurityManager({"allow_cloud_text_ai": True, "cloud_text_requires_jarvis": True})
    with pytest.raises(SecurityViolation):
        security.assert_cloud_text_allowed({"prompt": "hello", "context": {"jarvis_invoked": False}})


def test_cloud_text_accepts_jarvis_metadata() -> None:
    security = SecurityManager({"allow_cloud_text_ai": True, "cloud_text_requires_jarvis": True})
    security.assert_cloud_text_allowed({"prompt": "hello", "context": {"jarvis_invoked": True}})


def test_cloud_text_rejects_oversized_prompt() -> None:
    security = SecurityManager({"allow_cloud_text_ai": True, "cloud_text_requires_jarvis": True})
    client = CloudTextClient(security)
    with pytest.raises(SecurityViolation):
        client.answer("x" * (MAX_CLOUD_TEXT_CHARS + 1), {"jarvis_invoked": True})


def test_cloud_tts_defaults_to_opt_in() -> None:
    assert DEFAULT_SETTINGS["allow_cloud_tts"] is False
    assert DEFAULT_SETTINGS["tts_provider"] == "elevenlabs"


def test_history_redacts_secret_like_text(tmp_path) -> None:
    store = JsonStore(tmp_path)
    store.append_history("user", "api_key=sk-thisisasecret1234567890")
    history = store.load_collection("history")
    assert "[REDACTED]" in history[-1]["text"]
    assert "sk-thisisasecret" not in history[-1]["text"]


def test_history_is_bounded(tmp_path) -> None:
    store = JsonStore(tmp_path)
    store.settings["max_history_items"] = 2
    store.append_history("user", "one")
    store.append_history("assistant", "two")
    store.append_history("user", "three")
    history = store.load_collection("history")
    assert [item["text"] for item in history] == ["two", "three"]


def test_redact_sensitive_text() -> None:
    assert redact_sensitive_text("password: hunter2") == "password=[REDACTED]"
    assert redact_sensitive_text("Incorrect API key sk-proj-************zKEA") == "Incorrect API key [REDACTED]"


def test_openai_error_sanitizes_api_key_fragments() -> None:
    error = "Incorrect API key provided: sk-proj-abc123zKEA. invalid_api_key 401"
    sanitized = sanitize_openai_error(RuntimeError(error))
    assert "sk-proj" not in sanitized
    assert "zKEA" not in sanitized
    assert "OpenAI rejected the configured API key" in sanitized


def test_local_openai_secret_preferred_over_environment(tmp_path, monkeypatch) -> None:
    store = JsonStore(tmp_path)
    set_openai_api_key(store, "  Bearer sk-local1234567890  ")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env1234567890")

    assert get_openai_api_key(store) == "sk-local1234567890"
    status, detail = openai_key_status(store)
    assert status == "OK"
    assert "DPAPI-encrypted" in detail
    assert "sk-local" not in detail


def test_project_env_loads_values_without_overriding_process_environment(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# local test\nJARVIS_TEST_NEW='from file'\nexport JARVIS_TEST_EXISTING=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("JARVIS_TEST_NEW", raising=False)
    monkeypatch.setenv("JARVIS_TEST_EXISTING", "from-process")

    assert load_project_env(env_file) == 1
    assert os.environ["JARVIS_TEST_NEW"] == "from file"
    assert os.environ["JARVIS_TEST_EXISTING"] == "from-process"


def test_elevenlabs_audio_request_is_wrapped_as_wav(monkeypatch) -> None:
    captured = {}
    pcm_audio = b"\x01\x00\x02\x00"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return pcm_audio

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-123")
    monkeypatch.setattr("jarvis_app.local_speech.urlopen", fake_urlopen)

    audio = generate_elevenlabs_wav(
        "Voice test",
        {"elevenlabs_tts_model": "eleven_multilingual_v2", "elevenlabs_tts_output_format": "pcm_24000"},
    )

    request = captured["request"]
    assert request.full_url.endswith("/voice-123?output_format=pcm_24000")
    assert request.get_header("Xi-api-key") == "test-elevenlabs-key"
    with wave.open(io.BytesIO(audio), "rb") as wav_file:
        assert wav_file.getframerate() == 24_000
        assert wav_file.getnchannels() == 1
        assert wav_file.readframes(2) == pcm_audio


def test_elevenlabs_http_error_includes_safe_provider_detail(monkeypatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-123")

    def fake_urlopen(request, timeout):
        body = io.BytesIO(b'{"detail":{"status":"quota_exceeded","message":"Account has no available credits"}}')
        raise HTTPError(request.full_url, 402, "Payment Required", {}, body)

    monkeypatch.setattr("jarvis_app.local_speech.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="HTTP 402.*no available credits"):
        generate_elevenlabs_wav("Voice test", {"elevenlabs_tts_output_format": "pcm_24000"})


def test_tts_failure_is_saved_and_reported_without_secrets() -> None:
    statuses: list[str] = []
    tts = object.__new__(LocalTextToSpeech)
    tts.settings = {}
    tts.settings_saver = None
    tts.status_callback = statuses.append

    tts._report_cloud_tts_error("ElevenLabs", "api_key=secret-value quota exceeded")

    assert "secret-value" not in tts.settings["tts_last_error"]
    assert "quota exceeded" in tts.settings["tts_last_error"]
    assert statuses == [tts.settings["tts_last_error"]]
