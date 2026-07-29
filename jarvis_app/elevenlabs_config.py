from __future__ import annotations

import os


def _env_value(name: str) -> str:
    return os.environ.get(name, "").strip().strip('"').strip("'").strip()


def get_elevenlabs_api_key() -> str:
    return _env_value("ELEVENLABS_API_KEY")


def get_elevenlabs_voice_id(settings: dict[str, object] | None = None) -> str:
    return _env_value("ELEVENLABS_VOICE_ID") or str((settings or {}).get("elevenlabs_voice_id", "")).strip()


def get_elevenlabs_model_id(settings: dict[str, object] | None = None) -> str:
    return _env_value("ELEVENLABS_MODEL_ID") or str(
        (settings or {}).get("elevenlabs_tts_model", "eleven_flash_v2_5")
    ).strip()


def elevenlabs_key_status(settings: dict[str, object] | None = None) -> tuple[str, str]:
    if not get_elevenlabs_api_key():
        return "WARN", "ELEVENLABS_API_KEY is not configured."
    if not get_elevenlabs_voice_id(settings):
        return "WARN", "ELEVENLABS_API_KEY is present, but ELEVENLABS_VOICE_ID is not configured."
    return "OK", "ElevenLabs API key and voice ID are present. Their values were not displayed or stored."
