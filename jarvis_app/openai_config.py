from __future__ import annotations

import os
import re
from typing import Any

from .storage import JsonStore, SecretStore


OPENAI_KEY_HELP = (
    "OpenAI rejected the configured API key. Create a fresh API key at "
    "https://platform.openai.com/api-keys, then run: jarvis --set-openai-key"
)

OPENAI_SECRET_NAME = "openai_api_key"


def normalize_openai_api_key(raw: str) -> str:
    key = raw.strip().strip('"').strip("'").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def get_openai_api_key(store: JsonStore | None = None) -> str:
    if store is not None:
        secret = SecretStore(store).get_secret(OPENAI_SECRET_NAME)
        if secret:
            return normalize_openai_api_key(secret)
    raw = os.environ.get("OPENAI_API_KEY", "")
    return normalize_openai_api_key(raw)


def set_openai_api_key(store: JsonStore, raw: str) -> None:
    key = normalize_openai_api_key(raw)
    if not key:
        raise ValueError("OpenAI API key cannot be empty.")
    SecretStore(store).set_secret(OPENAI_SECRET_NAME, key)


def clear_openai_api_key(store: JsonStore) -> bool:
    return SecretStore(store).delete_secret(OPENAI_SECRET_NAME)


def openai_key_status(store: JsonStore | None = None) -> tuple[str, str]:
    if store is not None:
        secret = SecretStore(store).get_secret(OPENAI_SECRET_NAME)
        if secret:
            key = normalize_openai_api_key(secret)
            if not key:
                return "WARN", "Local encrypted OpenAI key is present but empty after trimming."
            if not key.startswith("sk-"):
                return "WARN", "Local encrypted OpenAI key is present but does not look like an OpenAI API key."
            return "OK", "Local DPAPI-encrypted OpenAI key is configured in .jarvis_data/environment."

    raw = os.environ.get("OPENAI_API_KEY", "")
    if not raw:
        return "WARN", "No local OpenAI key is configured and OPENAI_API_KEY is not set."
    key = normalize_openai_api_key(raw)
    if not key:
        return "WARN", "OPENAI_API_KEY is set but empty after trimming whitespace and quotes."
    if key != raw:
        return "OK", "OPENAI_API_KEY is present; Jarvis will trim surrounding quotes, spaces, or a Bearer prefix."
    if not key.startswith("sk-"):
        return "WARN", "OPENAI_API_KEY is present but does not look like an OpenAI API key."
    return "OK", "OPENAI_API_KEY is present. The value was not displayed or stored."


def sanitize_openai_error(exc: Exception | Any) -> str:
    text = str(exc)
    text = re.sub(r"sk-[A-Za-z0-9_*.-]{8,}", "[REDACTED_OPENAI_API_KEY]", text)
    if "invalid_api_key" in text or "Incorrect API key" in text or "401" in text:
        return OPENAI_KEY_HELP
    return text
