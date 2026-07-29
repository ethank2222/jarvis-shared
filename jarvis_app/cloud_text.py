from __future__ import annotations

import os
from typing import Any

from .app_config import MAX_CLOUD_TEXT_CHARS
from .openai_config import get_openai_api_key, sanitize_openai_error
from .security import SecurityManager, SecurityViolation
from .storage import JsonStore


class CloudTextClient:
    """Optional text-only AI client. It never accepts or sends audio."""

    def __init__(self, security: SecurityManager, settings: dict[str, Any] | None = None, store: JsonStore | None = None) -> None:
        self.security = security
        self.settings = settings or {}
        self.store = store
        self._client: Any | None = None
        self._client_key = ""

    def answer(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        payload = {"prompt": prompt, "context": context or {}}
        self.security.assert_cloud_text_allowed(payload)
        if not isinstance(prompt, str):
            raise SecurityViolation("Cloud text AI accepts text only.")
        if len(prompt) > MAX_CLOUD_TEXT_CHARS:
            raise SecurityViolation(f"Cloud text AI prompt exceeds {MAX_CLOUD_TEXT_CHARS} characters.")

        api_key = get_openai_api_key(self.store)
        if not api_key:
            raise SecurityViolation("Cloud text AI is enabled, but no OpenAI API key is configured. Run: jarvis --set-openai-key")

        try:
            client = self._get_client(api_key)
            response = client.responses.create(
                model=os.environ.get("JARVIS_TEXT_MODEL", str(self.settings.get("openai_text_model", "gpt-5.5"))),
                max_output_tokens=int(self.settings.get("openai_max_output_tokens", 320) or 320),
                instructions=(
                    "You are a concise private desktop assistant named Jarvis. "
                    "Answer clearly in one to three short paragraphs unless detail is necessary. "
                    "Never claim that you created a note, reminder, file, event, email, or other local action; "
                    "only the desktop application's verified tool results may claim an action succeeded. "
                    "You may receive text transcribed locally from the user's microphone, but you must never ask for, "
                    "process, or request raw microphone audio or voice recordings."
                ),
                input=prompt,
            )
        except Exception as exc:
            raise RuntimeError(sanitize_openai_error(exc)) from exc
        return response.output_text.strip()

    def _get_client(self, api_key: str) -> Any:
        if self._client is not None and self._client_key == api_key:
            return self._client
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on local environment
            raise SecurityViolation(f"OpenAI client is unavailable: {exc}") from exc
        self._client = OpenAI(
            api_key=api_key,
            timeout=float(self.settings.get("openai_request_timeout_seconds", 20) or 20),
            max_retries=1,
        )
        self._client_key = api_key
        return self._client
