from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .app_config import APPROVED_APP_COMMANDS, APPROVED_SHELL_COMMANDS
from .command_intents import parse_email_draft_command, parse_note_command, parse_reminder_command, parse_timer_command


@dataclass(frozen=True)
class ToolStep:
    action_id: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolPlan:
    steps: list[ToolStep] = field(default_factory=list)
    reason: str = ""
    blocked_reason: str = ""

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_reason)


TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {"action_id": "system.health", "description": "Run local health diagnostics.", "payload": {}},
    {"action_id": "files.search", "description": "Search file names and text inside approved folders.", "payload": {"query": "string"}},
    {"action_id": "files.summarize", "description": "Preview-summary for a specific approved text file.", "payload": {"path": "string"}},
    {"action_id": "files.create_note", "description": "Create a local markdown note.", "payload": {"title": "string", "body": "string"}},
    {"action_id": "notes.scan", "description": "Run local OCR on an image or latest screenshot.", "payload": {"path": "string", "source": "latest_screenshot"}},
    {"action_id": "notes.list", "description": "List local markdown notes.", "payload": {}},
    {"action_id": "notes.read", "description": "Read a local markdown note by search term.", "payload": {"query": "string"}},
    {"action_id": "memory.remember", "description": "Store an explicit local memory.", "payload": {"text": "string", "category": "string"}},
    {"action_id": "memory.list", "description": "List local memories.", "payload": {"query": "string"}},
    {"action_id": "memory.forget", "description": "Forget a local memory by id or query.", "payload": {"id": "string", "query": "string"}},
    {"action_id": "reminders.create", "description": "Create a local reminder.", "payload": {"title": "string", "due_text": "string"}},
    {"action_id": "reminders.list", "description": "List active local reminders.", "payload": {}},
    {"action_id": "reminders.edit", "description": "Edit a local reminder.", "payload": {"id": "string", "title": "string", "due_text": "string"}},
    {"action_id": "reminders.complete", "description": "Complete a local reminder.", "payload": {"id": "string"}},
    {"action_id": "reminders.delete", "description": "Delete a local reminder after confirmation.", "payload": {"id": "string"}},
    {"action_id": "timers.create", "description": "Create a local countdown timer.", "payload": {"label": "string", "duration_text": "string", "duration_seconds": "number"}},
    {"action_id": "timers.list", "description": "List active local countdown timers.", "payload": {}},
    {"action_id": "timers.cancel", "description": "Cancel a local countdown timer.", "payload": {"id": "string"}},
    {"action_id": "screen.capture", "description": "Capture a local screenshot after confirmation.", "payload": {}},
    {"action_id": "desktop.open_app", "description": "Open an approved local app.", "payload": {"app": "string"}},
    {"action_id": "automation.shell", "description": "Run an approved shell command after confirmation.", "payload": {"command": "string"}},
    {"action_id": "voice.status", "description": "Report reply voice settings and usage.", "payload": {}},
    {"action_id": "voice.test", "description": "Speak a short reply voice test.", "payload": {}},
    {"action_id": "google.status", "description": "Report Gmail and Calendar connection status.", "payload": {}},
    {"action_id": "calendar.read_today", "description": "Read today's Google Calendar schedule.", "payload": {}},
    {"action_id": "calendar.search", "description": "Search upcoming Google Calendar events.", "payload": {"query": "string"}},
    {"action_id": "calendar.create", "description": "Create a Google Calendar event after confirmation.", "payload": {"title": "string", "time_text": "string"}},
    {"action_id": "gmail.search", "description": "Search Gmail.", "payload": {"query": "string"}},
    {"action_id": "gmail.draft", "description": "Create a Gmail draft.", "payload": {"to": "string", "subject": "string", "body": "string"}},
    {"action_id": "gmail.send", "description": "Send a Gmail draft after review.", "payload": {"draft_id": "string"}},
)


class ToolPlanner:
    """Small, deterministic planner for safe local tools.

    Cloud model tool-calling can be added later, but this layer keeps the same
    local policy gate and gives natural phrasing a useful baseline today.
    """

    def plan(self, prompt: str) -> ToolPlan:
        raw = self._clean_request(prompt)
        lowered = raw.lower()
        blocked = self._blocked_reason(lowered)
        if blocked:
            return ToolPlan(blocked_reason=blocked)

        if re.search(r"\b(health|diagnostic|diagnostics|system check|status report)\b", lowered):
            return ToolPlan([ToolStep("system.health")], "Natural-language system health request.")

        if re.search(r"\b(voice status|voice settings|tts status|sound settings)\b", lowered):
            return ToolPlan([ToolStep("voice.status")], "Natural-language voice status request.")

        if re.search(r"\b(test voice|voice test|say something|test your voice)\b", lowered):
            return ToolPlan([ToolStep("voice.test")], "Natural-language voice test request.")

        shell = self._shell_plan(raw)
        if shell.steps or shell.blocked:
            return shell

        timer = self._timer_plan(raw, lowered)
        if timer.steps or timer.blocked:
            return timer

        reminder = self._reminder_plan(raw, lowered)
        if reminder.steps or reminder.blocked:
            return reminder

        reminder_payload = parse_reminder_command(raw)
        if reminder_payload:
            return ToolPlan([ToolStep("reminders.create", reminder_payload)], "Local reminder request.")

        note_payload = parse_note_command(raw)
        if note_payload:
            return ToolPlan([ToolStep("files.create_note", note_payload)], "Local note creation request.")

        memory = self._memory_plan(raw, lowered)
        if memory.steps or memory.blocked:
            return memory

        note_scan = self._scan_plan(raw, lowered)
        if note_scan.steps:
            return note_scan

        file_plan = self._file_plan(raw, lowered)
        if file_plan.steps:
            return file_plan

        screen = self._screen_plan(lowered)
        if screen.steps:
            return screen

        google = self._google_plan(raw, lowered)
        if google.steps or google.blocked:
            return google

        app = self._app_plan(raw)
        if app.steps:
            return app

        return ToolPlan()

    def _timer_plan(self, raw: str, lowered: str) -> ToolPlan:
        if re.search(r"\b(list|show|what|active|running)\b.*\btimers?\b", lowered):
            return ToolPlan([ToolStep("timers.list")], "Timer list request.")

        cancel = re.match(r"^(?:cancel|stop|delete) timer (?P<id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if cancel:
            return ToolPlan([ToolStep("timers.cancel", {"id": cancel.group("id")})], "Timer cancellation request.")

        timer_payload = parse_timer_command(raw)
        if timer_payload:
            return ToolPlan([ToolStep("timers.create", timer_payload)], "Local timer request.")

        if "timer" in lowered and re.search(r"\b(set|start|create|make|countdown)\b", lowered):
            return ToolPlan(blocked_reason="I can set local timers, but I need a duration like '5 minutes'.")
        return ToolPlan()

    def _reminder_plan(self, raw: str, lowered: str) -> ToolPlan:
        if re.search(r"\b(list|show|what|any|active|upcoming)\b.*\breminders?\b", lowered):
            return ToolPlan([ToolStep("reminders.list")], "Reminder list request.")

        complete = re.match(r"^(?:mark |set )?(?:reminder )?(?P<id>[a-zA-Z0-9_-]+) (?:as )?(?:done|complete|completed|finished)$", raw, re.I)
        if not complete:
            complete = re.match(r"^(?:complete|finish|done) reminder (?P<id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if complete:
            return ToolPlan([ToolStep("reminders.complete", {"id": complete.group("id")})], "Reminder completion request.")

        delete = re.match(r"^(?:delete|remove|cancel) reminder (?P<id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if delete:
            return ToolPlan([ToolStep("reminders.delete", {"id": delete.group("id")})], "Reminder deletion request.")

        edit = re.match(
            r"^(?:edit|update|change) reminder (?P<id>[a-zA-Z0-9_-]+) to (?P<title>.+?) "
            r"(?:at|on|for) (?P<due>.+)$",
            raw,
            re.I,
        )
        if edit:
            return ToolPlan(
                [
                    ToolStep(
                        "reminders.edit",
                        {
                            "id": edit.group("id"),
                            "title": edit.group("title").strip(),
                            "due_text": edit.group("due").strip(),
                        },
                    )
                ],
                "Reminder edit request.",
            )

        if "reminder" in lowered and re.search(r"\b(set|add|create|make|remind)\b", lowered):
            return ToolPlan(blocked_reason="I can create local reminders, but I need reminder text.")
        return ToolPlan()

    def _memory_plan(self, raw: str, lowered: str) -> ToolPlan:
        remember = re.match(r"^(?:please )?remember(?: that)? (?P<text>.+)$", raw, re.I)
        if remember:
            return ToolPlan(
                [ToolStep("memory.remember", {"text": remember.group("text").strip(), "category": "general"})],
                "Explicit memory request.",
            )

        if lowered in {"what do you remember", "show memories", "list memories", "list memory"}:
            return ToolPlan([ToolStep("memory.list")], "Memory list request.")

        about = re.match(r"^what do you remember about (?P<query>.+)$", raw, re.I)
        if about:
            return ToolPlan([ToolStep("memory.list", {"query": about.group("query").strip()})], "Memory search request.")

        forget = re.match(r"^(?:please )?forget memory (?P<id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if forget:
            return ToolPlan([ToolStep("memory.forget", {"id": forget.group("id")})], "Memory deletion request.")

        forget_query = re.match(r"^(?:please )?forget(?: that)? (?P<query>.+)$", raw, re.I)
        if forget_query and "forget" in lowered:
            return ToolPlan([ToolStep("memory.forget", {"query": forget_query.group("query").strip()})], "Memory deletion request.")

        return ToolPlan()

    def _scan_plan(self, raw: str, lowered: str) -> ToolPlan:
        if (
            "screenshot" in lowered
            and re.search(r"\b(ocr|scan|read text from|read|look|analyze|analyse|inspect|check)\b", lowered)
            and re.search(r"\b(last|latest|recent|previous|this)\b", lowered)
        ):
            return ToolPlan([ToolStep("notes.scan", {"source": "latest_screenshot"})], "Screenshot OCR request.")

        scan = re.match(r"^(?:please )?(?:scan|ocr|read text from) (?:image|file)? ?(?P<path>.+)$", raw, re.I)
        if scan:
            path = scan.group("path").strip().strip('"')
            return ToolPlan([ToolStep("notes.scan", {"path": path})], "Image OCR request.")

        return ToolPlan()

    def _file_plan(self, raw: str, lowered: str) -> ToolPlan:
        summarize = re.match(r"^(?:please )?summarize (?:file|document) (?P<path>.+)$", raw, re.I)
        if summarize:
            return ToolPlan([ToolStep("files.summarize", {"path": summarize.group("path").strip().strip('"')})], "File summary request.")

        if (
            re.search(r"\b(list|show|read|tell)\b", lowered)
            and "notes" in lowered
        ) or re.search(r"\bwhat\b.*\b(?:are|is)\b.*\b(my |the )?notes\b", lowered):
            return ToolPlan([ToolStep("notes.list")], "Notes list request.")

        read_note = re.match(r"^(?:read|show|open) (?:my )?notes? (?:about|for|called|named)? (?P<query>.+)$", raw, re.I)
        if read_note:
            return ToolPlan([ToolStep("notes.read", {"query": read_note.group("query").strip()})], "Note read request.")

        if re.search(r"\b(find|search|locate)\b", lowered) and re.search(r"\b(file|files|document|documents|note|notes)\b", lowered):
            query = self._search_query(raw)
            return ToolPlan([ToolStep("files.search", {"query": query})], "Approved-folder search request.")

        if "note" in lowered and re.search(r"\b(take|create|write|make|add|save|jot)\b", lowered):
            return ToolPlan(blocked_reason="I can create local notes, but I need the note text.")
        return ToolPlan()

    def _screen_plan(self, lowered: str) -> ToolPlan:
        if re.search(r"\b(take|capture|grab|save|scan)\b.*\b(screenshot|screen)\b", lowered):
            return ToolPlan([ToolStep("screen.capture")], "Screenshot capture request.")
        return ToolPlan()

    def _google_plan(self, raw: str, lowered: str) -> ToolPlan:
        if re.search(r"\b(google|gmail|calendar)\b.*\b(status|connected|connection)\b", lowered):
            return ToolPlan([ToolStep("google.status")], "Google connection status request.")

        calendar_create = re.match(
            r"^(?:create|schedule|set|add) (?:a )?(?:calendar )?(?:event|appointment|meeting) (?P<title>.+?)(?: at (?P<time>.+))?$",
            raw,
            re.I,
        )
        if calendar_create:
            return ToolPlan(
                [
                    ToolStep(
                        "calendar.create",
                        {
                            "title": calendar_create.group("title").strip(),
                            "time_text": (calendar_create.group("time") or "").strip(),
                        },
                    )
                ],
                "Calendar event creation request.",
            )

        if re.search(r"\b(calendar|schedule|meetings?|events?|appointments?)\b", lowered):
            if re.search(r"\b(today|now|next|upcoming|this morning|this afternoon|tonight)\b", lowered):
                return ToolPlan([ToolStep("calendar.read_today")], "Calendar read request.")
            if re.search(r"\b(search|find|show|look up|check)\b", lowered):
                return ToolPlan([ToolStep("calendar.search", {"query": self._object_query(raw, "calendar")})], "Calendar search request.")

        email_payload = parse_email_draft_command(raw)
        if email_payload:
            return ToolPlan([ToolStep("gmail.draft", email_payload)], "Gmail draft request.")

        send_draft = re.match(r"^(?:send|send gmail|send email) (?:email )?draft (?P<draft_id>[a-zA-Z0-9_-]+)$", raw, re.I)
        if send_draft:
            return ToolPlan([ToolStep("gmail.send", {"draft_id": send_draft.group("draft_id")})], "Gmail send request.")

        if re.search(r"\b(gmail|email|mail)\b", lowered) and re.search(r"\b(search|find|show|look up|check)\b", lowered):
            return ToolPlan([ToolStep("gmail.search", {"query": self._object_query(raw, "email")})], "Gmail search request.")

        return ToolPlan()

    def _app_plan(self, raw: str) -> ToolPlan:
        app = self._app_candidate(raw)
        if app:
            return ToolPlan([ToolStep("desktop.open_app", {"app": app})], "Natural-language app launch request.")
        return ToolPlan()

    def _app_candidate(self, raw: str) -> str:
        match = re.match(r"^(?:open|launch|start)\s+(?:(?:the)\s+)?(?P<app>.+)$", raw, re.I)
        if not match:
            return ""
        app = self._command_key(match.group("app"))
        app = re.sub(r"\s+(?:app|application)$", "", app).strip()
        return app

    def _shell_plan(self, raw: str) -> ToolPlan:
        candidate = self._shell_candidate(raw)
        if not candidate:
            return ToolPlan()
        command_key = self._command_key(candidate)
        if command_key in APPROVED_SHELL_COMMANDS:
            return ToolPlan([ToolStep("automation.shell", {"command": command_key})], "Approved shell command request.")
        allowed = ", ".join(sorted(APPROVED_SHELL_COMMANDS))
        return ToolPlan(blocked_reason=f"'{command_key}' is not approved. Approved shell commands are: {allowed}.")

    def _blocked_reason(self, lowered: str) -> str:
        blocked_patterns = (
            r"\b(run|execute|launch)\b.*\b(shell|powershell|cmd|terminal|script|command)\b",
            r"\b(delete|remove|erase|wipe)\b.*\b(file|folder|directory|email|gmail|message)\b",
            r"\b(format|wipe)\b.*\b(drive|disk|computer|pc)\b",
        )
        if any(re.search(pattern, lowered) for pattern in blocked_patterns):
            return "That request maps to a blocked or destructive action. I can help with approved local tools instead."
        return ""

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

    def _command_key(self, value: str) -> str:
        lowered = value.lower().strip().strip(" ,.:;?!")
        lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    def _clean_request(self, prompt: str) -> str:
        raw = prompt.strip().strip(" ,.:;")
        return re.sub(
            r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+|i need you to\s+|i want you to\s+)",
            "",
            raw,
            flags=re.I,
        ).strip()

    def _search_query(self, raw: str) -> str:
        query = re.sub(r"^(?:please )?(?:find|search|locate)\s+", "", raw, flags=re.I)
        query = re.sub(r"\b(my|the|all|files?|documents?|notes?)\b", " ", query, flags=re.I)
        query = re.sub(r"\band summarize\b.*$", "", query, flags=re.I)
        query = re.sub(r"\s+", " ", query).strip(" ,.:;")
        return query or raw.strip()

    def _object_query(self, raw: str, domain: str) -> str:
        query = re.sub(r"^(?:search|find|show|look up|check)\s+", "", raw, flags=re.I)
        if domain == "calendar":
            query = re.sub(r"\b(my|the|calendar|schedule|meetings?|events?|appointments?|for|about)\b", " ", query, flags=re.I)
        else:
            query = re.sub(r"\b(my|the|gmail|email|mail|messages?|for|about)\b", " ", query, flags=re.I)
        query = re.sub(r"\s+", " ", query).strip(" ,.:;")
        return query or raw.strip()
