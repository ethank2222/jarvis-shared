from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class ApprovalLevel(str, Enum):
    AUTO = "Auto"
    CONFIRM = "Confirm"
    REVIEW = "Review"
    BLOCKED = "Blocked"


class SecurityViolation(RuntimeError):
    """Raised when a requested action violates the local security policy."""


@dataclass(frozen=True)
class ActionPolicy:
    action_id: str
    area: str
    description: str
    approval: ApprovalLevel
    sends_audio_cloud: bool = False
    sends_text_cloud: bool = False
    sends_image_cloud: bool = False
    mutates_external: bool = False
    destructive: bool = False


ACTION_POLICIES: tuple[ActionPolicy, ...] = (
    ActionPolicy("voice.wake", "Voice", "Wake on configured phrase", ApprovalLevel.AUTO),
    ActionPolicy("voice.push_to_talk", "Voice", "Push-to-talk conversation", ApprovalLevel.AUTO),
    ActionPolicy("voice.status", "Voice", "Report voice provider, cache, and usage settings", ApprovalLevel.AUTO),
    ActionPolicy("voice.test", "Voice", "Speak a short voice test phrase", ApprovalLevel.AUTO),
    ActionPolicy("voice.set_provider", "Voice", "Change the reply voice provider", ApprovalLevel.CONFIRM),
    ActionPolicy("voice.set_cache", "Voice", "Change reply-audio cache setting", ApprovalLevel.CONFIRM),
    ActionPolicy("system.health", "System", "Run local health diagnostics", ApprovalLevel.AUTO),
    ActionPolicy("google.status", "Google", "Report Gmail and Calendar connection status", ApprovalLevel.AUTO),
    ActionPolicy("conversation.answer", "Conversation", "Answer general questions", ApprovalLevel.AUTO, sends_text_cloud=True),
    ActionPolicy("calendar.read_today", "Calendar", "Read today's Google Calendar schedule", ApprovalLevel.AUTO),
    ActionPolicy("calendar.search", "Calendar", "Search upcoming Google Calendar events", ApprovalLevel.AUTO),
    ActionPolicy("calendar.create", "Calendar", "Create a Google Calendar event", ApprovalLevel.CONFIRM, mutates_external=True),
    ActionPolicy("calendar.update", "Calendar", "Update a Google Calendar event", ApprovalLevel.CONFIRM, mutates_external=True),
    ActionPolicy("calendar.delete", "Calendar", "Delete or cancel a Google Calendar event", ApprovalLevel.REVIEW, mutates_external=True, destructive=True),
    ActionPolicy("gmail.search", "Gmail", "Search Gmail", ApprovalLevel.AUTO),
    ActionPolicy("gmail.summarize", "Gmail", "Summarize Gmail threads", ApprovalLevel.AUTO, sends_text_cloud=True),
    ActionPolicy("gmail.draft", "Gmail", "Draft an email", ApprovalLevel.AUTO),
    ActionPolicy("gmail.send", "Gmail", "Send an email", ApprovalLevel.REVIEW, mutates_external=True),
    ActionPolicy("gmail.modify", "Gmail", "Archive, label, or star messages", ApprovalLevel.CONFIRM, mutates_external=True),
    ActionPolicy("gmail.delete", "Gmail", "Delete email", ApprovalLevel.BLOCKED, mutates_external=True, destructive=True),
    ActionPolicy("reminders.create", "Reminders", "Create local reminder", ApprovalLevel.AUTO),
    ActionPolicy("reminders.list", "Reminders", "List active local reminders", ApprovalLevel.AUTO),
    ActionPolicy("reminders.edit", "Reminders", "Edit local reminder", ApprovalLevel.CONFIRM),
    ActionPolicy("reminders.delete", "Reminders", "Delete local reminder", ApprovalLevel.CONFIRM, destructive=True),
    ActionPolicy("reminders.complete", "Reminders", "Complete local reminder", ApprovalLevel.AUTO),
    ActionPolicy("timers.create", "Timers", "Create local countdown timer", ApprovalLevel.AUTO),
    ActionPolicy("timers.list", "Timers", "List local countdown timers", ApprovalLevel.AUTO),
    ActionPolicy("timers.cancel", "Timers", "Cancel local countdown timer", ApprovalLevel.AUTO),
    ActionPolicy("memory.remember", "Memory", "Store an explicit local memory", ApprovalLevel.AUTO),
    ActionPolicy("memory.list", "Memory", "List local memories", ApprovalLevel.AUTO),
    ActionPolicy("memory.forget", "Memory", "Forget a local memory", ApprovalLevel.CONFIRM, destructive=True),
    ActionPolicy("notes.scan", "Notes", "Scan screenshot or image for text", ApprovalLevel.AUTO),
    ActionPolicy("notes.list", "Notes", "List local notes", ApprovalLevel.AUTO),
    ActionPolicy("notes.read", "Notes", "Read a local note", ApprovalLevel.AUTO),
    ActionPolicy("notes.summarize", "Notes", "Summarize scanned notes", ApprovalLevel.AUTO, sends_text_cloud=True),
    ActionPolicy("notes.extract_tasks", "Notes", "Extract tasks from notes", ApprovalLevel.AUTO, sends_text_cloud=True),
    ActionPolicy("files.search", "Files", "Search approved folders", ApprovalLevel.AUTO),
    ActionPolicy("files.summarize", "Files", "Summarize approved files locally", ApprovalLevel.AUTO),
    ActionPolicy("files.create_note", "Files", "Create a new local note file", ApprovalLevel.AUTO),
    ActionPolicy("files.move", "Files", "Rename or move files", ApprovalLevel.REVIEW),
    ActionPolicy("files.delete", "Files", "Delete files", ApprovalLevel.BLOCKED, destructive=True),
    ActionPolicy("screen.capture", "Screen", "Capture screenshot for analysis", ApprovalLevel.CONFIRM),
    ActionPolicy("desktop.open_app", "Desktop", "Open approved apps", ApprovalLevel.AUTO),
    ActionPolicy("desktop.open_notepad_text", "Desktop", "Open generated text in Notepad", ApprovalLevel.AUTO),
    ActionPolicy("desktop.close_app", "Desktop", "Close apps", ApprovalLevel.BLOCKED),
    ActionPolicy("automation.shell", "Automation", "Run an approved shell command", ApprovalLevel.CONFIRM),
    ActionPolicy("web.search", "Web", "Search the web", ApprovalLevel.CONFIRM, sends_text_cloud=True),
)


AUDIO_KEYS = {
    "audio",
    "audio_bytes",
    "audio_file",
    "audio_path",
    "clip",
    "microphone",
    "mp3",
    "recording",
    "recording_path",
    "voice",
    "wav",
}


class SecurityManager:
    """Central policy gate for every action and cloud payload."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = settings or {}
        self._policies = {policy.action_id: policy for policy in ACTION_POLICIES}

    def policy_for(self, action_id: str) -> ActionPolicy:
        try:
            return self._policies[action_id]
        except KeyError as exc:
            raise SecurityViolation(f"Unknown action '{action_id}' is not allowed.") from exc

    def assert_action_allowed(self, action_id: str) -> ActionPolicy:
        policy = self.policy_for(action_id)
        if policy.approval is ApprovalLevel.BLOCKED:
            raise SecurityViolation(f"Action '{policy.description}' is blocked by policy.")
        if policy.sends_audio_cloud:
            raise SecurityViolation("Cloud audio transfer is permanently disabled.")
        return policy

    def assert_no_audio_payload(self, payload: Any) -> None:
        if isinstance(payload, (bytes, bytearray, memoryview)):
            raise SecurityViolation("Binary payloads are not allowed in cloud requests.")
        for key, value in self._walk_payload(payload):
            if key and key.lower() in AUDIO_KEYS:
                raise SecurityViolation(f"Cloud payload contains forbidden audio field '{key}'.")
            if isinstance(value, (bytes, bytearray, memoryview)):
                raise SecurityViolation("Cloud payload contains forbidden binary audio-like data.")

    def assert_cloud_text_allowed(self, payload: Any) -> None:
        self.assert_no_audio_payload(payload)
        if not self.settings.get("allow_cloud_text_ai", False):
            raise SecurityViolation("Cloud text AI is disabled in settings.")
        if self.settings.get("cloud_text_requires_jarvis", True):
            if not isinstance(payload, dict):
                raise SecurityViolation("Cloud text AI requires structured payload metadata.")
            context = payload.get("context", {})
            if not isinstance(context, dict) or context.get("jarvis_invoked") is not True:
                raise SecurityViolation("Cloud text AI is allowed only for Jarvis-prefixed commands.")

    def assert_cloud_image_allowed(self, payload: Any) -> None:
        self.assert_no_audio_payload(payload)
        if not self.settings.get("allow_cloud_image_analysis", False):
            raise SecurityViolation("Cloud image analysis is disabled in settings.")

    def security_summary(self) -> list[str]:
        cloud_text = "enabled" if self.settings.get("allow_cloud_text_ai", False) else "disabled"
        cloud_image = "enabled" if self.settings.get("allow_cloud_image_analysis", False) else "disabled"
        cloud_tts = "enabled" if self.settings.get("allow_cloud_tts", False) else "disabled"
        return [
            "Cloud audio: permanently disabled",
            f"Cloud text AI: {cloud_text}",
            f"Cloud TTS output: {cloud_tts} (reply text only)",
            f"Cloud image analysis: {cloud_image}",
            "Blocked actions: file delete, email delete, unapproved shell commands, app closing",
            "External mutations require confirmation or UI review",
        ]

    def _walk_payload(self, payload: Any) -> Iterable[tuple[str | None, Any]]:
        if isinstance(payload, dict):
            for key, value in payload.items():
                yield str(key), value
                yield from self._walk_payload(value)
        elif isinstance(payload, (list, tuple, set)):
            for value in payload:
                yield None, value
                yield from self._walk_payload(value)
        else:
            yield None, payload
