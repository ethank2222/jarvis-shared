from __future__ import annotations

import os
import re
import subprocess
import uuid
import ctypes
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from collections.abc import Iterator
from typing import Any, Callable

from PIL import ImageGrab

from .app_config import (
    APPROVED_APP_COMMANDS,
    APPROVED_SHELL_COMMANDS,
    MAX_FILE_SEARCH_RESULTS,
    MAX_MEMORY_ITEMS,
    MAX_MEMORY_TEXT_CHARS,
    MAX_SAFE_WALK_FILES,
    MAX_TEXT_FILE_BYTES,
    SUPPORTED_TEXT_EXTENSIONS,
    WORKSPACE_ROOT,
)
from .elevenlabs_config import elevenlabs_key_status
from .google_services import GoogleServiceError, GoogleServices
from .health import health_report
from .ocr import IMAGE_EXTENSIONS, OcrService
from .security import ActionPolicy, ApprovalLevel, SecurityManager, SecurityViolation
from .storage import JsonStore, redact_sensitive_text, utc_now_iso


@dataclass
class ActionResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None


ApprovalCallback = Callable[[ActionPolicy, dict[str, Any]], bool]


class ActionRegistry:
    def __init__(self, store: JsonStore, security: SecurityManager, google: GoogleServices) -> None:
        self.store = store
        self.security = security
        self.google = google
        self.handlers: dict[str, Callable[[dict[str, Any]], ActionResult]] = {
            "system.health": self._system_health,
            "google.status": self._google_status,
            "voice.status": self._voice_status,
            "voice.test": self._voice_test,
            "voice.set_provider": self._voice_set_provider,
            "voice.set_cache": self._voice_set_cache,
            "reminders.create": self._create_reminder,
            "reminders.list": self._list_reminders_action,
            "reminders.delete": self._delete_reminder,
            "reminders.edit": self._edit_reminder,
            "reminders.complete": self._complete_reminder,
            "timers.create": self._create_timer,
            "timers.list": self._list_timers,
            "timers.cancel": self._cancel_timer,
            "memory.remember": self._remember,
            "memory.list": self._list_memories,
            "memory.forget": self._forget_memory,
            "files.search": self._search_files,
            "files.summarize": self._summarize_file,
            "files.create_note": self._create_note,
            "notes.scan": self._scan_note,
            "notes.list": self._list_notes,
            "notes.read": self._read_note,
            "screen.capture": self._capture_screen,
            "desktop.open_app": self._open_app,
            "desktop.open_notepad_text": self._open_notepad_text,
            "automation.shell": self._run_shell_command,
            "calendar.read_today": self._calendar_today,
            "calendar.search": self._calendar_search,
            "calendar.create": self._calendar_create,
            "gmail.search": self._gmail_search,
            "gmail.draft": self._gmail_draft,
            "gmail.send": self._gmail_send,
        }

    def execute(self, action_id: str, payload: dict[str, Any], approve: ApprovalCallback | None = None) -> ActionResult:
        policy = self.security.assert_action_allowed(action_id)
        if policy.approval in {ApprovalLevel.CONFIRM, ApprovalLevel.REVIEW}:
            if approve is None or not approve(policy, payload):
                return ActionResult(False, f"Cancelled: {policy.description}")

        handler = self.handlers.get(action_id)
        if handler is None:
            raise SecurityViolation(f"No handler is registered for '{action_id}'.")
        return handler(payload)

    def _system_health(self, _payload: dict[str, Any]) -> ActionResult:
        return ActionResult(True, health_report(self.store))

    def _google_status(self, _payload: dict[str, Any]) -> ActionResult:
        connected = self.google.status.gmail_connected and self.google.status.calendar_connected
        return ActionResult(connected, self.google.status_summary())

    def _voice_status(self, _payload: dict[str, Any]) -> ActionResult:
        provider = str(self.store.settings.get("tts_provider", "elevenlabs"))
        cloud = "enabled" if self.store.settings.get("allow_cloud_tts", False) else "disabled"
        cache = "enabled" if self.store.settings.get("cache_tts_audio", False) else "disabled"
        month = str(self.store.settings.get("tts_usage_month", "")) or "not started"
        chars = int(self.store.settings.get("tts_monthly_chars", 0) or 0)
        rate_key = "elevenlabs_tts_estimated_cost_per_1m_chars" if provider == "elevenlabs" else "openai_tts_estimated_cost_per_1m_chars"
        rate = float(self.store.settings.get(rate_key, 0.0) or 0.0)
        cost = f"${(chars / 1_000_000) * rate:.4f}" if rate > 0 else "rate not configured"
        lines = [
            f"Voice provider: {provider}",
            f"Cloud TTS: {cloud}",
            f"Audio cache: {cache}",
            f"TTS usage month: {month}",
            f"TTS generated characters: {chars}",
            f"Estimated TTS cost: {cost}",
            "Fallback: cloud TTS, when enabled, falls back to local Windows SAPI.",
        ]
        last_error = str(self.store.settings.get("tts_last_error", "")).strip()
        last_error_at = str(self.store.settings.get("tts_last_error_at", "")).strip()
        if last_error:
            lines.append(f"Last TTS error ({last_error_at or 'time unknown'}): {last_error}")
        if provider == "elevenlabs":
            credential_status, credential_detail = elevenlabs_key_status(self.store.settings)
            lines.append(f"ElevenLabs configuration: {credential_status} - {credential_detail}")
        return ActionResult(True, "\n".join(lines))

    def _voice_test(self, _payload: dict[str, Any]) -> ActionResult:
        return ActionResult(True, "Voice test ready, sir. Local microphone audio remains on this machine.")

    def _voice_set_provider(self, payload: dict[str, Any]) -> ActionResult:
        provider = str(payload.get("provider", "")).strip().lower()
        if provider in {"windows", "sapi", "local", "offline"}:
            self.store.settings["tts_provider"] = "sapi"
            self.store.settings["allow_cloud_tts"] = False
            self.store.save_settings()
            return ActionResult(True, "Reply voice set to local Windows SAPI. Cloud TTS is disabled.")
        if provider == "openai":
            self.store.settings["tts_provider"] = "openai"
            self.store.settings["allow_cloud_tts"] = True
            self.store.save_settings()
            return ActionResult(True, "Reply voice set to OpenAI TTS. Only Jarvis reply text may be sent; microphone audio remains local.")
        if provider == "elevenlabs":
            self.store.settings["tts_provider"] = "elevenlabs"
            self.store.settings["allow_cloud_tts"] = True
            self.store.save_settings()
            status, detail = elevenlabs_key_status(self.store.settings)
            suffix = "" if status == "OK" else f" Configuration warning: {detail}"
            return ActionResult(
                True,
                "Reply voice set to ElevenLabs. Only Jarvis reply text may be sent; microphone audio remains local."
                + suffix,
            )
        if provider == "azure":
            return ActionResult(False, "Azure is documented as a future provider, but is not wired in this build.")
        return ActionResult(False, "Supported voice providers are local Windows SAPI, OpenAI, and ElevenLabs.")

    def _voice_set_cache(self, payload: dict[str, Any]) -> ActionResult:
        enabled = bool(payload.get("enabled"))
        self.store.settings["cache_tts_audio"] = enabled
        self.store.save_settings()
        state = "enabled" if enabled else "disabled"
        return ActionResult(True, f"Reply-audio cache {state}. Cached audio may contain private reply text, so keep the Jarvis data folder private.")

    def _create_reminder(self, payload: dict[str, Any]) -> ActionResult:
        description = str(payload.get("description") or payload.get("title", "")).strip()
        if not description:
            return ActionResult(False, "I need reminder text.")
        due_text = str(payload.get("due_text", "")).strip()
        schedule = self._parse_reminder_schedule(due_text)
        if due_text and schedule is None:
            return ActionResult(False, f"I could not understand the reminder date/time '{due_text}'. Try something like 'today 11:15' or 'tomorrow 4 PM'.")
        reminder = {
            "id": uuid.uuid4().hex[:8],
            "title": description,
            "description": description,
            "due_text": due_text,
            "date": schedule["date"] if schedule else "",
            "time": schedule["time"] if schedule else "",
            "due_at": schedule["due_at"] if schedule else "",
            "timezone": schedule["timezone"] if schedule else "",
            "created_at": utc_now_iso(),
            "done": False,
            "notified": False,
        }
        self.store.append_collection("reminders", reminder)
        stored = next(
            (item for item in self.store.load_collection("reminders") if item.get("id") == reminder["id"]),
            None,
        )
        if stored is None:
            return ActionResult(False, "The reminder could not be verified after saving.")
        if schedule:
            return ActionResult(
                True,
                f"Reminder saved locally for {self._format_reminder_due(schedule['due_at'])}: {description}",
                {"reminder": stored},
            )
        return ActionResult(True, f"Reminder saved locally with no scheduled time: {description}", {"reminder": stored})

    def _delete_reminder(self, payload: dict[str, Any]) -> ActionResult:
        reminder_id = str(payload.get("id", "")).strip()
        reminders = self.store.load_collection("reminders")
        kept = [item for item in reminders if item.get("id") != reminder_id]
        if len(kept) == len(reminders):
            return ActionResult(False, f"No reminder found with id {reminder_id}.")
        self.store.save_collection("reminders", kept)
        return ActionResult(True, f"Deleted reminder {reminder_id}.")

    def _edit_reminder(self, payload: dict[str, Any]) -> ActionResult:
        reminder_id = str(payload.get("id", "")).strip()
        reminders = self.store.load_collection("reminders")
        for item in reminders:
            if item.get("id") == reminder_id:
                description = str(payload.get("description") or payload.get("title", item.get("description") or item.get("title", ""))).strip()
                due_text = str(payload.get("due_text", item.get("due_text", ""))).strip()
                schedule = self._parse_reminder_schedule(due_text)
                if due_text and schedule is None:
                    return ActionResult(False, f"I could not understand the reminder date/time '{due_text}'.")
                item["title"] = description
                item["description"] = description
                item["due_text"] = due_text
                item["date"] = schedule["date"] if schedule else ""
                item["time"] = schedule["time"] if schedule else ""
                item["due_at"] = schedule["due_at"] if schedule else ""
                item["timezone"] = schedule["timezone"] if schedule else ""
                item["notified"] = False
                item["updated_at"] = utc_now_iso()
                self.store.save_collection("reminders", reminders)
                stored = next(
                    (candidate for candidate in self.store.load_collection("reminders") if candidate.get("id") == reminder_id),
                    None,
                )
                if stored is None or stored.get("updated_at") != item["updated_at"]:
                    return ActionResult(False, f"Reminder {reminder_id} could not be verified after updating.")
                due = f" for {self._format_reminder_due(stored['due_at'])}" if stored.get("due_at") else " with no scheduled time"
                return ActionResult(True, f"Updated reminder {reminder_id}{due}: {stored['description']}", {"reminder": stored})
        return ActionResult(False, f"No reminder found with id {reminder_id}.")

    def _complete_reminder(self, payload: dict[str, Any]) -> ActionResult:
        reminder_id = str(payload.get("id", "")).strip()
        reminders = self.store.load_collection("reminders")
        for item in reminders:
            if item.get("id") == reminder_id:
                item["done"] = True
                item["completed_at"] = utc_now_iso()
                self.store.save_collection("reminders", reminders)
                return ActionResult(True, f"Completed reminder {reminder_id}.")
        return ActionResult(False, f"No reminder found with id {reminder_id}.")

    def list_reminders(self) -> ActionResult:
        reminders = [item for item in self.store.load_collection("reminders") if not item.get("done")]
        if not reminders:
            return ActionResult(True, "No active reminders.")
        lines = []
        reminders = sorted(reminders, key=lambda item: item.get("due_at") or "9999")
        for item in reminders[:10]:
            due = f" ({self._format_reminder_due(str(item.get('due_at', '')))})" if item.get("due_at") else " (unscheduled)"
            notified = " - notified" if item.get("notified") else ""
            description = item.get("description") or item.get("title") or "Reminder"
            lines.append(f"{item.get('id')}: {description}{due}{notified}")
        return ActionResult(True, "Active reminders:\n" + "\n".join(lines), {"reminders": reminders})

    def _list_reminders_action(self, _payload: dict[str, Any]) -> ActionResult:
        return self.list_reminders()

    def due_reminders(self) -> list[dict[str, Any]]:
        now = datetime.now().astimezone()
        reminders = self.store.load_collection("reminders")
        due: list[dict[str, Any]] = []
        changed = False
        for item in reminders:
            if item.get("done") or item.get("notified"):
                continue
            due_at = self._reminder_due_at(item)
            if due_at is None or due_at > now:
                continue
            item["notified"] = True
            item["notified_at"] = utc_now_iso()
            due.append(item)
            changed = True
        if changed:
            self.store.save_collection("reminders", reminders)
        return due

    def _parse_reminder_schedule(self, due_text: str) -> dict[str, str] | None:
        clean = due_text.strip()
        if not clean:
            return None
        now = datetime.now().astimezone()
        time_only = self._parse_time_only_reminder(clean, now)
        if time_only is not None:
            return self._reminder_schedule(time_only)

        lowered = clean.lower()
        if lowered == "tonight":
            due_at = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if due_at <= now:
                due_at += timedelta(days=1)
            return self._reminder_schedule(due_at)
        if lowered == "tomorrow":
            due_at = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            return self._reminder_schedule(due_at)

        try:
            import dateparser
        except Exception:
            return None

        settings = {
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": now,
        }
        parsed = dateparser.parse(clean, settings=settings)
        if parsed is None and lowered.startswith("next "):
            parsed = dateparser.parse(clean[5:].strip(), settings=settings)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        due_at = parsed.astimezone().replace(second=0, microsecond=0)
        if not self._reminder_has_explicit_time(clean):
            due_at = due_at.replace(hour=9, minute=0)
            if due_at <= now:
                due_at += timedelta(days=1)
        return self._reminder_schedule(due_at)

    def _parse_time_only_reminder(self, due_text: str, now: datetime) -> datetime | None:
        match = re.match(
            r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)?$",
            due_text.strip(),
            re.I,
        )
        if not match:
            return None
        minute = int(match.group("minute") or 0)
        hour = int(match.group("hour"))
        ampm = (match.group("ampm") or "").lower().replace(".", "")
        if minute > 59:
            return None
        if ampm:
            if hour < 1 or hour > 12:
                return None
            if ampm == "pm" and hour != 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
        elif ":" not in due_text:
            return None
        elif hour > 23:
            return None
        due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due_at <= now:
            due_at += timedelta(days=1)
        return due_at

    def _reminder_has_explicit_time(self, due_text: str) -> bool:
        return bool(
            re.search(r"\b\d{1,2}:\d{2}\b", due_text, re.I)
            or re.search(r"\b\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?)\b", due_text, re.I)
            or re.search(r"\b(noon|midnight)\b", due_text, re.I)
        )

    def _reminder_schedule(self, due_at: datetime) -> dict[str, str]:
        due_at = due_at.astimezone().replace(second=0, microsecond=0)
        return {
            "date": due_at.strftime("%Y-%m-%d"),
            "time": due_at.strftime("%H:%M"),
            "due_at": due_at.isoformat(),
            "timezone": due_at.tzname() or str(due_at.tzinfo),
        }

    def _reminder_due_at(self, item: dict[str, Any]) -> datetime | None:
        raw = str(item.get("due_at", "")).strip()
        if not raw:
            return None
        try:
            due_at = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return due_at.astimezone()

    def _format_reminder_due(self, raw_due_at: str) -> str:
        try:
            due_at = datetime.fromisoformat(raw_due_at).astimezone()
        except ValueError:
            return raw_due_at
        return due_at.strftime("%a %b %d, %I:%M %p").replace(" 0", " ")

    def _create_timer(self, payload: dict[str, Any]) -> ActionResult:
        try:
            duration_seconds = int(payload.get("duration_seconds", 0))
        except (TypeError, ValueError):
            return ActionResult(False, "I need a timer duration like 5 minutes.")
        if duration_seconds <= 0:
            return ActionResult(False, "I need a timer duration like 5 minutes.")
        if duration_seconds > 7 * 24 * 60 * 60:
            return ActionResult(False, "Timers are limited to 7 days. Use a reminder for longer time spans.")

        label = str(payload.get("label", "")).strip() or "Timer"
        duration_text = str(payload.get("duration_text", "")).strip() or self._format_timer_duration(duration_seconds)
        expires_at = datetime.now().astimezone() + timedelta(seconds=duration_seconds)
        timer = {
            "id": uuid.uuid4().hex[:8],
            "label": label[:80],
            "duration_text": duration_text,
            "duration_seconds": duration_seconds,
            "created_at": utc_now_iso(),
            "expires_at": expires_at.isoformat(),
            "cancelled": False,
            "done": False,
            "notified": False,
        }
        self.store.append_collection("timers", timer)
        stored = next((item for item in self.store.load_collection("timers") if item.get("id") == timer["id"]), None)
        if stored is None:
            return ActionResult(False, "The timer could not be verified after saving.")
        return ActionResult(
            True,
            f"Timer set locally for {duration_text}: {timer['label']}. Ends at {expires_at.strftime('%I:%M %p').lstrip('0')}.",
            {"timer": stored},
        )

    def _list_timers(self, _payload: dict[str, Any]) -> ActionResult:
        self.due_timers()
        now = datetime.now().astimezone()
        active = []
        for item in self.store.load_collection("timers"):
            if item.get("cancelled") or item.get("done"):
                continue
            expires_at = self._timer_expires_at(item)
            if expires_at is None or expires_at <= now:
                continue
            active.append((expires_at, item))
        if not active:
            return ActionResult(True, "No active timers.", {"timers": []})

        lines = []
        for expires_at, item in sorted(active, key=lambda pair: pair[0])[:10]:
            remaining = max(0, int((expires_at - now).total_seconds()))
            lines.append(f"{item.get('id')}: {item.get('label', 'Timer')} - {self._format_timer_duration(remaining)} remaining")
        return ActionResult(True, "Active timers:\n" + "\n".join(lines), {"timers": [item for _expires, item in active]})

    def _cancel_timer(self, payload: dict[str, Any]) -> ActionResult:
        timer_id = str(payload.get("id", "")).strip()
        if not timer_id:
            return ActionResult(False, "I need a timer id to cancel.")
        timers = self.store.load_collection("timers")
        for item in timers:
            if item.get("id") == timer_id:
                if item.get("cancelled"):
                    return ActionResult(True, f"Timer {timer_id} was already cancelled.")
                item["cancelled"] = True
                item["cancelled_at"] = utc_now_iso()
                self.store.save_collection("timers", timers)
                return ActionResult(True, f"Cancelled timer {timer_id}.")
        return ActionResult(False, f"No timer found with id {timer_id}.")

    def due_timers(self) -> list[dict[str, Any]]:
        now = datetime.now().astimezone()
        timers = self.store.load_collection("timers")
        due: list[dict[str, Any]] = []
        changed = False
        for item in timers:
            if item.get("cancelled") or item.get("notified"):
                continue
            expires_at = self._timer_expires_at(item)
            if expires_at is None or expires_at > now:
                continue
            item["done"] = True
            item["notified"] = True
            item["notified_at"] = utc_now_iso()
            due.append(item)
            changed = True
        if changed:
            self.store.save_collection("timers", timers)
        return due

    def _timer_expires_at(self, item: dict[str, Any]) -> datetime | None:
        raw = str(item.get("expires_at", "")).strip()
        if not raw:
            return None
        try:
            expires_at = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return expires_at.astimezone()

    def _format_timer_duration(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if seconds or not parts:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        return " ".join(parts)

    def _remember(self, payload: dict[str, Any]) -> ActionResult:
        text = str(payload.get("text", "")).strip()
        if not text:
            return ActionResult(False, "I need something specific to remember.")
        redacted = redact_sensitive_text(text)
        if redacted != text:
            return ActionResult(False, "I will not store text that looks like a password, token, secret, or API key.")
        memories = self.store.load_collection("memories")
        memory = {
            "id": uuid.uuid4().hex[:8],
            "category": str(payload.get("category", "general")).strip()[:40] or "general",
            "text": redacted[:MAX_MEMORY_TEXT_CHARS],
            "created_at": utc_now_iso(),
        }
        memories = memories[-(MAX_MEMORY_ITEMS - 1) :] if MAX_MEMORY_ITEMS > 1 else []
        memories.append(memory)
        self.store.save_collection("memories", memories)
        return ActionResult(True, f"Remembered: {memory['text']}", {"memory": memory})

    def _list_memories(self, payload: dict[str, Any]) -> ActionResult:
        query = str(payload.get("query", "")).strip().lower()
        memories = self.store.load_collection("memories")
        if query:
            memories = [
                item
                for item in memories
                if query in str(item.get("text", "")).lower() or query in str(item.get("category", "")).lower()
            ]
        if not memories:
            return ActionResult(True, "No local memories matched." if query else "No local memories yet.")
        lines = [
            f"{item.get('id')}: [{item.get('category', 'general')}] {item.get('text', '')}"
            for item in memories[-25:][::-1]
        ]
        return ActionResult(True, "Local memories:\n" + "\n".join(lines), {"memories": memories})

    def _forget_memory(self, payload: dict[str, Any]) -> ActionResult:
        memory_id = str(payload.get("id", "")).strip()
        query = str(payload.get("query", "")).strip().lower()
        if not memory_id and not query:
            return ActionResult(False, "I need a memory id or search text to forget.")
        memories = self.store.load_collection("memories")
        removed: list[dict[str, Any]] = []
        kept: list[dict[str, Any]] = []
        for item in memories:
            matches_id = memory_id and item.get("id") == memory_id
            matches_query = query and query in str(item.get("text", "")).lower()
            if matches_id or matches_query:
                removed.append(item)
            else:
                kept.append(item)
        if not removed:
            target = memory_id or query
            return ActionResult(True, f"No local memory matched '{target}'.")
        self.store.save_collection("memories", kept)
        return ActionResult(True, f"Forgot {len(removed)} local memory item(s).", {"removed": removed})

    def _search_files(self, payload: dict[str, Any]) -> ActionResult:
        query = str(payload.get("query", "")).strip().lower()
        if not query:
            return ActionResult(False, "I need a file search query.")
        approved = self._approved_folders()
        if not approved:
            return ActionResult(False, "No approved folders are configured.")

        matches: list[dict[str, str]] = []
        for folder in approved:
            for path in self._safe_walk(folder):
                if len(matches) >= MAX_FILE_SEARCH_RESULTS:
                    break
                lowered_name = path.name.lower()
                name_match = query in lowered_name
                content_match = False
                snippet = ""
                if path.suffix.lower() in SUPPORTED_TEXT_EXTENSIONS and path.stat().st_size <= MAX_TEXT_FILE_BYTES:
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        text = ""
                    index = text.lower().find(query)
                    content_match = index >= 0
                    if content_match:
                        start = max(0, index - 80)
                        end = min(len(text), index + len(query) + 160)
                        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
                if name_match or content_match:
                    matches.append({"path": str(path), "snippet": snippet})
            if len(matches) >= MAX_FILE_SEARCH_RESULTS:
                break

        if not matches:
            return ActionResult(True, f"No approved files matched '{query}'.")
        message = "\n".join(f"- {item['path']}" for item in matches)
        return ActionResult(True, f"Found {len(matches)} result(s):\n{message}", {"matches": matches})

    def _summarize_file(self, payload: dict[str, Any]) -> ActionResult:
        raw_path = str(payload.get("path", "")).strip()
        if not raw_path:
            return ActionResult(False, "I need a file path to summarize.")
        path = Path(raw_path).resolve()
        if not self._is_approved_path(path):
            raise SecurityViolation("That file is outside approved folders.")
        if path.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
            return ActionResult(False, "Only text-like files can be summarized locally.")
        if path.stat().st_size > MAX_TEXT_FILE_BYTES:
            return ActionResult(False, "That file is too large for local summary preview.")
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            return ActionResult(True, "The file is empty.")
        summary = self._extractive_summary(text)
        return ActionResult(True, f"Local summary:\n{summary}", {"path": str(path), "summary": summary})

    def _create_note(self, payload: dict[str, Any]) -> ActionResult:
        title = str(payload.get("title", "note")).strip() or "note"
        body = str(payload.get("body", "")).strip()
        path = self._create_note_file(title, body)
        if not path.is_file():
            return ActionResult(False, "The note could not be verified after saving.")
        saved_text = path.read_text(encoding="utf-8", errors="replace")
        if body and body not in saved_text:
            return ActionResult(False, "The note file was created, but its contents could not be verified.")
        return ActionResult(
            True,
            f"Note saved locally: {title}",
            {"path": str(path), "title": title, "body": body},
        )

    def _create_note_file(self, title: str, body: str) -> Path:
        safe_title = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-")[:80] or "note"
        notes_dir = self._notes_dir()
        notes_dir.mkdir(parents=True, exist_ok=True)
        path = notes_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{safe_title}.md"
        path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        return path

    def _list_notes(self, _payload: dict[str, Any]) -> ActionResult:
        notes_dir = self._notes_dir()
        notes_dir.mkdir(parents=True, exist_ok=True)
        notes = sorted(notes_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not notes:
            return ActionResult(True, "No local notes yet.")
        lines = [f"- {path.name}" for path in notes[:25]]
        return ActionResult(True, "Local notes:\n" + "\n".join(lines), {"notes": [str(path) for path in notes[:25]]})

    def _read_note(self, payload: dict[str, Any]) -> ActionResult:
        query = str(payload.get("query", "")).strip().lower()
        if not query:
            return ActionResult(False, "I need a note name or search term.")
        normalized_query = re.sub(r"[^a-z0-9]+", " ", query).strip()
        notes_dir = self._notes_dir()
        notes_dir.mkdir(parents=True, exist_ok=True)
        matches = []
        for path in notes_dir.glob("*.md"):
            name = path.name.lower()
            normalized_name = re.sub(r"[^a-z0-9]+", " ", name).strip()
            if query in name or normalized_query in normalized_name:
                matches.append(path)
        if not matches:
            return ActionResult(True, f"No local note matched '{query}'.")
        path = sorted(matches, key=lambda item: item.stat().st_mtime, reverse=True)[0]
        if path.stat().st_size > MAX_TEXT_FILE_BYTES:
            return ActionResult(False, "That note is too large to preview.")
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        preview = text[:1800] if text else "(empty note)"
        return ActionResult(True, f"{path.name}:\n{preview}", {"path": str(path)})

    def _scan_note(self, payload: dict[str, Any]) -> ActionResult:
        path = self._resolve_scan_target(payload)
        if path is None:
            return ActionResult(False, "I need an image path, or a locally captured screenshot to scan.")
        if not self._is_approved_path(path) and not self._is_app_data_path(path):
            raise SecurityViolation("That image is outside approved folders and Jarvis data folders.")

        result = OcrService(self.store.settings).scan_image(path)
        if not result.ok:
            return ActionResult(False, result.error)

        title = f"Scan {path.stem}"
        body = (
            f"Source: {path}\n\n"
            f"OCR engine: {result.engine}\n\n"
            "## Extracted Text\n\n"
            f"{result.text}\n"
        )
        note_path = self._create_note_file(title, body)
        preview = re.sub(r"\s+", " ", result.text).strip()[:700]
        return ActionResult(
            True,
            f"Scanned locally with {result.engine}. Created note: {note_path}\n\n{preview}",
            {"path": str(path), "note_path": str(note_path), "text": result.text},
        )

    def _capture_screen(self, _payload: dict[str, Any]) -> ActionResult:
        screenshots_dir = self._screenshots_dir()
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        path = screenshots_dir / f"screenshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        image = ImageGrab.grab()
        image.save(path)
        return ActionResult(True, f"Screenshot captured locally: {path}", {"path": str(path)})

    def _open_app(self, payload: dict[str, Any]) -> ActionResult:
        app = self._command_key(str(payload.get("app", "")))
        command = APPROVED_APP_COMMANDS.get(app)
        if not command:
            return ActionResult(False, self._app_allowlist_message(app))
        try:
            launched = self._launch_app_command(command)
        except FileNotFoundError as exc:
            return ActionResult(False, f"'{app}' is approved, but Windows could not start it: {exc}")
        return ActionResult(True, f"Opening {app}.", {"app": app, **launched})

    def _open_notepad_text(self, payload: dict[str, Any]) -> ActionResult:
        text = str(payload.get("text", "")).strip()
        if not text:
            return ActionResult(False, "I need text to put in Notepad.")
        title = str(payload.get("title", "Jarvis output")).strip() or "Jarvis output"
        safe_title = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-")[:80] or "jarvis-output"
        notepad_dir = self._notepad_dir()
        notepad_dir.mkdir(parents=True, exist_ok=True)
        path = notepad_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{safe_title}.txt"
        path.write_text(text + "\n", encoding="utf-8")
        if not path.is_file():
            return ActionResult(False, "The Notepad text file could not be verified after saving.")

        command = APPROVED_APP_COMMANDS.get("notepad")
        if not command:
            return ActionResult(False, "Notepad is not configured in the approved app list.")
        try:
            launched = self._launch_app_command([*command, str(path)])
        except FileNotFoundError as exc:
            return ActionResult(
                False,
                f"Saved the text locally, but Windows could not open Notepad: {exc}. File: {path}",
                {"path": str(path), "text": text},
            )
        return ActionResult(
            True,
            f"Opened Notepad with generated text: {path}",
            {"path": str(path), "text": text, **launched},
        )

    def _launch_app_command(self, command: list[str]) -> dict[str, Any]:
        try:
            process = subprocess.Popen(command)
            return {"pid": process.pid, "method": "popen"}
        except FileNotFoundError:
            if os.name != "nt":
                raise

        executable = command[0]
        parameters = subprocess.list2cmdline(command[1:]) if len(command) > 1 else None
        result = ctypes.windll.shell32.ShellExecuteW(None, "open", executable, parameters, None, 1)
        if result <= 32:
            raise FileNotFoundError(f"ShellExecute failed with code {result} for {executable}")
        return {"method": "shellexecute"}

    def _app_allowlist_message(self, app: str = "") -> str:
        allowed = ", ".join(sorted(APPROVED_APP_COMMANDS))
        prefix = f"'{app}' is not in the approved app list. " if app else ""
        return f"{prefix}Approved apps are: {allowed}."

    def _run_shell_command(self, payload: dict[str, Any]) -> ActionResult:
        command_key = self._command_key(str(payload.get("command", "")))
        spec = APPROVED_SHELL_COMMANDS.get(command_key)
        if spec is None:
            return ActionResult(False, self._shell_allowlist_message(command_key))

        command = spec.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            return ActionResult(False, f"Approved shell command '{command_key}' is misconfigured.")

        cwd = Path(str(spec.get("cwd", WORKSPACE_ROOT))).resolve()
        workspace = WORKSPACE_ROOT.resolve()
        if cwd != workspace and workspace not in cwd.parents:
            return ActionResult(False, f"Approved shell command '{command_key}' has an unsafe working directory.")

        timeout = int(spec.get("timeout_seconds", 30) or 30)
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=max(1, min(timeout, 300)),
                shell=False,
            )
        except FileNotFoundError:
            return ActionResult(False, f"Approved shell command '{command_key}' could not start because '{command[0]}' was not found.")
        except subprocess.TimeoutExpired:
            return ActionResult(False, f"Approved shell command '{command_key}' timed out after {timeout} seconds.")

        output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip())
        output = output[:4000] if output else "(no output)"
        status = "completed" if completed.returncode == 0 else f"exited with code {completed.returncode}"
        return ActionResult(
            completed.returncode == 0,
            f"Shell command '{command_key}' {status}:\n{output}",
            {"command": command_key, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr},
        )

    def _shell_allowlist_message(self, command_key: str = "") -> str:
        allowed = ", ".join(sorted(APPROVED_SHELL_COMMANDS))
        prefix = f"Shell command '{command_key}' is not approved. " if command_key else ""
        return f"{prefix}Approved shell commands are: {allowed}."

    def _command_key(self, value: str) -> str:
        lowered = value.lower().strip().strip(" ,.:;?!")
        lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    def _calendar_today(self, _payload: dict[str, Any]) -> ActionResult:
        try:
            events = self.google.calendar_today()
        except GoogleServiceError as exc:
            return ActionResult(False, str(exc))
        return self._calendar_results("Today's calendar", events)

    def _calendar_search(self, payload: dict[str, Any]) -> ActionResult:
        query = str(payload.get("query", "")).strip()
        try:
            events = self.google.calendar_search(query)
        except GoogleServiceError as exc:
            return ActionResult(False, str(exc))
        return self._calendar_results(f"Calendar results for '{query}'", events)

    def _calendar_create(self, payload: dict[str, Any]) -> ActionResult:
        title = str(payload.get("title", "")).strip()
        time_text = str(payload.get("time_text", "")).strip()
        try:
            event = self.google.calendar_create(title, time_text)
        except GoogleServiceError as exc:
            return ActionResult(False, str(exc))
        return ActionResult(
            True,
            f"Calendar event created: {event['title']} at {self._format_event_time(event['start'])}",
            {"event": event},
        )

    def _gmail_search(self, payload: dict[str, Any]) -> ActionResult:
        query = str(payload.get("query", "")).strip()
        try:
            messages = self.google.gmail_search(query)
        except GoogleServiceError as exc:
            return ActionResult(False, str(exc))
        if not messages:
            return ActionResult(True, f"No Gmail messages matched '{query}'.", {"messages": []})
        lines = [
            f"{item['id']}: {item['subject']} - {item['from']}\n  {item['snippet'][:180]}"
            for item in messages
        ]
        return ActionResult(True, f"Gmail results for '{query}':\n" + "\n".join(lines), {"messages": messages})

    def _gmail_draft(self, payload: dict[str, Any]) -> ActionResult:
        to = str(payload.get("to", "")).strip()
        subject = str(payload.get("subject", "")).strip() or "Jarvis draft"
        body = str(payload.get("body", "")).strip()
        try:
            draft = self.google.gmail_create_draft(to, subject, body)
        except GoogleServiceError as exc:
            return ActionResult(False, str(exc))
        return ActionResult(True, f"Gmail draft created: {draft['id']} to {draft['to']}", {"draft": draft})

    def _gmail_send(self, payload: dict[str, Any]) -> ActionResult:
        draft_id = str(payload.get("draft_id", "")).strip()
        try:
            sent = self.google.gmail_send_draft(draft_id)
        except GoogleServiceError as exc:
            return ActionResult(False, str(exc))
        return ActionResult(True, f"Gmail draft {draft_id} sent. Message id: {sent['message_id']}", {"sent": sent})

    def _calendar_results(self, heading: str, events: list[dict[str, str]]) -> ActionResult:
        if not events:
            return ActionResult(True, f"{heading}: no events found.", {"events": []})
        lines = [f"{event['id']}: {self._format_event_time(event['start'])} - {event['title']}" for event in events]
        return ActionResult(True, heading + ":\n" + "\n".join(lines), {"events": events})

    def _format_event_time(self, raw: str) -> str:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone().strftime("%a %b %d, %I:%M %p")
        except ValueError:
            return raw

    def _extractive_summary(self, text: str, sentence_limit: int = 4) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", clean) if item.strip()]
        if len(sentences) <= sentence_limit:
            return " ".join(sentences)[:1800]
        words = re.findall(r"[a-zA-Z]{3,}", clean.lower())
        stop_words = {
            "and", "are", "but", "for", "from", "has", "have", "into", "its", "not", "that", "the",
            "their", "there", "these", "they", "this", "was", "were", "will", "with", "you", "your",
        }
        frequencies: dict[str, int] = {}
        for word in words:
            if word not in stop_words:
                frequencies[word] = frequencies.get(word, 0) + 1
        ranked = sorted(
            enumerate(sentences),
            key=lambda pair: sum(frequencies.get(word, 0) for word in re.findall(r"[a-zA-Z]{3,}", pair[1].lower())),
            reverse=True,
        )[:sentence_limit]
        selected = [sentence for _index, sentence in sorted(ranked, key=lambda pair: pair[0])]
        return " ".join(selected)[:1800]

    def _approved_folders(self) -> list[Path]:
        folders = []
        for raw in self.store.settings.get("approved_folders", []):
            try:
                path = Path(raw).resolve()
            except OSError:
                continue
            if path.exists() and path.is_dir():
                folders.append(path)
        return folders

    def _is_approved_path(self, path: Path) -> bool:
        return any(path == folder or folder in path.parents for folder in self._approved_folders())

    def _is_app_data_path(self, path: Path) -> bool:
        local_roots = [self.store.base_dir.resolve(), self._notes_dir(), self._screenshots_dir()]
        return any(path == root or root in path.parents for root in local_roots)

    def _notes_dir(self) -> Path:
        return Path(self.store.settings.get("notes_folder", self.store.base_dir / "notes")).resolve()

    def _notepad_dir(self) -> Path:
        return Path(self.store.settings.get("notepad_folder", self.store.base_dir / "notepad")).resolve()

    def _screenshots_dir(self) -> Path:
        return Path(self.store.settings.get("screenshots_folder", self.store.base_dir / "screenshots")).resolve()

    def _resolve_scan_target(self, payload: dict[str, Any]) -> Path | None:
        source = str(payload.get("source", "")).strip().lower()
        if source == "latest_screenshot":
            screenshots_dir = self._screenshots_dir()
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            images = [
                path
                for path in screenshots_dir.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            ]
            if not images:
                return None
            return sorted(images, key=lambda item: item.stat().st_mtime, reverse=True)[0].resolve()

        raw_path = str(payload.get("path", "")).strip().strip('"')
        if not raw_path:
            return None
        return Path(raw_path).expanduser().resolve()

    def _safe_walk(self, folder: Path) -> Iterator[Path]:
        seen = 0
        for root, dirs, files in os.walk(folder):
            dirs[:] = [
                name
                for name in dirs
                if not name.startswith(".")
                and name not in {"node_modules", "__pycache__"}
                and not (Path(root) / name).is_symlink()
            ]
            for name in files:
                if seen >= MAX_SAFE_WALK_FILES:
                    return
                if name.startswith("."):
                    continue
                path = Path(root) / name
                try:
                    resolved = path.resolve()
                    if path.is_symlink():
                        continue
                    if self._is_approved_path(resolved):
                        seen += 1
                        yield resolved
                except OSError:
                    continue
