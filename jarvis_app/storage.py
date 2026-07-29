from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import win32crypt

from .app_config import DEFAULT_DATA_DIR, DEFAULT_SETTINGS


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?([^\s'\";,]+)"),
    re.compile(r"\bsk-[A-Za-z0-9_*.-]{8,}\b"),
)


def redact_sensitive_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            redacted = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class JsonStore:
    def __init__(self, base_dir: Path | str = DEFAULT_DATA_DIR) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "notes").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "tts_cache").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "environment").mkdir(parents=True, exist_ok=True)
        self.settings = self._load_json("settings.json", DEFAULT_SETTINGS)
        changed = False
        enabling_jarvis_gated_text_ai = "cloud_text_requires_jarvis" not in self.settings
        hardening_cloud_tts = "security_audit_2026_07_cloud_tts_opt_in" not in self.settings
        redacting_existing_history = "security_audit_2026_07_history_redacted" not in self.settings
        redacting_masked_openai_errors = "security_audit_2026_07_openai_error_redacted" not in self.settings
        updating_openai_voice_profile = "voice_profile_openai_british_male_2026_07" not in self.settings
        for key, value in DEFAULT_SETTINGS.items():
            if key not in self.settings:
                self.settings[key] = value
                changed = True
        if self.base_dir.resolve() != DEFAULT_DATA_DIR.resolve():
            for setting_name, folder_name in (
                ("notes_folder", "notes"),
                ("screenshots_folder", "screenshots"),
                ("tts_cache_folder", "tts_cache"),
                ("vosk_model_path", "vosk-model-small-en-us-0.15"),
            ):
                if str(self.settings.get(setting_name, "")) == str(DEFAULT_SETTINGS[setting_name]):
                    self.settings[setting_name] = str(self.base_dir / folder_name)
                    changed = True
        if enabling_jarvis_gated_text_ai:
            self.settings["allow_cloud_text_ai"] = True
            self.settings["cloud_text_requires_jarvis"] = True
            changed = True
        if hardening_cloud_tts:
            self.settings["allow_cloud_tts"] = False
            self.settings["security_audit_2026_07_cloud_tts_opt_in"] = True
            changed = True
        if self.settings.get("cloud_audio_allowed") is not False:
            self.settings["cloud_audio_allowed"] = False
            changed = True
        if redacting_existing_history:
            self._redact_existing_history()
            self.settings["security_audit_2026_07_history_redacted"] = True
            changed = True
        if redacting_masked_openai_errors:
            self._redact_existing_history()
            self.settings["security_audit_2026_07_openai_error_redacted"] = True
            changed = True
        if updating_openai_voice_profile:
            self.settings["openai_tts_voice"] = "cedar"
            self.settings["openai_tts_instructions"] = DEFAULT_SETTINGS["openai_tts_instructions"]
            self.settings["voice_profile_openai_british_male_2026_07"] = True
            changed = True
        if changed:
            self.save_settings()

    def _path(self, name: str) -> Path:
        return self.base_dir / name

    def _load_json(self, name: str, default: Any) -> Any:
        path = self._path(name)
        if not path.exists():
            self._write_json(name, default)
            return json.loads(json.dumps(default))
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = path.with_suffix(path.suffix + ".corrupt")
            path.replace(backup)
            self._write_json(name, default)
            return json.loads(json.dumps(default))

    def _write_json(self, name: str, value: Any) -> None:
        path = self._path(name)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def save_settings(self) -> None:
        self.settings["cloud_audio_allowed"] = False
        self._write_json("settings.json", self.settings)

    def load_collection(self, name: str) -> list[dict[str, Any]]:
        return self._load_json(f"{name}.json", [])

    def save_collection(self, name: str, items: list[dict[str, Any]]) -> None:
        self._write_json(f"{name}.json", items)

    def append_collection(self, name: str, item: dict[str, Any]) -> dict[str, Any]:
        items = self.load_collection(name)
        items.append(item)
        self.save_collection(name, items)
        return item

    def append_history(self, role: str, text: str) -> None:
        if not self.settings.get("store_history", True):
            return
        max_text = int(self.settings.get("max_history_text_chars", 4000))
        max_items = int(self.settings.get("max_history_items", 500))
        clean_text = redact_sensitive_text(text)[:max_text]
        items = self.load_collection("history")
        items.append({"role": role, "text": clean_text, "created_at": utc_now_iso()})
        self.save_collection("history", items[-max_items:])

    def _redact_existing_history(self) -> None:
        path = self._path("history.json")
        if not path.exists():
            return
        items = self.load_collection("history")
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                item["text"] = redact_sensitive_text(item["text"])
        self.save_collection("history", items)


class SecretStore:
    """Stores secrets encrypted with Windows DPAPI."""

    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self._secrets_file = "environment/secrets.json"

    def set_secret(self, name: str, value: str) -> None:
        encrypted = win32crypt.CryptProtectData(value.encode("utf-8"), None, None, None, None, 0)
        secrets = self.store._load_json(self._secrets_file, {})
        secrets[name] = base64.b64encode(encrypted).decode("ascii")
        self.store._write_json(self._secrets_file, secrets)

    def get_secret(self, name: str) -> str | None:
        secrets = self.store._load_json(self._secrets_file, {})
        encoded = secrets.get(name)
        if not encoded:
            return None
        encrypted = base64.b64decode(encoded)
        _description, plaintext = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
        return plaintext.decode("utf-8")

    def delete_secret(self, name: str) -> bool:
        secrets = self.store._load_json(self._secrets_file, {})
        if name not in secrets:
            return False
        del secrets[name]
        self.store._write_json(self._secrets_file, secrets)
        return True
