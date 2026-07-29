from __future__ import annotations

from pathlib import Path

from jarvis_app.actions import ActionRegistry
from jarvis_app.assistant import AssistantRuntime
from jarvis_app.google_services import GoogleServices
from jarvis_app.ocr import OcrResult
from jarvis_app.security import SecurityManager
from jarvis_app.storage import JsonStore


def build_runtime(tmp_path: Path) -> AssistantRuntime:
    store = JsonStore(tmp_path)
    store.settings["approved_folders"] = [str(tmp_path)]
    security = SecurityManager(store.settings)
    actions = ActionRegistry(store, security, GoogleServices(store))
    return AssistantRuntime(store, actions, security)


def test_health_check_command_returns_report(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    result = runtime.handle("Jarvis health check")
    assert result.ok
    assert "Private Jarvis" in result.message
    assert "health report" in result.message


def test_planner_routes_natural_file_search_and_audits(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)
    (tmp_path / "budget-notes.md").write_text("budget action items", encoding="utf-8")

    result = runtime.handle("Jarvis find my budget notes")

    assert result.ok
    assert "budget-notes.md" in result.message
    audit = runtime.store.load_collection("tool_audit")
    assert audit[-1]["steps"][0]["action_id"] == "files.search"


def test_planner_blocks_shell_like_request(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    result = runtime.handle("Jarvis run a powershell command")

    assert not result.ok
    assert "approved shell commands" in result.message.lower()


def test_memory_create_list_forget_and_secret_rejection(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    created = runtime.handle("Jarvis remember that I prefer short answers")
    assert created.ok
    memory_id = created.data["memory"]["id"]

    listed = runtime.handle("Jarvis what do you remember")
    assert "prefer short answers" in listed.message

    rejected = runtime.handle("Jarvis remember that api_key=sk-thisisasecret1234567890")
    assert not rejected.ok
    assert "will not store" in rejected.message

    forgotten = runtime.handle(f"Jarvis forget memory {memory_id}", lambda _policy, _payload: True)
    assert forgotten.ok
    assert "Forgot 1" in forgotten.message


def test_voice_status_and_provider_setting(tmp_path: Path) -> None:
    runtime = build_runtime(tmp_path)

    status = runtime.handle("Jarvis voice status")
    assert status.ok
    assert "Voice provider" in status.message

    cancelled = runtime.handle("Jarvis set voice provider local")
    assert not cancelled.ok
    assert "Cancelled" in cancelled.message

    changed = runtime.handle("Jarvis set voice provider local", lambda _policy, _payload: True)
    assert changed.ok
    assert runtime.store.settings["tts_provider"] == "sapi"
    assert runtime.store.settings["allow_cloud_tts"] is False


def test_elevenlabs_voice_provider_can_be_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "test-voice")
    runtime = build_runtime(tmp_path)

    changed = runtime.handle("Jarvis set voice provider elevenlabs", lambda _policy, _payload: True)

    assert changed.ok
    assert runtime.store.settings["tts_provider"] == "elevenlabs"
    assert runtime.store.settings["allow_cloud_tts"] is True
    assert "microphone audio remains local" in changed.message


def test_scan_image_uses_local_ocr_and_creates_note(tmp_path: Path, monkeypatch) -> None:
    runtime = build_runtime(tmp_path)
    image = tmp_path / "whiteboard.png"
    image.write_bytes(b"not a real image, fake OCR is injected")

    class FakeOcrService:
        def __init__(self, _settings: dict[str, object]) -> None:
            pass

        def scan_image(self, _path: Path) -> OcrResult:
            return OcrResult(True, text="Call Sam and update the budget.", engine="fake-local")

    monkeypatch.setattr("jarvis_app.actions.OcrService", FakeOcrService)

    result = runtime.handle(f"Jarvis scan image {image}")

    assert result.ok
    assert "fake-local" in result.message
    note_path = Path(result.data["note_path"])
    assert note_path.exists()
    assert "Call Sam" in note_path.read_text(encoding="utf-8")


def test_look_at_last_screenshot_routes_to_local_latest_screenshot_scan(tmp_path: Path, monkeypatch) -> None:
    runtime = build_runtime(tmp_path)
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir(exist_ok=True)
    image = screenshots / "screenshot-20260711-111900.png"
    image.write_bytes(b"not a real image, fake OCR is injected")

    class FakeOcrService:
        def __init__(self, _settings: dict[str, object]) -> None:
            pass

        def scan_image(self, _path: Path) -> OcrResult:
            return OcrResult(True, text="Dialog asks to confirm screenshot.", engine="fake-local")

    def fail_cloud(*_args, **_kwargs):
        raise AssertionError("latest screenshot requests must not call OpenAI")

    monkeypatch.setattr("jarvis_app.actions.OcrService", FakeOcrService)
    runtime.cloud.answer = fail_cloud

    result = runtime.handle("Jarvis look at the last screenshot you took")

    assert result.ok
    assert "fake-local" in result.message
    assert "Dialog asks" in result.message


def test_spoken_confirmation_answers_accept_bare_or_jarvis_prefixed_yes_no(tmp_path: Path) -> None:
    from jarvis_app.ui import JarvisWindow

    runtime = build_runtime(tmp_path)
    window = object.__new__(JarvisWindow)
    window.runtime = runtime

    assert window._approval_answer("yes") is True
    assert window._approval_answer("Jarvis yes") is True
    assert window._approval_answer("no") is False
    assert window._approval_answer("Jarvis no") is False
    assert window._approval_answer("maybe") is None
