from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .actions import ActionRegistry, ActionResult, ApprovalCallback
from .app_config import ACTIVATION_PHRASE, APPROVED_APP_COMMANDS, APPROVED_SHELL_COMMANDS
from .cloud_text import CloudTextClient
from .command_intents import parse_email_draft_command, parse_note_command, parse_reminder_command, parse_timer_command
from .local_speech import SLEEP_PHRASES, STARTUP_PHRASES, normalize_voice_phrase
from .security import SecurityManager, SecurityViolation
from .storage import JsonStore, redact_sensitive_text, utc_now_iso
from .tool_planner import ToolPlan, ToolPlanner


@dataclass
class ParsedCommand:
    action_id: str | None
    payload: dict[str, Any]
    direct_response: str | None = None
    jarvis_invoked: bool = False


class CommandParser:
    def __init__(self, wake_phrase: str = "jarvis") -> None:
        self.wake_phrase = wake_phrase.lower()

    def parse(self, text: str) -> ParsedCommand:
        raw = text.strip().strip(" ,.:;?!")
        lowered = raw.lower().strip()
        jarvis_invoked = False
        if lowered.startswith(self.wake_phrase):
            jarvis_invoked = True
            raw = raw[len(self.wake_phrase):].strip(" ,.:;?!")
            lowered = raw.lower()
        command_key = normalize_voice_phrase(raw)

        if command_key in {"help", "what can you do"} or self._is_tool_help_request(command_key):
            return ParsedCommand(None, {}, self._help_text(), jarvis_invoked)
        if self._is_sleep_phrase(lowered):
            return ParsedCommand(None, {}, "SLEEP_MODE", jarvis_invoked)
        if jarvis_invoked and self._is_startup_phrase(lowered):
            return ParsedCommand(None, {}, "Welcome Home Sir.", jarvis_invoked)
        if lowered == ACTIVATION_PHRASE.replace("'", "").lower() or lowered == ACTIVATION_PHRASE.lower():
            return ParsedCommand(None, {}, "Voice activation phrase recognized. In voice mode, follow it with: Jarvis, then your command.", jarvis_invoked)

        notepad_prompt = self._response_to_notepad_prompt(raw)
        if notepad_prompt:
            if not jarvis_invoked:
                return ParsedCommand(None, {}, "UNKNOWN_WITHOUT_JARVIS", jarvis_invoked)
            return ParsedCommand("workflow.response_to_notepad", {"prompt": notepad_prompt}, jarvis_invoked=jarvis_invoked)

        note_prompt = self._response_to_note_prompt(raw)
        if note_prompt:
            if not jarvis_invoked:
                return ParsedCommand(None, {}, "UNKNOWN_WITHOUT_JARVIS", jarvis_invoked)
            return ParsedCommand("workflow.response_to_note", {"prompt": note_prompt}, jarvis_invoked=jarvis_invoked)

        save_last_note = self._save_last_to_note_payload(raw)
        if save_last_note:
            return ParsedCommand("workflow.save_last_to_note", save_last_note, jarvis_invoked=jarvis_invoked)

        sequence_steps = self._split_sequence(raw)
        if len(sequence_steps) > 1:
            return ParsedCommand("workflow.sequence", {"steps": sequence_steps}, jarvis_invoked=jarvis_invoked)

        if lowered in {"health check", "system health", "diagnostics", "run diagnostics"}:
            return ParsedCommand("system.health", {}, jarvis_invoked=jarvis_invoked)
        if lowered in {"google status", "gmail status", "calendar connection status"}:
            return ParsedCommand("google.status", {}, jarvis_invoked=jarvis_invoked)
        if "security status" in lowered or lowered == "status":
            return ParsedCommand(None, {}, "SECURITY_STATUS", jarvis_invoked)
        if lowered in {"voice status", "voice settings", "tts status", "sound settings"}:
            return ParsedCommand("voice.status", {}, jarvis_invoked=jarvis_invoked)
        if lowered in {"test voice", "voice test", "test your voice"}:
            return ParsedCommand("voice.test", {}, jarvis_invoked=jarvis_invoked)

        voice_provider = re.match(
            r"^(?:(?:set|use|switch to) (?:the )?(?P<provider>openai|windows|sapi|local|offline|elevenlabs|azure)(?: voice| tts| provider)?|set (?:voice|tts) provider (?P<provider2>openai|windows|sapi|local|offline|elevenlabs|azure))$",
            raw,
            re.I,
        )
        if voice_provider:
            return ParsedCommand(
                "voice.set_provider",
                {"provider": voice_provider.group("provider") or voice_provider.group("provider2")},
                jarvis_invoked=jarvis_invoked,
            )

        voice_cache = re.match(r"^(?P<state>enable|disable|turn on|turn off) (?:the )?(?:voice|reply audio|tts) cache$", raw, re.I)
        if voice_cache:
            enabled = voice_cache.group("state").lower() in {"enable", "turn on"}
            return ParsedCommand("voice.set_cache", {"enabled": enabled}, jarvis_invoked=jarvis_invoked)

        if self._is_shell_list_request(command_key):
            return ParsedCommand(None, {"message": self._shell_allowlist_text()}, "SHELL_COMMAND_LIST", jarvis_invoked)

        shell_payload = self._parse_shell_command(raw)
        if shell_payload:
            return ParsedCommand("automation.shell", shell_payload, jarvis_invoked=jarvis_invoked)
        if self._looks_like_shell_request(command_key):
            return ParsedCommand(
                None,
                {"message": self._shell_allowlist_text(self._shell_candidate(raw) or raw)},
                "SHELL_COMMAND_NOT_ALLOWED",
                jarvis_invoked,
            )

        if command_key in {"what time is it", "time", "current time"}:
            return ParsedCommand(None, {}, "LOCAL_TIME", jarvis_invoked)
        if command_key in {"what date is it", "date", "todays date"}:
            return ParsedCommand(None, {}, "LOCAL_DATE", jarvis_invoked)
        if self._is_reminder_list_request(command_key):
            return ParsedCommand("reminders.list", {}, jarvis_invoked=jarvis_invoked)

        if self._is_timer_list_request(command_key):
            return ParsedCommand("timers.list", {}, jarvis_invoked=jarvis_invoked)

        timer_payload = parse_timer_command(raw)
        if timer_payload:
            return ParsedCommand("timers.create", timer_payload, jarvis_invoked=jarvis_invoked)

        cancel_timer = re.match(r"^(?:cancel|stop|delete) timer (?P<id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if cancel_timer:
            return ParsedCommand("timers.cancel", {"id": cancel_timer.group("id")}, jarvis_invoked=jarvis_invoked)

        reminder_payload = parse_reminder_command(raw)
        if reminder_payload:
            return ParsedCommand("reminders.create", reminder_payload, jarvis_invoked=jarvis_invoked)

        note_payload = parse_note_command(raw)
        if note_payload:
            return ParsedCommand("files.create_note", note_payload, jarvis_invoked=jarvis_invoked)

        remember = re.match(r"^remember(?: that)? (?P<text>.+)$", raw, re.I)
        if remember:
            return ParsedCommand("memory.remember", {"text": remember.group("text"), "category": "general"}, jarvis_invoked=jarvis_invoked)

        if command_key in {"what do you remember", "show memories", "list memories", "list memory"}:
            return ParsedCommand("memory.list", {}, jarvis_invoked=jarvis_invoked)

        memory_about = re.match(r"^what do you remember about (?P<query>.+)$", raw, re.I)
        if memory_about:
            return ParsedCommand("memory.list", {"query": memory_about.group("query")}, jarvis_invoked=jarvis_invoked)

        forget_memory = re.match(r"^forget memory (?P<id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if forget_memory:
            return ParsedCommand("memory.forget", {"id": forget_memory.group("id")}, jarvis_invoked=jarvis_invoked)

        forget_that = re.match(r"^forget(?: that)? (?P<query>.+)$", raw, re.I)
        if forget_that:
            return ParsedCommand("memory.forget", {"query": forget_that.group("query")}, jarvis_invoked=jarvis_invoked)

        edit_reminder = re.match(
            r"^(?:edit|update) reminder (?P<id>[a-zA-Z0-9_-]+) to (?P<title>.+?) "
            r"(?:at|on|for) (?P<due>.+)$",
            raw,
            re.I,
        )
        if edit_reminder:
            return ParsedCommand(
                "reminders.edit",
                {
                    "id": edit_reminder.group("id"),
                    "title": edit_reminder.group("title").strip(),
                    "due_text": edit_reminder.group("due").strip(),
                },
                jarvis_invoked=jarvis_invoked,
            )

        reschedule_reminder = re.match(
            r"^reschedule reminder (?P<id>[a-zA-Z0-9_-]+) (?:to|for|at) (?P<due>.+)$",
            raw,
            re.I,
        )
        if reschedule_reminder:
            return ParsedCommand(
                "reminders.edit",
                {"id": reschedule_reminder.group("id"), "due_text": reschedule_reminder.group("due").strip()},
                jarvis_invoked=jarvis_invoked,
            )

        delete_reminder = re.match(r"^(?:delete|remove) reminder (?P<id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if delete_reminder:
            return ParsedCommand("reminders.delete", {"id": delete_reminder.group("id")}, jarvis_invoked=jarvis_invoked)

        complete_reminder = re.match(r"^(?:complete|finish|done) reminder (?P<id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if complete_reminder:
            return ParsedCommand("reminders.complete", {"id": complete_reminder.group("id")}, jarvis_invoked=jarvis_invoked)

        search_files = re.match(r"^(?:search|find) files? (?:for )?(?P<query>.+)$", raw, re.I)
        if search_files:
            return ParsedCommand("files.search", {"query": search_files.group("query")}, jarvis_invoked=jarvis_invoked)

        summarize = re.match(r"^summarize file (?P<path>.+)$", raw, re.I)
        if summarize:
            return ParsedCommand("files.summarize", {"path": summarize.group("path")}, jarvis_invoked=jarvis_invoked)

        if self._is_note_list_request(command_key):
            return ParsedCommand("notes.list", {}, jarvis_invoked=jarvis_invoked)

        read_note = re.match(r"^(?:read|open|show) note (?P<query>.+)$", raw, re.I)
        if read_note:
            return ParsedCommand("notes.read", {"query": read_note.group("query")}, jarvis_invoked=jarvis_invoked)

        if self._is_latest_screenshot_scan_request(command_key):
            return ParsedCommand("notes.scan", {"source": "latest_screenshot"}, jarvis_invoked=jarvis_invoked)

        scan_image = re.match(r"^(?:scan|ocr|read text from) (?:image|file)? ?(?P<path>.+)$", raw, re.I)
        if scan_image:
            return ParsedCommand("notes.scan", {"path": scan_image.group("path")}, jarvis_invoked=jarvis_invoked)

        if lowered in {"take screenshot", "capture screen", "scan screen"}:
            return ParsedCommand("screen.capture", {}, jarvis_invoked=jarvis_invoked)

        app_name = self._app_candidate(raw)
        if app_name:
            return ParsedCommand("desktop.open_app", {"app": app_name}, jarvis_invoked=jarvis_invoked)

        calendar_create = re.match(
            r"^(?:create|schedule|set) (?:a )?(?:calendar )?(?:event|appointment|meeting) (?P<title>.+?)(?: at (?P<time>.+))?$",
            raw,
            re.I,
        )
        if calendar_create:
            return ParsedCommand(
                "calendar.create",
                {"title": calendar_create.group("title").strip(), "time_text": (calendar_create.group("time") or "").strip()},
                jarvis_invoked=jarvis_invoked,
            )

        calendar_search = re.match(r"^(?:search|find) calendar (?:for )?(?P<query>.+)$", raw, re.I)
        if calendar_search:
            return ParsedCommand("calendar.search", {"query": calendar_search.group("query").strip()}, jarvis_invoked=jarvis_invoked)

        if "calendar" in lowered or "schedule" in lowered or "meetings" in lowered:
            if any(word in lowered for word in ["today", "now", "next"]):
                return ParsedCommand("calendar.read_today", {}, jarvis_invoked=jarvis_invoked)
            return ParsedCommand("calendar.search", {"query": raw}, jarvis_invoked=jarvis_invoked)

        email_payload = parse_email_draft_command(raw)
        if email_payload:
            return ParsedCommand("gmail.draft", email_payload, jarvis_invoked=jarvis_invoked)

        send_draft = re.match(r"^(?:send|send gmail|send email) (?:email )?draft (?P<draft_id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if send_draft:
            return ParsedCommand("gmail.send", {"draft_id": send_draft.group("draft_id")}, jarvis_invoked=jarvis_invoked)

        gmail = re.match(r"^(?:search|find) (?:gmail|email) (?:for )?(?P<query>.+)$", raw, re.I)
        if gmail:
            return ParsedCommand("gmail.search", {"query": gmail.group("query")}, jarvis_invoked=jarvis_invoked)

        if jarvis_invoked:
            return ParsedCommand("conversation.answer", {"prompt": raw}, jarvis_invoked=jarvis_invoked)
        return ParsedCommand(None, {}, "UNKNOWN_WITHOUT_JARVIS")

    def _help_text(self) -> str:
        return (
            "Voice mode starts automatically. Say Wake up Daddy's Home, then say Jarvis, followed by a command. "
            "Try: Jarvis, remind me to call Alex at 4 PM; list reminders; complete reminder ABC123; "
            "set a timer for 5 minutes; list timers; search files for budget; "
            "create note Project saying First draft is ready; list notes; read note Project; "
            "scan latest screenshot; remember that I prefer short answers; what do you remember; health check; voice status; "
            "take screenshot; open notepad; open paint; what meetings do I have today; "
            "draft email to Sam saying I will send the proposal Friday; "
            "draft an email to Sam and put it in Notepad; "
            "draft an email to Sam and save it to my notes; save it to my notes; "
            "take a note that the budget is approved and then show my notes; Jarvis, bedtime; security status."
        )

    def _response_to_notepad_prompt(self, raw: str) -> str:
        raw = self._clean_request(raw)
        match = re.match(
            r"^(?P<prompt>.+?)\s+(?:and\s+then|then|and)\s+"
            r"(?:(?:put|paste|write|save)\s+(?:it|that|the\s+(?:answer|response|draft|result|text|email))?"
            r"|open\s+(?:it|that|the\s+(?:answer|response|draft|result|text|email)))\s*"
            r"(?:in|into|to|as)\s+(?:a\s+)?(?:notepad|notepad file|text file)$",
            raw,
            re.I,
        )
        if not match:
            return ""
        return match.group("prompt").strip(" ,.:;?!")

    def _response_to_note_prompt(self, raw: str) -> str:
        raw = self._clean_request(raw)
        match = re.match(
            r"^(?P<prompt>.+?)\s+(?:and\s+then|then|and)\s+"
            r"(?:(?:put|paste|write|save|add|store)\s+(?:it|that|this|the\s+(?:answer|response|reply|draft|result|text|email|message))?)\s*"
            r"(?:in|into|to|as)\s+(?:a\s+)?(?:my\s+)?(?:notes?|note|text note)$",
            raw,
            re.I,
        )
        if not match:
            return ""
        return match.group("prompt").strip(" ,.:;?!")

    def _save_last_to_note_payload(self, raw: str) -> dict[str, str] | None:
        text = self._clean_request(raw)
        reference = r"(?:it|that|this|the\s+(?:last\s+)?(?:answer|response|reply|draft|result|text|email|email\s+content|message|content)|last\s+(?:answer|response|reply|draft|message)|previous\s+(?:answer|response|reply|draft|message))"
        destination = r"(?:a\s+)?(?:my\s+)?(?:notes?|note|text note)"
        if re.match(rf"^(?:save|add|put|store|copy|write)\s+{reference}\s+(?:in|into|to|as)\s+{destination}$", text, re.I):
            return {"title": self._note_reference_title(text)}
        if re.match(rf"^(?:create|make|write)\s+(?:a\s+)?note\s+(?:from|of|with)\s+{reference}$", text, re.I):
            return {"title": self._note_reference_title(text)}
        return None

    def _note_reference_title(self, text: str) -> str:
        lowered = text.lower()
        if "email" in lowered or "draft" in lowered:
            return "Saved Email Draft"
        if "message" in lowered:
            return "Saved Message"
        return "Saved Jarvis Response"

    def _split_sequence(self, raw: str) -> list[str]:
        parts = [part.strip(" ,.:;?!") for part in re.split(r"\s*(?:;|\b(?:and\s+then|then)\b)\s*", raw, flags=re.I)]
        parts = [self._strip_step_wake(part) for part in parts if part]
        if len(parts) < 2:
            return []
        if not all(self._looks_like_sequence_step(part) for part in parts):
            return []
        return parts[:8]

    def _strip_step_wake(self, raw: str) -> str:
        lowered = raw.lower().lstrip()
        if lowered.startswith(self.wake_phrase):
            return raw[len(self.wake_phrase):].strip(" ,.:;?!")
        return raw.strip(" ,.:;?!")

    def _looks_like_sequence_step(self, raw: str) -> bool:
        step = self._strip_step_wake(raw)
        if not step:
            return False
        command_key = normalize_voice_phrase(step)
        if command_key in {
            "help",
            "what can you do",
            "health check",
            "system health",
            "diagnostics",
            "run diagnostics",
            "google status",
            "gmail status",
            "calendar connection status",
            "security status",
            "status",
            "voice status",
            "voice settings",
            "tts status",
            "sound settings",
            "test voice",
            "voice test",
            "test your voice",
            "what time is it",
            "time",
            "current time",
            "what date is it",
            "date",
            "todays date",
            "take screenshot",
            "capture screen",
            "scan screen",
        }:
            return True
        return bool(
            self._is_tool_help_request(command_key)
            or self._is_sleep_phrase(command_key)
            or self._is_startup_phrase(command_key)
            or self._is_shell_list_request(command_key)
            or self._parse_shell_command(step)
            or self._looks_like_shell_request(command_key)
            or self._is_reminder_list_request(command_key)
            or self._is_timer_list_request(command_key)
            or self._is_note_list_request(command_key)
            or self._is_latest_screenshot_scan_request(command_key)
            or self._response_to_note_prompt(step)
            or self._save_last_to_note_payload(step)
            or parse_timer_command(step)
            or parse_reminder_command(step)
            or parse_note_command(step)
            or parse_email_draft_command(step)
            or self._app_candidate(step)
            or re.match(r"^(?:cancel|stop|delete) timer [a-zA-Z0-9_-]+$", step, re.I)
            or re.match(r"^(?:delete|remove|reschedule|complete|finish|done|edit|update) reminder\b", step, re.I)
            or re.match(r"^(?:read|open|show) note\b", step, re.I)
            or re.match(r"^(?:scan|ocr|read text from) (?:image|file)? ?", step, re.I)
            or re.match(r"^(?:search|find) files? ", step, re.I)
            or re.match(r"^summarize file ", step, re.I)
            or re.match(r"^(?:search|find) (?:gmail|email) ", step, re.I)
            or re.match(r"^(?:send|send gmail|send email) (?:email )?draft ", step, re.I)
            or re.match(r"^(?:create|schedule|set) (?:a )?(?:calendar )?(?:event|appointment|meeting) ", step, re.I)
            or re.match(r"^(?:search|find) calendar ", step, re.I)
            or re.search(r"\b(calendar|schedule|meetings)\b", command_key)
        )

    def _is_sleep_phrase(self, lowered: str) -> bool:
        normalized = normalize_voice_phrase(lowered)
        return normalized in SLEEP_PHRASES

    def _is_startup_phrase(self, lowered: str) -> bool:
        normalized = normalize_voice_phrase(lowered)
        return normalized in STARTUP_PHRASES

    def _is_tool_help_request(self, lowered: str) -> bool:
        return bool(
            re.search(r"\b(what|which|show|list|tell)\b.*\b(tools|commands|abilities|capabilities)\b", lowered)
            or re.search(r"\b(tools|commands|abilities|capabilities)\b.*\b(have|access|available|use|can)\b", lowered)
            or re.search(r"\b(access|available)\b.*\b(notes|reminders|timers|tools)\b", lowered)
        )

    def _is_note_list_request(self, command_key: str) -> bool:
        if command_key in {
            "list notes",
            "show notes",
            "show my notes",
            "show me my notes",
            "read my notes",
            "tell me my notes",
            "what are my notes",
            "what are the notes",
            "what notes do i have",
            "what notes do you have",
            "what notes are saved",
            "what notes are stored",
        }:
            return True
        return bool(
            re.search(r"\b(list|show|read|tell)\b.*\b(my )?notes\b", command_key)
            or re.search(r"\bwhat\b.*\b(?:are|is)\b.*\b(my |the )?notes\b", command_key)
            or re.search(r"\bwhat\b.*\bnotes\b.*\b(are|have|saved|stored)\b", command_key)
            or re.search(r"\bdo i have\b.*\bnotes\b", command_key)
        )

    def _is_reminder_list_request(self, command_key: str) -> bool:
        if command_key in {"list reminders", "show reminders", "show my reminders", "what are my reminders"}:
            return True
        return bool(
            re.search(r"\b(list|show)\b.*\b(my )?reminders\b", command_key)
            or re.search(r"\bwhat\b.*\breminders\b.*\b(have|active|upcoming)\b", command_key)
            or re.search(r"\bdo i have\b.*\breminders\b", command_key)
        )

    def _is_timer_list_request(self, command_key: str) -> bool:
        if command_key in {"list timers", "show timers", "show my timers", "what timers are running", "show active timers", "active timers"}:
            return True
        return bool(
            re.search(r"\b(list|show)\b.*\b(my )?timers\b", command_key)
            or re.search(r"\bwhat\b.*\btimers\b.*\b(running|active|set)\b", command_key)
            or re.search(r"\bdo i have\b.*\btimers\b", command_key)
        )

    def _is_latest_screenshot_scan_request(self, command_key: str) -> bool:
        if command_key in {"scan latest screenshot", "scan screenshot", "scan this screenshot", "ocr latest screenshot"}:
            return True
        if "screenshot" not in command_key:
            return False
        has_target = bool(re.search(r"\b(last|latest|recent|previous|this)\b", command_key))
        has_intent = bool(re.search(r"\b(look|read|scan|ocr|analyze|analyse|inspect|check)\b", command_key))
        return has_target and has_intent

    def _is_shell_list_request(self, command_key: str) -> bool:
        return bool(
            re.search(r"\b(list|show|what)\b.*\b(shell|terminal|commands?)\b", command_key)
            and re.search(r"\b(allowed|approved|allowlisted|available|can|run)\b", command_key)
        )

    def _parse_shell_command(self, raw: str) -> dict[str, str] | None:
        candidate = self._shell_candidate(raw)
        if not candidate:
            return None
        command_key = self._command_key(candidate)
        if command_key in APPROVED_SHELL_COMMANDS:
            return {"command": command_key}
        return None

    def _looks_like_shell_request(self, command_key: str) -> bool:
        return bool(
            re.search(r"\b(run|execute|start)\b.*\b(shell|powershell|terminal|commands?)\b", command_key)
            or re.match(r"^(run|execute) ", command_key)
        )

    def _shell_candidate(self, raw: str) -> str:
        match = re.match(
            r"^(?:run|execute|start)\s+(?:(?:an?|the)\s+)?(?:(?:approved|allowed|allowlisted)\s+)?"
            r"(?:(?:shell|terminal|powershell)\s+)?(?:command\s+)?(?P<command>.+)$",
            raw,
            re.I,
        )
        if not match:
            return ""
        return match.group("command").strip(" ,.:;?!")

    def _shell_allowlist_text(self, attempted: str = "") -> str:
        allowed = ", ".join(sorted(APPROVED_SHELL_COMMANDS))
        attempted_key = self._command_key(attempted)
        prefix = f"'{attempted_key}' is not approved. " if attempted_key else ""
        return f"{prefix}Approved shell commands are: {allowed}."

    def _clean_request(self, raw: str) -> str:
        text = raw.strip().strip(" ,.:;?!")
        return re.sub(
            r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+|i need you to\s+|i want you to\s+)",
            "",
            text,
            flags=re.I,
        ).strip()

    def _app_candidate(self, raw: str) -> str:
        match = re.match(r"^(?:open|launch|start)\s+(?:(?:the)\s+)?(?P<app>.+)$", raw, re.I)
        if not match:
            return ""
        app = self._command_key(match.group("app"))
        app = re.sub(r"\s+(?:app|application)$", "", app).strip()
        if app in APPROVED_APP_COMMANDS:
            return app
        return app

    def _command_key(self, value: str) -> str:
        lowered = value.lower().strip().strip(" ,.:;?!")
        lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()


class AssistantRuntime:
    def __init__(self, store: JsonStore, actions: ActionRegistry, security: SecurityManager) -> None:
        self.store = store
        self.actions = actions
        self.security = security
        self.parser = CommandParser(str(store.settings.get("wake_phrase", "jarvis")))
        self.cloud = CloudTextClient(security, store.settings, store)
        self.tool_planner = ToolPlanner()
        self.last_result: ActionResult | None = None

    def handle(self, text: str, approve: ApprovalCallback | None = None) -> ActionResult:
        self.store.append_history("user", text)
        parsed = self.parser.parse(text)
        try:
            result = self._execute_parsed(parsed, approve)
        except SecurityViolation as exc:
            result = ActionResult(False, f"Security policy: {exc}")
        except Exception as exc:
            result = ActionResult(False, f"Error: {exc}")
        self.store.append_history("assistant", result.message)
        self.last_result = result
        return result

    def _execute_parsed(self, parsed: ParsedCommand, approve: ApprovalCallback | None = None) -> ActionResult:
        if parsed.direct_response == "SECURITY_STATUS":
            return ActionResult(True, "\n".join(self.security.security_summary()))
        if parsed.direct_response == "LOCAL_TIME":
            return ActionResult(True, datetime.now().strftime("The local time is %I:%M %p.").replace(" 0", " "))
        if parsed.direct_response == "LOCAL_DATE":
            return ActionResult(True, datetime.now().strftime("Today is %A, %B %d, %Y.").replace(" 0", " "))
        if parsed.direct_response == "LIST_REMINDERS":
            return self.actions.list_reminders()
        if parsed.direct_response == "SLEEP_MODE":
            return ActionResult(True, "Going to sleep, sir.", {"voice_mode": "sleep"})
        if parsed.direct_response == "SHELL_COMMAND_LIST":
            return ActionResult(True, str(parsed.payload.get("message", "")))
        if parsed.direct_response == "SHELL_COMMAND_NOT_ALLOWED":
            return ActionResult(False, str(parsed.payload.get("message", "")))
        if parsed.direct_response == "UNKNOWN_WITHOUT_JARVIS":
            return ActionResult(True, "For general answers, start with Jarvis. For example: Jarvis, explain quantum computing simply.")
        if parsed.direct_response is not None:
            return ActionResult(True, parsed.direct_response)
        if parsed.action_id == "workflow.sequence":
            return self._run_sequence(parsed.payload.get("steps", []), parsed.jarvis_invoked, approve)
        if parsed.action_id == "workflow.response_to_notepad":
            return self._answer_to_notepad(parsed.payload.get("prompt", ""), parsed.jarvis_invoked, approve)
        if parsed.action_id == "workflow.response_to_note":
            return self._answer_to_note(parsed.payload.get("prompt", ""), parsed.jarvis_invoked, approve)
        if parsed.action_id == "workflow.save_last_to_note":
            return self._save_last_response_to_note(parsed.payload, approve)
        if parsed.action_id == "conversation.answer":
            return self._answer_general(parsed.payload["prompt"], parsed.jarvis_invoked, approve)
        if parsed.action_id:
            return self.actions.execute(parsed.action_id, parsed.payload, approve)
        return ActionResult(False, "I could not determine the action.")

    def _run_sequence(self, steps: Any, jarvis_invoked: bool, approve: ApprovalCallback | None = None) -> ActionResult:
        if not isinstance(steps, list):
            return ActionResult(False, "I could not understand the command sequence.")
        clean_steps = [str(step).strip(" ,.:;?!") for step in steps if str(step).strip(" ,.:;?!")]
        if not clean_steps:
            return ActionResult(False, "I could not understand the command sequence.")

        results: list[dict[str, Any]] = []
        for index, step in enumerate(clean_steps[:8], start=1):
            step_text = step
            if jarvis_invoked and not step.lower().lstrip().startswith(self.parser.wake_phrase):
                step_text = f"{self.parser.wake_phrase} {step}"
            parsed = self.parser.parse(step_text)
            result = self._execute_parsed(parsed, approve)
            self.last_result = result
            results.append({"step": step, "ok": result.ok, "message": result.message, "data": result.data})
            if not result.ok:
                break

        ok = all(item["ok"] for item in results)
        lines = [f"{index}. {item['step']}: {item['message']}" for index, item in enumerate(results, start=1)]
        return ActionResult(ok, "\n\n".join(lines), {"steps": results})

    def _answer_to_notepad(self, prompt: Any, jarvis_invoked: bool, approve: ApprovalCallback | None = None) -> ActionResult:
        clean_prompt = str(prompt).strip()
        if not clean_prompt:
            return ActionResult(False, "I need something to write before I can put it in Notepad.")
        if not jarvis_invoked:
            return ActionResult(True, "For generated text, start with Jarvis. For example: Jarvis, draft an email to Sam and put it in Notepad.")

        try:
            generated_text = self.cloud.answer(self._notepad_generation_prompt(clean_prompt), {"jarvis_invoked": True})
        except SecurityViolation as exc:
            return ActionResult(
                False,
                f"ChatGPT text request blocked by security policy: {exc}. I did not create the Notepad file.",
            )
        except Exception as exc:
            return ActionResult(
                False,
                f"ChatGPT text request failed: {exc}. I did not create the Notepad file.",
            )

        opened = self.actions.execute(
            "desktop.open_notepad_text",
            {"title": self._notepad_title(clean_prompt), "text": generated_text},
            approve,
        )
        if not opened.ok:
            return ActionResult(False, f"I generated the text, but could not open it in Notepad. {opened.message}", {"generated_text": generated_text, "notepad": opened.data})
        return ActionResult(
            True,
            f"Generated the text and opened it in Notepad: {opened.data.get('path') if opened.data else ''}",
            {"generated_text": generated_text, "notepad": opened.data},
        )

    def _answer_to_note(self, prompt: Any, jarvis_invoked: bool, approve: ApprovalCallback | None = None) -> ActionResult:
        clean_prompt = str(prompt).strip()
        if not clean_prompt:
            return ActionResult(False, "I need something to write before I can save it as a note.")
        if not jarvis_invoked:
            return ActionResult(True, "For generated text, start with Jarvis. For example: Jarvis, draft an email to Sam and save it to my notes.")

        try:
            generated_text = self.cloud.answer(self._note_generation_prompt(clean_prompt), {"jarvis_invoked": True})
        except SecurityViolation as exc:
            return ActionResult(
                False,
                f"ChatGPT text request blocked by security policy: {exc}. I did not create the note.",
            )
        except Exception as exc:
            return ActionResult(False, f"ChatGPT text request failed: {exc}. I did not create the note.")

        note = self.actions.execute(
            "files.create_note",
            {"title": self._note_title(clean_prompt), "body": generated_text},
            approve,
        )
        if not note.ok:
            return ActionResult(False, f"I generated the text, but could not save it as a note. {note.message}", {"generated_text": generated_text, "note": note.data})
        return ActionResult(
            True,
            f"Generated the text and saved it as a local note: {note.data.get('path') if note.data else ''}",
            {"generated_text": generated_text, "note": note.data},
        )

    def _save_last_response_to_note(self, payload: dict[str, Any], approve: ApprovalCallback | None = None) -> ActionResult:
        source = self._last_result_text_for_note()
        if not source:
            return ActionResult(
                False,
                "I do not have a previous Jarvis response to save yet. Say the note text after 'note that', or ask me to draft something first.",
            )
        title = str(payload.get("title", "Saved Jarvis Response")).strip() or "Saved Jarvis Response"
        note = self.actions.execute("files.create_note", {"title": title, "body": source}, approve)
        if not note.ok:
            return note
        return ActionResult(True, f"Saved the last Jarvis response as a local note: {note.data.get('path') if note.data else ''}", {"note": note.data})

    def _last_result_text_for_note(self) -> str:
        result = self.last_result
        if result is None or not result.ok:
            return self._last_assistant_history_text()
        data_text = self._result_data_text(result.data)
        return data_text or result.message.strip() or self._last_assistant_history_text()

    def _result_data_text(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        for key in ("generated_text", "text", "body", "summary", "answer"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        draft = data.get("draft")
        if isinstance(draft, dict):
            body = str(draft.get("body", "")).strip()
            if body:
                to = str(draft.get("to", "")).strip()
                subject = str(draft.get("subject", "")).strip()
                header = "\n".join(part for part in (f"To: {to}" if to else "", f"Subject: {subject}" if subject else "") if part)
                return f"{header}\n\n{body}".strip()
        for value in data.values():
            nested = self._result_data_text(value)
            if nested:
                return nested
        return ""

    def _last_assistant_history_text(self) -> str:
        for item in reversed(self.store.load_collection("history")):
            if item.get("role") == "assistant":
                text = str(item.get("text", "")).strip()
                if text:
                    return text
        return ""

    def _notepad_generation_prompt(self, prompt: str) -> str:
        return (
            "Create the content requested below for the user to edit in Notepad. "
            "Return only the final content, with no explanation, preface, or markdown fences.\n\n"
            f"Request: {prompt}"
        )

    def _note_generation_prompt(self, prompt: str) -> str:
        return (
            "Create the content requested below for the user to save as a local note. "
            "Return only the final note content, with no explanation, preface, or markdown fences.\n\n"
            f"Request: {prompt}"
        )

    def _notepad_title(self, prompt: str) -> str:
        title = re.sub(r"^(?:please\s+)?(?:draft|write|compose|create|make)\s+(?:an?\s+)?", "", prompt, flags=re.I)
        title = re.sub(r"\s+", " ", title).strip(" ,.:;?!")
        return title[:60] or "Jarvis output"

    def _note_title(self, prompt: str) -> str:
        title = re.sub(r"^(?:please\s+)?(?:draft|write|compose|create|make)\s+(?:an?\s+)?", "", prompt, flags=re.I)
        title = re.sub(r"\s+", " ", title).strip(" ,.:;?!")
        return title[:60] or "Jarvis Note"

    def _answer_general(self, prompt: str, jarvis_invoked: bool, approve: ApprovalCallback | None = None) -> ActionResult:
        if jarvis_invoked:
            plan = self.tool_planner.plan(prompt)
            if plan.blocked:
                self._append_tool_audit(prompt, plan, "blocked")
                return ActionResult(False, plan.blocked_reason)
            if plan.steps:
                self._append_tool_audit(prompt, plan, "selected")
                results = [self.actions.execute(step.action_id, step.payload, approve) for step in plan.steps]
                if len(results) == 1:
                    return results[0]
                ok = all(result.ok for result in results)
                message = "\n\n".join(result.message for result in results)
                return ActionResult(ok, message, {"tool_results": [result.data for result in results]})
        try:
            answer = self.cloud.answer(prompt, {"jarvis_invoked": jarvis_invoked})
            return ActionResult(True, answer)
        except SecurityViolation as exc:
            return ActionResult(
                True,
                f"ChatGPT text request blocked by security policy: {exc}. Microphone audio still stays local.",
            )
        except Exception as exc:
            return ActionResult(
                False,
                f"ChatGPT text request failed: {exc}. Check your local OpenAI key with jarvis --health, or run jarvis --set-openai-key. Microphone audio still stayed local.",
            )

    def _append_tool_audit(self, prompt: str, plan: ToolPlan, status: str) -> None:
        self.store.append_collection(
            "tool_audit",
            {
                "created_at": utc_now_iso(),
                "status": status,
                "prompt": redact_sensitive_text(prompt)[:1000],
                "reason": plan.reason,
                "blocked_reason": plan.blocked_reason,
                "steps": [{"action_id": step.action_id, "payload": step.payload} for step in plan.steps],
            },
        )
