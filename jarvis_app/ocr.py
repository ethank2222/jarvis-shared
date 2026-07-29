from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app_config import MAX_OCR_TEXT_CHARS


IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


@dataclass(frozen=True)
class OcrResult:
    ok: bool
    text: str = ""
    engine: str = ""
    error: str = ""


class OcrService:
    """Local OCR wrapper. It never sends image data to cloud services."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = settings or {}

    def scan_image(self, path: Path | str) -> OcrResult:
        image_path = Path(path).resolve()
        if not image_path.exists() or not image_path.is_file():
            return OcrResult(False, error=f"Image file not found: {image_path}")
        if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            return OcrResult(False, error=f"Unsupported OCR file type: {image_path.suffix}")

        tesseract = self._tesseract_command()
        if not tesseract:
            return OcrResult(False, error="Local OCR is not configured. Install Tesseract and set tesseract_cmd if needed.")

        language = str(self.settings.get("ocr_language", "eng")).strip() or "eng"
        try:
            completed = subprocess.run(
                [tesseract, str(image_path), "stdout", "-l", language],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return OcrResult(False, engine="tesseract", error=f"Local OCR failed: {exc}")

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            return OcrResult(False, engine="tesseract", error=detail or "Tesseract returned an error.")

        text = completed.stdout.strip()[:MAX_OCR_TEXT_CHARS]
        if not text:
            return OcrResult(False, engine="tesseract", error="No text was detected in the image.")
        return OcrResult(True, text=text, engine="tesseract")

    def _tesseract_command(self) -> str:
        configured = str(self.settings.get("tesseract_cmd", "")).strip()
        if configured and Path(configured).exists():
            return configured
        found = shutil.which("tesseract")
        return found or ""
