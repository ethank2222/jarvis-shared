from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app_config import APP_VERSION, DEFAULT_DATA_DIR, WORKSPACE_ROOT
from .elevenlabs_config import elevenlabs_key_status
from .google_services import GoogleServices
from .openai_config import openai_key_status
from .storage import JsonStore


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    detail: str
    remediation: str = ""


def build_health_checks(store: JsonStore | None = None) -> list[HealthCheck]:
    store = store or JsonStore()
    settings = store.settings
    checks: list[HealthCheck] = [
        _python_check(),
        _data_dir_check(store.base_dir),
        _launcher_file_check(),
        _launcher_path_check(),
        _module_check("pywin32", "win32com", "Windows SAPI voice and recognition support"),
        _module_check("pythoncom", "pythoncom", "Windows COM event loop support"),
        _module_check("Pillow", "PIL", "Screenshot capture support"),
        _module_check("CustomTkinter", "customtkinter", "Futuristic desktop HUD support"),
        _speech_package_check(settings),
        _vosk_model_check(settings),
        _openai_key_check(settings, store),
        _google_check(store),
        _cloud_audio_check(settings),
        _ocr_check(settings),
        _approved_folders_check(settings),
        _tts_check(settings),
    ]
    return checks


def render_health_report(checks: list[HealthCheck]) -> str:
    counts = {status: sum(1 for check in checks if check.status == status) for status in ("OK", "WARN", "FAIL")}
    lines = [
        f"Private Jarvis {APP_VERSION} health report",
        f"Summary: {counts['OK']} OK, {counts['WARN']} warning(s), {counts['FAIL']} failure(s).",
        "",
    ]
    for check in checks:
        lines.append(f"[{check.status}] {check.name}: {check.detail}")
        if check.remediation:
            lines.append(f"  Fix: {check.remediation}")
    return "\n".join(lines)


def health_report(store: JsonStore | None = None) -> str:
    return render_health_report(build_health_checks(store))


def _python_check() -> HealthCheck:
    version = platform.python_version()
    if sys.version_info >= (3, 10):
        return HealthCheck("Python", "OK", f"{version} at {sys.executable}")
    return HealthCheck("Python", "FAIL", f"{version} is too old.", "Use Python 3.10 or newer.")


def _data_dir_check(base_dir: Path) -> HealthCheck:
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        for child in ("notes", "screenshots", "tts_cache"):
            (base_dir / child).mkdir(parents=True, exist_ok=True)
        return HealthCheck("Data folders", "OK", str(base_dir))
    except OSError as exc:
        return HealthCheck("Data folders", "FAIL", str(exc), "Set JARVIS_DATA_DIR to a writable local folder.")


def _launcher_file_check() -> HealthCheck:
    missing = [name for name in ("jarvis.cmd", "jarvis.bat", "run_jarvis.py") if not (WORKSPACE_ROOT / name).exists()]
    if not missing:
        return HealthCheck("Launcher files", "OK", str(WORKSPACE_ROOT))
    return HealthCheck("Launcher files", "FAIL", f"Missing: {', '.join(missing)}", "Run scripts/install_jarvis_command.ps1 from this workspace.")


def _launcher_path_check() -> HealthCheck:
    found = shutil.which("jarvis") or shutil.which("jarvis.cmd") or shutil.which("jarvis.bat")
    if found:
        return HealthCheck("Command launcher", "OK", found)
    return HealthCheck(
        "Command launcher",
        "WARN",
        "`jarvis` was not found on PATH.",
        "Run scripts/install_jarvis_command.ps1, then open a new terminal.",
    )


def _module_check(label: str, module: str, purpose: str) -> HealthCheck:
    if importlib.util.find_spec(module):
        return HealthCheck(label, "OK", purpose)
    return HealthCheck(label, "WARN", f"{purpose} is unavailable.", f"Install the Python package that provides {module}.")


def _speech_package_check(settings: dict[str, Any]) -> HealthCheck:
    has_vosk = importlib.util.find_spec("vosk") is not None
    has_sounddevice = importlib.util.find_spec("sounddevice") is not None
    if has_vosk and has_sounddevice:
        return HealthCheck("Offline speech packages", "OK", "Vosk and sounddevice are available.")
    if settings.get("vosk_model_path"):
        return HealthCheck(
            "Offline speech packages",
            "WARN",
            "Vosk offline recognition packages are not fully available; Jarvis will try Windows SAPI fallback.",
            "Install vosk and sounddevice for more reliable local recognition.",
        )
    return HealthCheck("Offline speech packages", "WARN", "No offline speech package path is configured.")


def _vosk_model_check(settings: dict[str, Any]) -> HealthCheck:
    path = Path(str(settings.get("vosk_model_path", DEFAULT_DATA_DIR / "vosk-model-small-en-us-0.15"))).expanduser()
    if path.exists() and path.is_dir():
        return HealthCheck("Vosk model", "OK", str(path))
    return HealthCheck("Vosk model", "WARN", f"Model folder not found: {path}", "Download a Vosk English model locally and update settings.json.")


def _openai_key_check(settings: dict[str, Any], store: JsonStore) -> HealthCheck:
    if not settings.get("allow_cloud_text_ai", False):
        return HealthCheck("OpenAI text", "OK", "Cloud text AI is disabled.")
    status, detail = openai_key_status(store)
    remediation = "Create a key at https://platform.openai.com/api-keys and run: jarvis --set-openai-key"
    return HealthCheck("OpenAI text", status, detail, "" if status == "OK" else remediation)


def _google_check(store: JsonStore) -> HealthCheck:
    status = GoogleServices(store).status
    if status.gmail_connected and status.calendar_connected:
        return HealthCheck("Google services", "OK", status.reason)
    return HealthCheck(
        "Google services",
        "WARN",
        status.reason,
        "Save a Desktop OAuth client JSON, then run: jarvis --connect-google",
    )


def _cloud_audio_check(settings: dict[str, Any]) -> HealthCheck:
    if settings.get("cloud_audio_allowed") is False:
        return HealthCheck("Cloud audio", "OK", "Microphone audio is configured local-only.")
    return HealthCheck("Cloud audio", "FAIL", "cloud_audio_allowed is not false.", "Set cloud_audio_allowed to false in settings.json.")


def _ocr_check(settings: dict[str, Any]) -> HealthCheck:
    configured = str(settings.get("tesseract_cmd", "")).strip()
    found = configured if configured and Path(configured).exists() else shutil.which("tesseract")
    if found:
        return HealthCheck("Local OCR", "OK", f"Tesseract found at {found}")
    return HealthCheck("Local OCR", "WARN", "Tesseract was not found; image scanning will fail safely until installed.")


def _approved_folders_check(settings: dict[str, Any]) -> HealthCheck:
    folders = [Path(str(raw)).expanduser() for raw in settings.get("approved_folders", [])]
    existing = [path for path in folders if path.exists() and path.is_dir()]
    if existing:
        return HealthCheck("Approved folders", "OK", f"{len(existing)} folder(s) configured.")
    return HealthCheck("Approved folders", "WARN", "No readable approved folders are configured.")


def _tts_check(settings: dict[str, Any]) -> HealthCheck:
    provider = str(settings.get("tts_provider", "elevenlabs"))
    cloud = "enabled" if settings.get("allow_cloud_tts", False) else "disabled"
    cache = "enabled" if settings.get("cache_tts_audio", False) else "disabled"
    if provider == "elevenlabs" and settings.get("allow_cloud_tts", False):
        status, detail = elevenlabs_key_status(settings)
        last_error = str(settings.get("tts_last_error", "")).strip()
        if last_error:
            status = "WARN"
            detail = f"{detail} Last runtime error: {last_error}"
        remediation = (
            "Resolve the last ElevenLabs runtime error, then run: Jarvis, voice test"
            if last_error
            else "Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in the project .env file."
        )
        return HealthCheck(
            "Reply voice",
            status,
            f"provider={provider}, cloud_tts={cloud}, cache={cache}. {detail}",
            "" if status == "OK" else remediation,
        )
    return HealthCheck("Reply voice", "OK", f"provider={provider}, cloud_tts={cloud}, cache={cache}")


def main() -> None:
    print(health_report())


if __name__ == "__main__":
    main()
