from __future__ import annotations

from pathlib import Path

from jarvis_app.actions import ActionRegistry
from jarvis_app.assistant import AssistantRuntime, CommandParser
from jarvis_app.google_services import GoogleServices, GoogleStatus
from jarvis_app.security import SecurityManager
from jarvis_app.storage import JsonStore


ADVERTISED_COMMANDS = (
    "help", "security status", "health check", "what time is it", "what date is it",
    "Jarvis wake up", "Jarvis bedtime", "voice status", "voice test",
    "set voice provider elevenlabs", "enable voice cache", "remind me tomorrow to call Alex",
    "list reminders", "edit reminder abc123 to call Jordan at 5 PM",
    "complete reminder abc123", "delete reminder abc123",
    "set a timer for five minutes", "list timers", "cancel timer abc123",
    "take a note that the budget is approved", "list notes", "show my notes", "read note budget",
    "scan latest screenshot", "look at the last screenshot you took", r"scan image C:\notes\whiteboard.png",
    "remember that I prefer short answers", "what do you remember", "forget memory abc123",
    "search files for budget", r"summarize file C:\notes\budget.md", "take screenshot",
    "open notepad", "launch calculator", "open slack", "open discord", "open chrome",
    "open github desktop", "open word", "open excel", "open power point",
    "show approved shell commands", "run shell command python version",
    "what meetings do I have today", "search calendar for dentist",
    "schedule meeting Project Review at Friday 2 PM", "search gmail for invoice",
    "draft email to sam@example.com saying I will send the proposal Friday",
    "send email draft abc123", "google status", "Jarvis explain black holes simply",
)


def build_runtime(tmp_path: Path, google=None) -> AssistantRuntime:
    store = JsonStore(tmp_path)
    store.settings["approved_folders"] = [str(tmp_path)]
    store.save_settings()
    security = SecurityManager(store.settings)
    google = google or GoogleServices(store)
    actions = ActionRegistry(store, security, google)
    return AssistantRuntime(store, actions, security)


def test_every_advertised_command_resolves_to_a_handler_or_direct_response(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    parser = CommandParser()
    for command in ADVERTISED_COMMANDS:
        parsed = parser.parse(command)
        assert parsed.action_id or parsed.direct_response, command
        if parsed.action_id:
            runtime.security.policy_for(parsed.action_id)
            if parsed.action_id != "conversation.answer":
                assert parsed.action_id in runtime.actions.handlers, command


def test_disconnected_google_commands_fail_with_setup_instruction(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    for command in (
        "what meetings do I have today",
        "search calendar for dentist",
        "search gmail for invoice",
        "draft email to sam@example.com saying Hello",
    ):
        result = runtime.handle(command, lambda _policy, _payload: True)
        assert not result.ok
        assert "jarvis --connect-google" in result.message


class FakeGoogleServices:
    status = GoogleStatus(True, True, "test connection")

    def status_summary(self) -> str:
        return "Google services: connected. test connection"

    def calendar_today(self):
        return [{"id": "event1", "title": "Standup", "start": "2026-07-11T09:00:00-07:00", "end": "", "link": ""}]

    def calendar_search(self, query: str):
        return [{"id": "event2", "title": query.title(), "start": "2026-07-12T15:00:00-07:00", "end": "", "link": ""}]

    def calendar_create(self, title: str, time_text: str):
        return {"id": "event3", "title": title, "start": "2026-07-18T14:00:00-07:00", "end": "", "link": "https://calendar.test/event3"}

    def gmail_search(self, query: str):
        return [{"id": "msg1", "thread_id": "thread1", "from": "sam@example.com", "subject": query, "date": "", "snippet": "Invoice attached"}]

    def gmail_create_draft(self, to: str, subject: str, body: str):
        return {"id": "draft1", "message_id": "msg2", "to": to, "subject": subject, "body": body}

    def gmail_send_draft(self, draft_id: str):
        return {"draft_id": draft_id, "message_id": "msg3", "thread_id": "thread2"}


def test_connected_google_commands_execute_and_return_verified_ids(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path, FakeGoogleServices())
    today = runtime.handle("what meetings do I have today")
    searched = runtime.handle("search calendar for dentist")
    created = runtime.handle("schedule meeting Project Review at Friday 2 PM", lambda _policy, _payload: True)
    mail = runtime.handle("search gmail for invoice")
    natural_mail = runtime.handle("Jarvis can you show my email about invoice")
    drafted = runtime.handle("draft email to sam@example.com about Proposal saying Attached is the proposal")
    sent = runtime.handle("send email draft draft1", lambda _policy, _payload: True)
    assert today.data["events"][0]["id"] == "event1"
    assert searched.data["events"][0]["id"] == "event2"
    assert created.data["event"]["id"] == "event3"
    assert mail.data["messages"][0]["id"] == "msg1"
    assert natural_mail.data["messages"][0]["id"] == "msg1"
    assert drafted.data["draft"]["id"] == "draft1"
    assert sent.data["sent"]["message_id"] == "msg3"


def test_file_summary_selects_informative_sentences(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    document = tmp_path / "project.md"
    document.write_text(
        "The project began on Monday. The launch is scheduled for Friday. "
        "The launch requires final security approval. Coffee was served at lunch. "
        "The launch checklist has twelve verified items. The weather was mild.",
        encoding="utf-8",
    )
    result = runtime.handle(f"summarize file {document}")
    assert result.ok
    assert "Local summary" in result.message
    assert "launch" in result.data["summary"].lower()


def test_reminder_edit_updates_and_verifies_saved_record(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    created = runtime.handle("remind me to call Alex at 4 PM")
    reminder_id = created.data["reminder"]["id"]

    edited = runtime.handle(
        f"edit reminder {reminder_id} to call Jordan at 5 PM",
        lambda _policy, _payload: True,
    )

    assert edited.ok
    assert edited.data["reminder"]["title"] == "call Jordan"
    assert edited.data["reminder"]["due_text"] == "5 PM"
