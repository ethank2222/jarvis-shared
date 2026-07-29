from __future__ import annotations

import os
import sys
from pathlib import Path

from .env_loader import load_project_env


load_project_env()

APP_NAME = "Private Jarvis"
APP_VERSION = "0.6.0"
WAKE_PHRASE = "jarvis"
ACTIVATION_PHRASE = "wake up daddy's home"

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR", WORKSPACE_ROOT / ".jarvis_data"))

SUPPORTED_TEXT_EXTENSIONS = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".py",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

MAX_FILE_SEARCH_RESULTS = 25
MAX_TEXT_FILE_BYTES = 1_000_000
MAX_CLOUD_TEXT_CHARS = 6_000
MAX_SAFE_WALK_FILES = 5_000
MAX_MEMORY_ITEMS = 200
MAX_MEMORY_TEXT_CHARS = 1_000
MAX_OCR_TEXT_CHARS = 20_000
MAX_TTS_INPUT_CHARS = 1_200

APPROVED_APP_COMMANDS = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "explorer": ["explorer.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "firefox": ["firefox.exe"],
    "slack": ["slack.exe"],
    "discord": ["Discord.exe"],
    "github desktop": ["GitHubDesktop.exe"],
    "githubdesktop": ["GitHubDesktop.exe"],
    "github": ["GitHubDesktop.exe"],
    "word": ["WINWORD.EXE"],
    "microsoft word": ["WINWORD.EXE"],
    "excel": ["EXCEL.EXE"],
    "microsoft excel": ["EXCEL.EXE"],
    "powerpoint": ["POWERPNT.EXE"],
    "power point": ["POWERPNT.EXE"],
    "microsoft powerpoint": ["POWERPNT.EXE"],
    "microsoft power point": ["POWERPNT.EXE"],
    "ppt": ["POWERPNT.EXE"],
    "outlook": ["OUTLOOK.EXE"],
    "microsoft outlook": ["OUTLOOK.EXE"],
    "teams": ["ms-teams.exe"],
    "microsoft teams": ["ms-teams.exe"],
    "onenote": ["ONENOTE.EXE"],
    "one note": ["ONENOTE.EXE"],
    "microsoft onenote": ["ONENOTE.EXE"],
    "vs code": ["Code.exe"],
    "vscode": ["Code.exe"],
    "visual studio code": ["Code.exe"],
}

APPROVED_SHELL_COMMANDS = {
    "jarvis version": {
        "description": "Print the installed Jarvis version.",
        "command": [sys.executable, str(WORKSPACE_ROOT / "run_jarvis.py"), "--version"],
        "cwd": str(WORKSPACE_ROOT),
        "timeout_seconds": 15,
    },
    "jarvis health": {
        "description": "Run Jarvis local health diagnostics.",
        "command": [sys.executable, str(WORKSPACE_ROOT / "run_jarvis.py"), "--health"],
        "cwd": str(WORKSPACE_ROOT),
        "timeout_seconds": 60,
    },
    "google status": {
        "description": "Print the local Google connection status.",
        "command": [sys.executable, str(WORKSPACE_ROOT / "run_jarvis.py"), "--google-status"],
        "cwd": str(WORKSPACE_ROOT),
        "timeout_seconds": 30,
    },
    "python version": {
        "description": "Print the Python runtime version.",
        "command": [sys.executable, "--version"],
        "cwd": str(WORKSPACE_ROOT),
        "timeout_seconds": 15,
    },
    "git status": {
        "description": "Show the workspace git status.",
        "command": ["git", "status", "--short"],
        "cwd": str(WORKSPACE_ROOT),
        "timeout_seconds": 30,
    },
    "pytest": {
        "description": "Run the project test suite.",
        "command": [sys.executable, "-m", "pytest"],
        "cwd": str(WORKSPACE_ROOT),
        "timeout_seconds": 180,
    },
}

DEFAULT_SETTINGS = {
    "wake_phrase": WAKE_PHRASE,
    "activation_phrase": ACTIVATION_PHRASE,
    "allow_cloud_text_ai": True,
    "cloud_text_requires_jarvis": True,
    "openai_text_model": "gpt-5.5",
    "openai_max_output_tokens": 320,
    "openai_request_timeout_seconds": 20,
    "allow_cloud_tts": False,
    "tts_provider": "elevenlabs",
    "openai_tts_model": "gpt-4o-mini-tts",
    "openai_tts_voice": "cedar",
    "openai_tts_instructions": "Speak as a polished adult male British private assistant: calm, precise, warm, technically fluent, and realistic. Do not imitate any real actor or copyrighted character voice.",
    "elevenlabs_tts_model": "eleven_flash_v2_5",
    "elevenlabs_voice_id": "",
    "elevenlabs_tts_output_format": "pcm_24000",
    "cache_tts_audio": False,
    "tts_cache_folder": str(DEFAULT_DATA_DIR / "tts_cache"),
    "max_tts_cache_items": 50,
    "tts_usage_month": "",
    "tts_monthly_chars": 0,
    "tts_last_error": "",
    "tts_last_error_at": "",
    "openai_tts_estimated_cost_per_1m_chars": 0.0,
    "elevenlabs_tts_estimated_cost_per_1m_chars": 0.0,
    "allow_cloud_image_analysis": False,
    "cloud_audio_allowed": False,
    "include_memory_in_cloud_text": False,
    "monthly_budget_usd": 10,
    "store_history": True,
    "max_history_items": 500,
    "max_history_text_chars": 4_000,
    "approved_folders": [str(WORKSPACE_ROOT)],
    "notes_folder": str(DEFAULT_DATA_DIR / "notes"),
    "screenshots_folder": str(DEFAULT_DATA_DIR / "screenshots"),
    "ocr_language": "eng",
    "tesseract_cmd": "",
    "google_oauth_client_secret_file": str(DEFAULT_DATA_DIR / "environment" / "google-oauth-client.json"),
    "voice_name": "",
    "vosk_model_path": str(DEFAULT_DATA_DIR / "vosk-model-small-en-us-0.15"),
}
