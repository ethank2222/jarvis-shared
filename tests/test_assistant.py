from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from jarvis_app.actions import ActionRegistry
from jarvis_app.assistant import AssistantRuntime
from jarvis_app.google_services import GoogleServices
from jarvis_app.security import SecurityManager
from jarvis_app.storage import JsonStore


def build_runtime(tmp_path: Path) -> AssistantRuntime:
    store = JsonStore(tmp_path)
    store.settings["approved_folders"] = [str(tmp_path)]
    security = SecurityManager(store.settings)
    actions = ActionRegistry(store, security, GoogleServices(store))
    return AssistantRuntime(store, actions, security)


def test_create_and_list_reminder(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    created = runtime.handle("Jarvis remind me to call Alex at 4 PM")
    assert created.ok
    listed = runtime.handle("list reminders")
    assert listed.ok
    assert "call Alex" in listed.message


def test_complete_reminder(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    created = runtime.handle("remind me to call Alex")
    reminder_id = created.data["reminder"]["id"]
    completed = runtime.handle(f"complete reminder {reminder_id}")
    assert completed.ok
    listed = runtime.handle("list reminders")
    assert "No active reminders" in listed.message


def test_file_search_stays_in_approved_folder(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    (tmp_path / "notes.md").write_text("budget meeting notes", encoding="utf-8")
    result = runtime.handle("search files for budget")
    assert result.ok
    assert "notes.md" in result.message


def test_general_question_requires_jarvis_for_cloud(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    result = runtime.handle("what is the weather")
    assert result.ok
    assert "start with Jarvis" in result.message


def test_jarvis_general_question_uses_cloud_gate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = build_runtime(tmp_path)
    result = runtime.handle("Jarvis what is the weather")
    assert result.ok
    assert "jarvis --set-openai-key" in result.message


def test_jarvis_sleep_commands_are_local(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = build_runtime(tmp_path)

    for command in ["Jarvis bedtime", "Jarvis power off", "Jarvis good night"]:
        result = runtime.handle(command)
        assert result.ok
        assert result.message == "Going to sleep, sir."
        assert result.data == {"voice_mode": "sleep"}


def test_jarvis_startup_commands_are_local(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = build_runtime(tmp_path)

    for command in ["Jarvis wake up", "Jarvis turn on", "Jarvis power on", "Jarvis come online"]:
        result = runtime.handle(command)
        assert result.ok
        assert result.message == "Welcome Home Sir."


def test_create_list_and_read_note(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    created = runtime.handle("create note Project Alpha saying First draft is ready")
    assert created.ok
    listed = runtime.handle("list notes")
    assert "Project-Alpha" in listed.message
    natural_listed = runtime.handle("Jarvis what are my notes")
    assert "Project-Alpha" in natural_listed.message
    read = runtime.handle("read note Project Alpha")
    assert read.ok
    assert "First draft is ready" in read.message


def test_natural_note_phrases_create_verified_local_files(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    for command in [
        "Jarvis take a note that the budget is approved",
        "Jarvis write this down: send the proposal Friday",
        "Jarvis create a note saying schedule the design review",
    ]:
        result = runtime.handle(command)
        assert result.ok
        assert "saved locally" in result.message
        path = Path(result.data["path"])
        assert path.is_file()
        assert result.data["body"] in path.read_text(encoding="utf-8")


def test_natural_reminder_phrases_persist_title_and_due_text(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    commands = [
        ("Jarvis remind me at 4 PM to call Alex", "call Alex", "4 PM"),
        ("Jarvis set reminder for tomorrow to send the report", "send the report", "tomorrow"),
        ("Jarvis set a reminder to check the budget tonight", "check the budget", "tonight"),
    ]
    for command, title, due in commands:
        result = runtime.handle(command)
        assert result.ok
        assert "saved locally" in result.message
        assert result.data["reminder"]["title"] == title
        assert result.data["reminder"]["due_text"] == due

    stored = runtime.store.load_collection("reminders")
    assert len(stored) == len(commands)


def test_reminder_with_clock_time_has_structured_schedule_and_notifies_once(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    created = runtime.handle("Jarvis set a reminder for 11:15")

    assert created.ok
    reminder = created.data["reminder"]
    assert reminder["description"] == "Reminder"
    assert reminder["title"] == "Reminder"
    assert reminder["date"]
    assert reminder["time"] == "11:15"
    assert reminder["due_at"]
    assert reminder["notified"] is False
    assert datetime.fromisoformat(reminder["due_at"]).astimezone() > datetime.now().astimezone()

    reminders = runtime.store.load_collection("reminders")
    reminders[0]["due_at"] = (datetime.now().astimezone() - timedelta(seconds=1)).replace(microsecond=0).isoformat()
    reminders[0]["date"] = datetime.fromisoformat(reminders[0]["due_at"]).strftime("%Y-%m-%d")
    reminders[0]["time"] = datetime.fromisoformat(reminders[0]["due_at"]).strftime("%H:%M")
    runtime.store.save_collection("reminders", reminders)

    due = runtime.actions.due_reminders()
    assert [item["id"] for item in due] == [reminder["id"]]
    assert due[0]["description"] == "Reminder"
    assert runtime.actions.due_reminders() == []


def test_notes_do_not_get_reminder_schedule_fields(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    note = runtime.handle("Jarvis take a note that the budget is approved")

    assert note.ok
    assert {"date", "time", "due_at", "description"}.isdisjoint(note.data)


def test_timer_commands_create_list_cancel_and_notify_locally(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    created = runtime.handle("Jarvis start a 1 second tea timer")

    assert created.ok
    timer = created.data["timer"]
    assert timer["label"] == "tea"
    assert timer["duration_seconds"] == 1

    listed = runtime.handle("Jarvis show timers")
    assert listed.ok
    assert timer["id"] in listed.message

    timers = runtime.store.load_collection("timers")
    timers[0]["expires_at"] = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat()
    timers[0]["done"] = False
    timers[0]["notified"] = False
    runtime.store.save_collection("timers", timers)

    due = runtime.actions.due_timers()
    assert [item["id"] for item in due] == [timer["id"]]
    assert runtime.actions.due_timers() == []

    cancelled = runtime.handle(f"Jarvis cancel timer {timer['id']}")
    assert cancelled.ok


def test_local_note_and_reminder_commands_never_call_cloud(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    def fail_cloud(*_args, **_kwargs):
        raise AssertionError("local actions must not call OpenAI")

    runtime.cloud.answer = fail_cloud

    assert runtime.handle("Jarvis note that this stays local").ok
    assert runtime.handle("Jarvis remind me tomorrow to review the note").ok


def test_tool_like_requests_never_fall_through_to_cloud(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    def fail_cloud(*_args, **_kwargs):
        raise AssertionError("tool requests must not call OpenAI")

    runtime.cloud.answer = fail_cloud

    commands = [
        "Jarvis can you add this to my notes: reorder filters",
        "Jarvis show my notes",
        "Jarvis what notes do I have?",
        "Jarvis what are my notes",
        "show my notes",
        "Jarvis do you have access to my notes?",
        "Jarvis could you show my reminders",
        "Jarvis set a timer for five minutes",
        "Jarvis what tools do you have access to",
    ]
    for command in commands:
        result = runtime.handle(command)
        assert result.ok, command


def test_allowlisted_shell_commands_require_approval_and_execute(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    cancelled = runtime.handle("Jarvis run shell command python version")
    assert not cancelled.ok
    assert "Cancelled" in cancelled.message

    executed = runtime.handle("Jarvis run shell command python version", lambda _policy, _payload: True)
    assert executed.ok
    assert "python version" in executed.message.lower()
    assert "python" in executed.message.lower()


def test_unknown_shell_command_is_rejected_without_cloud(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    def fail_cloud(*_args, **_kwargs):
        raise AssertionError("unknown shell commands must not call OpenAI")

    runtime.cloud.answer = fail_cloud

    result = runtime.handle("Jarvis run shell command format drive")

    assert not result.ok
    assert "not approved" in result.message
    assert "Approved shell commands" in result.message


def test_approved_app_aliases_open_without_cloud(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    launched: list[list[str]] = []
    runtime.actions._launch_app_command = lambda command: launched.append(command) or {"method": "fake"}

    chrome = runtime.handle("Jarvis open chrome")
    word = runtime.handle("Jarvis launch Microsoft Word")
    powerpoint = runtime.handle("Jarvis start power point")

    assert chrome.ok
    assert word.ok
    assert powerpoint.ok
    assert launched == [["chrome.exe"], ["WINWORD.EXE"], ["POWERPNT.EXE"]]


def test_unknown_app_open_is_rejected_without_cloud(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    def fail_cloud(*_args, **_kwargs):
        raise AssertionError("unknown app opens must not call OpenAI")

    runtime.cloud.answer = fail_cloud

    result = runtime.handle("Jarvis open spotify")

    assert not result.ok
    assert "approved app list" in result.message.lower()
    assert "Approved apps" in result.message


def test_generated_response_can_be_put_in_notepad(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    launched: list[list[str]] = []
    prompts: list[str] = []

    runtime.actions._launch_app_command = lambda command: launched.append(command) or {"method": "fake"}

    def fake_answer(prompt: str, context: dict[str, object]) -> str:
        prompts.append(prompt)
        assert context == {"jarvis_invoked": True}
        return "Dear Taylor,\n\nHere is the launch update.\n\nBest,\nEthan"

    runtime.cloud.answer = fake_answer

    result = runtime.handle("Jarvis draft an email to Taylor about the launch and put it in a notepad")

    assert result.ok
    assert "opened it in Notepad" in result.message
    assert "Request: draft an email to Taylor about the launch" in prompts[0]
    path = Path(result.data["notepad"]["path"])
    assert path.is_file()
    assert "Here is the launch update" in path.read_text(encoding="utf-8")
    assert launched == [["notepad.exe", str(path)]]


def test_generated_response_can_be_saved_directly_to_notes(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    prompts: list[str] = []

    def fake_answer(prompt: str, context: dict[str, object]) -> str:
        prompts.append(prompt)
        assert context == {"jarvis_invoked": True}
        return "Dear Taylor,\n\nHere is the launch update.\n\nBest,\nEthan"

    runtime.cloud.answer = fake_answer

    result = runtime.handle("Jarvis draft an email to Taylor about the launch and save it to my notes")

    assert result.ok
    assert "saved it as a local note" in result.message
    assert "Request: draft an email to Taylor about the launch" in prompts[0]
    path = Path(result.data["note"]["path"])
    assert path.is_file()
    assert "Here is the launch update" in path.read_text(encoding="utf-8")


def test_save_it_to_notes_uses_previous_jarvis_response_without_cloud(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    runtime.cloud.answer = lambda prompt, context: "Draft email body for the proposal."

    drafted = runtime.handle("Jarvis write a short email about the proposal")
    assert drafted.ok

    def fail_cloud(*_args, **_kwargs):
        raise AssertionError("saving the previous response to notes must not call OpenAI")

    runtime.cloud.answer = fail_cloud
    saved = runtime.handle("Jarvis save it to my notes")

    assert saved.ok
    path = Path(saved.data["note"]["path"])
    assert path.is_file()
    assert "Draft email body for the proposal." in path.read_text(encoding="utf-8")

    listed = runtime.handle("Jarvis show my notes")
    assert "Saved-Jarvis-Response" in listed.message


def test_save_it_to_notes_without_prior_response_does_not_call_cloud(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    def fail_cloud(*_args, **_kwargs):
        raise AssertionError("empty note reference must not call OpenAI")

    runtime.cloud.answer = fail_cloud
    result = runtime.handle("Jarvis save it to my notes")

    assert not result.ok
    assert "previous Jarvis response" in result.message


def test_email_text_note_phrases_create_local_notes(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    result = runtime.handle("Jarvis save this email to my notes: Please review the Q3 plan.")

    assert result.ok
    path = Path(result.data["path"])
    assert path.is_file()
    assert "Please review the Q3 plan" in path.read_text(encoding="utf-8")


def test_multi_command_sequence_runs_existing_commands_in_order(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    result = runtime.handle("Jarvis take a note that sequence works and then show my notes")

    assert result.ok
    assert result.data["steps"][0]["step"] == "take a note that sequence works"
    assert result.data["steps"][1]["step"] == "show my notes"
    assert "Note saved locally" in result.data["steps"][0]["message"]
    assert "sequence-works" in result.data["steps"][1]["message"]


def test_then_inside_general_question_is_not_treated_as_a_sequence(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    runtime.cloud.answer = lambda prompt, context: f"cloud saw: {prompt}"

    result = runtime.handle("Jarvis explain if the build passes then what should I do")

    assert result.ok
    assert result.message == "cloud saw: explain if the build passes then what should I do"
