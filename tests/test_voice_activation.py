from __future__ import annotations

from jarvis_app.local_speech import LocalSpeechRecognizer, normalize_voice_phrase


def test_voice_normalization_handles_apostrophes() -> None:
    assert normalize_voice_phrase("Wake up Daddy's Home") == "wake up daddys home"


def test_voice_requires_activation_then_jarvis_command() -> None:
    commands: list[str] = []
    statuses: list[str] = []
    recognizer = LocalSpeechRecognizer(commands.append, on_status=statuses.append)

    recognizer._handle_text("Jarvis remind me to call Alex")
    assert commands == []

    recognizer._handle_text("Wake up Daddy's Home")
    assert commands == []
    assert recognizer.activated
    assert "Welcome Home Sir." in statuses

    recognizer._handle_text("remind me to call Alex")
    assert commands == []

    recognizer._handle_text("Jarvis remind me to call Alex")
    assert commands == ["Jarvis remind me to call Alex"]


def test_voice_sleep_disarms_recognizer() -> None:
    commands: list[str] = []
    statuses: list[str] = []
    recognizer = LocalSpeechRecognizer(commands.append, on_status=statuses.append)

    recognizer._handle_text("Wake up Daddy's Home")
    recognizer._handle_text("go to sleep")
    recognizer._handle_text("Jarvis open notepad")

    assert not recognizer.activated
    assert commands == []
    assert "Going to sleep, sir." in statuses


def test_voice_jarvis_sleep_signals_disarm_before_dispatch() -> None:
    for phrase in ["Jarvis bedtime", "Jarvis power off", "Jarvis good night", "Jarvis stand down"]:
        commands: list[str] = []
        statuses: list[str] = []
        recognizer = LocalSpeechRecognizer(commands.append, on_status=statuses.append)

        recognizer._handle_text("Wake up Daddy's Home")
        recognizer._handle_text(phrase)

        assert not recognizer.activated
        assert commands == []
        assert "Going to sleep, sir." in statuses


def test_voice_activation_accepts_common_transcription_variant() -> None:
    commands: list[str] = []
    recognizer = LocalSpeechRecognizer(commands.append)

    recognizer._handle_text("wake up daddy is home")

    assert recognizer.activated


def test_voice_activation_accepts_jarvis_startup_phrases() -> None:
    for phrase in ["Jarvis wake up", "Jarvis turn on", "Jarvis power on", "Jarvis come online", "Jarvis start listening"]:
        commands: list[str] = []
        statuses: list[str] = []
        recognizer = LocalSpeechRecognizer(commands.append, on_status=statuses.append)

        recognizer._handle_text(phrase)

        assert recognizer.activated
        assert commands == []
        assert "Welcome Home Sir." in statuses


def test_voice_activation_accepts_noisy_jarvis_wake_up_transcriptions() -> None:
    for phrase in [
        "Jarvis, wake up",
        "Jarvis wakeup",
        "Jervis wake up",
        "Jar vis wake up",
        "Jarvis week up",
        "Jarvis wake app",
        "Travis wake up",
    ]:
        commands: list[str] = []
        statuses: list[str] = []
        recognizer = LocalSpeechRecognizer(commands.append, on_status=statuses.append)

        recognizer._handle_text(phrase)

        assert recognizer.activated, phrase
        assert commands == []
        assert "Welcome Home Sir." in statuses


def test_voice_activation_does_not_treat_sleep_phrase_as_noisy_startup() -> None:
    commands: list[str] = []
    recognizer = LocalSpeechRecognizer(commands.append)

    recognizer._handle_text("Jarvis turn off")

    assert not recognizer.activated
    assert commands == []


def test_voice_activation_still_ignores_jarvis_commands_until_active() -> None:
    commands: list[str] = []
    recognizer = LocalSpeechRecognizer(commands.append)

    recognizer._handle_text("Jarvis open notepad")

    assert not recognizer.activated
    assert commands == []


def test_voice_confirmation_answers_pass_through_while_active() -> None:
    commands: list[str] = []
    recognizer = LocalSpeechRecognizer(commands.append)

    recognizer._handle_text("Wake up Daddy's Home")
    recognizer._handle_text("yes")
    recognizer._handle_text("no")

    assert commands == ["yes", "no"]
