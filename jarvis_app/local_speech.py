from __future__ import annotations

import json
import hashlib
import io
import os
import queue
import re
import tempfile
import threading
import time
import wave
import winsound
from collections.abc import Callable
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pythoncom
import win32com.client

from .app_config import ACTIVATION_PHRASE, DEFAULT_DATA_DIR, MAX_TTS_INPUT_CHARS, WAKE_PHRASE
from .elevenlabs_config import get_elevenlabs_api_key, get_elevenlabs_model_id, get_elevenlabs_voice_id
from .openai_config import get_openai_api_key
from .security import SecurityViolation
from .storage import JsonStore, redact_sensitive_text, utc_now_iso


def normalize_voice_phrase(text: str) -> str:
    lowered = text.lower().replace("'", "").replace(chr(8217), "")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


SLEEP_PHRASES = {
    "bed time",
    "bedtime",
    "dismissed",
    "go offline",
    "go to sleep",
    "good night",
    "goodnight",
    "power down",
    "power off",
    "rest",
    "shut down",
    "shutdown",
    "sleep",
    "stand by",
    "stand down",
    "standby",
    "stop listening",
    "take a break",
    "that is all",
    "that ll be all",
    "that will be all",
    "thats all",
    "turn off",
}


ELEVENLABS_PCM_SAMPLE_RATES = {
    "pcm_16000": 16_000,
    "pcm_22050": 22_050,
    "pcm_24000": 24_000,
}


def generate_elevenlabs_wav(text: str, settings: dict[str, Any], timeout: float = 30.0) -> bytes:
    api_key = get_elevenlabs_api_key()
    voice_id = get_elevenlabs_voice_id(settings)
    if not api_key or not voice_id:
        raise ValueError("ElevenLabs requires ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID.")

    output_format = str(settings.get("elevenlabs_tts_output_format", "pcm_24000"))
    sample_rate = ELEVENLABS_PCM_SAMPLE_RATES.get(output_format)
    if sample_rate is None:
        raise ValueError(f"Unsupported ElevenLabs output format: {output_format}")

    payload = json.dumps(
        {
            "text": text,
            "model_id": get_elevenlabs_model_id(settings),
        }
    ).encode("utf-8")
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{quote(voice_id, safe='')}"
        f"?output_format={output_format}"
    )
    request = Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/pcm",
            "xi-api-key": api_key,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            pcm_audio = response.read()
    except HTTPError as exc:
        raw_detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_detail = json.loads(raw_detail)
            detail_value = parsed_detail.get("detail", parsed_detail) if isinstance(parsed_detail, dict) else parsed_detail
            if isinstance(detail_value, dict):
                detail = str(detail_value.get("message") or detail_value.get("status") or detail_value)
            else:
                detail = str(detail_value)
        except (json.JSONDecodeError, AttributeError):
            detail = raw_detail
        detail = redact_sensitive_text(detail.replace(api_key, "[REDACTED]")).strip()
        suffix = f": {detail[:300]}" if detail else ""
        raise RuntimeError(f"ElevenLabs request failed with HTTP {exc.code}{suffix}") from exc
    if not pcm_audio:
        raise RuntimeError("ElevenLabs returned an empty audio response.")

    wav_audio = io.BytesIO()
    with wave.open(wav_audio, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_audio)
    return wav_audio.getvalue()


STARTUP_PHRASES = {
    "activate",
    "boot",
    "boot up",
    "come online",
    "engage",
    "go online",
    "listen",
    "online",
    "power on",
    "start",
    "start listening",
    "start up",
    "turn on",
    "wake",
    "wake up",
}

JARVIS_WAKE_WORD_VARIANTS = {
    "charvis",
    "jar ves",
    "jar vis",
    "jar vise",
    "jar voice",
    "jar us",
    "jar this",
    "jarves",
    "jarviss",
    "javis",
    "jervis",
    "travis",
}

WAKE_UP_STARTUP_VARIANTS = {
    "awake",
    "wait up",
    "wake app",
    "wake me up",
    "wake us",
    "wakeups",
    "wakeup",
    "waking up",
    "way cup",
    "week up",
}

VOICE_CONFIRMATION_PHRASES = {
    "approve",
    "approved",
    "cancel",
    "confirm",
    "do it",
    "do not",
    "dont",
    "go ahead",
    "never mind",
    "no",
    "nope",
    "okay",
    "ok",
    "proceed",
    "stop",
    "sure",
    "yes",
    "yeah",
    "yep",
}


class LocalSpeechPolicy:
    """Hard guardrail: microphone audio never leaves the machine."""

    cloud_audio_allowed = False

    def assert_local_only(self) -> None:
        if self.cloud_audio_allowed:
            raise SecurityViolation("Cloud audio is not allowed.")

    def export_audio(self, *_args: Any, **_kwargs: Any) -> None:
        raise SecurityViolation("Exporting voice recordings is disabled.")


class LocalTextToSpeech:
    def __init__(
        self,
        voice_name: str = "",
        settings: dict[str, Any] | None = None,
        settings_saver: Callable[[], None] | None = None,
        store: JsonStore | None = None,
        status_callback: Callable[[str], None] | None = None,
        activity_callback: Callable[[bool], None] | None = None,
    ) -> None:
        self.voice_name = voice_name
        self.settings = settings or {}
        self.settings_saver = settings_saver
        self.store = store
        self.status_callback = status_callback
        self.activity_callback = activity_callback
        self._lock = threading.Lock()
        self._voice = None
        self.available = False
        self.error: str | None = None
        self._init_voice()

    def _init_voice(self) -> None:
        try:
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            if self.voice_name:
                voices = self._voice.GetVoices()
                for index in range(voices.Count):
                    voice = voices.Item(index)
                    if self.voice_name.lower() in voice.GetDescription().lower():
                        self._voice.Voice = voice
                        break
            self.available = True
        except Exception as exc:
            self.error = str(exc)
            self.available = False

    def voices(self) -> list[str]:
        if not self._voice:
            return []
        voices = self._voice.GetVoices()
        return [voices.Item(index).GetDescription() for index in range(voices.Count)]

    def speak_async(self, text: str) -> None:
        if not text.strip():
            return
        threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    def _speak(self, text: str) -> None:
        self._notify_activity(True)
        try:
            with self._lock:
                if self._speak_cloud_tts(text):
                    return
                pythoncom.CoInitialize()
                try:
                    voice = win32com.client.Dispatch("SAPI.SpVoice")
                    if self.voice_name:
                        voices = voice.GetVoices()
                        for index in range(voices.Count):
                            candidate = voices.Item(index)
                            if self.voice_name.lower() in candidate.GetDescription().lower():
                                voice.Voice = candidate
                                break
                    voice.Speak(text)
                except Exception:
                    self.available = False
                finally:
                    pythoncom.CoUninitialize()
        finally:
            self._notify_activity(False)

    def _notify_activity(self, active: bool) -> None:
        if self.activity_callback:
            try:
                self.activity_callback(active)
            except Exception:
                pass

    def _speak_cloud_tts(self, text: str) -> bool:
        if not self.settings.get("allow_cloud_tts", False):
            return False
        provider = str(self.settings.get("tts_provider", "elevenlabs")).lower()
        if provider == "openai":
            return self._speak_openai_tts(text)
        if provider == "elevenlabs":
            return self._speak_elevenlabs_tts(text)
        return False

    def _speak_openai_tts(self, text: str) -> bool:
        api_key = get_openai_api_key(self.store)
        if not api_key:
            self._report_cloud_tts_error("OpenAI", "API key is not configured")
            return False
        try:
            from openai import OpenAI
        except Exception as exc:
            self._report_cloud_tts_error("OpenAI", f"client is unavailable: {exc}")
            return False

        try:
            spoken_text = text[:MAX_TTS_INPUT_CHARS]
            cache_path = self._tts_cache_path(spoken_text)
            if cache_path and cache_path.exists():
                winsound.PlaySound(str(cache_path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
                return True

            client = OpenAI(api_key=api_key)
            response = client.audio.speech.create(
                model=str(self.settings.get("openai_tts_model", "gpt-4o-mini-tts")),
                voice=str(self.settings.get("openai_tts_voice", "fable")),
                input=spoken_text,
                instructions=str(
                    self.settings.get(
                        "openai_tts_instructions",
                        "Speak with a calm, precise, realistic British assistant tone.",
                    )
                ),
                response_format="wav",
            )
            self._play_wav(response.content, cache_path)
            self._track_tts_usage(len(spoken_text))
            self._clear_cloud_tts_error()
            return True
        except Exception as exc:
            self._report_cloud_tts_error("OpenAI", exc)
            return False

    def _speak_elevenlabs_tts(self, text: str) -> bool:
        if not get_elevenlabs_api_key() or not get_elevenlabs_voice_id(self.settings):
            self._report_cloud_tts_error("ElevenLabs", "API key or voice ID is not configured")
            return False
        try:
            spoken_text = text[:MAX_TTS_INPUT_CHARS]
            cache_path = self._tts_cache_path(spoken_text)
            if cache_path and cache_path.exists():
                winsound.PlaySound(str(cache_path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
                return True

            wav_audio = generate_elevenlabs_wav(spoken_text, self.settings)
            self._play_wav(wav_audio, cache_path)
            self._track_tts_usage(len(spoken_text))
            self._clear_cloud_tts_error()
            return True
        except Exception as exc:
            self._report_cloud_tts_error("ElevenLabs", exc)
            return False

    def _report_cloud_tts_error(self, provider: str, error: object) -> None:
        message = redact_sensitive_text(str(error)).rstrip(". ")
        status = f"{provider} TTS failed: {message}. Using local Windows voice."
        self.settings["tts_last_error"] = status
        self.settings["tts_last_error_at"] = utc_now_iso()
        if self.settings_saver:
            try:
                self.settings_saver()
            except Exception:
                pass
        if self.status_callback:
            try:
                self.status_callback(status)
            except Exception:
                pass

    def _clear_cloud_tts_error(self) -> None:
        if not self.settings.get("tts_last_error"):
            return
        self.settings["tts_last_error"] = ""
        self.settings["tts_last_error_at"] = ""
        if self.settings_saver:
            try:
                self.settings_saver()
            except Exception:
                pass

    def _play_wav(self, audio: bytes, cache_path: Path | None) -> None:
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(audio)
            self._prune_tts_cache(cache_path.parent)
            winsound.PlaySound(str(cache_path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            path = tmp.name
            tmp.write(audio)
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _tts_cache_path(self, text: str) -> Path | None:
        if not self.settings.get("cache_tts_audio", False):
            return None
        cache_dir = Path(str(self.settings.get("tts_cache_folder", DEFAULT_DATA_DIR / "tts_cache"))).resolve()
        provider = str(self.settings.get("tts_provider", "elevenlabs"))
        if provider == "elevenlabs":
            provider_settings = [
                get_elevenlabs_model_id(self.settings),
                get_elevenlabs_voice_id(self.settings),
                str(self.settings.get("elevenlabs_tts_output_format", "pcm_24000")),
            ]
        else:
            provider_settings = [
                str(self.settings.get("openai_tts_model", "")),
                str(self.settings.get("openai_tts_voice", "")),
                str(self.settings.get("openai_tts_instructions", "")),
            ]
        identity = "|".join([provider, *provider_settings, text])
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        return cache_dir / f"{digest}.wav"

    def _prune_tts_cache(self, cache_dir: Path) -> None:
        max_items = int(self.settings.get("max_tts_cache_items", 50) or 50)
        if max_items < 1:
            return
        files = sorted(cache_dir.glob("*.wav"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files[max_items:]:
            try:
                path.unlink()
            except OSError:
                pass

    def _track_tts_usage(self, chars: int) -> None:
        month = datetime.now().strftime("%Y-%m")
        if self.settings.get("tts_usage_month") != month:
            self.settings["tts_usage_month"] = month
            self.settings["tts_monthly_chars"] = 0
        self.settings["tts_monthly_chars"] = int(self.settings.get("tts_monthly_chars", 0) or 0) + chars
        if self.settings_saver:
            try:
                self.settings_saver()
            except Exception:
                pass


class _SapiRecognitionEvents:
    def OnRecognition(self, _stream_number: int, _stream_position: object, _recognition_type: int, result: object) -> None:
        text = result.PhraseInfo.GetText()
        if hasattr(self, "on_text"):
            self.on_text(text)


class LocalSpeechRecognizer:
    """Windows SAPI dictation adapter.

    It is best-effort because microphone permissions and installed recognition
    engines vary by Windows machine. Failure keeps the app in typed mode.
    """

    def __init__(
        self,
        on_text: Callable[[str], None],
        wake_phrase: str = WAKE_PHRASE,
        activation_phrase: str = ACTIVATION_PHRASE,
        on_status: Callable[[str], None] | None = None,
        vosk_model_path: str | Path | None = None,
    ) -> None:
        self.on_text = on_text
        self.on_status = on_status
        self.wake_phrase = wake_phrase.lower()
        self.activation_phrase = activation_phrase
        self._normalized_wake_phrase = normalize_voice_phrase(wake_phrase)
        self._normalized_activation_phrase = normalize_voice_phrase(activation_phrase)
        self._activation_variants = {
            self._normalized_activation_phrase,
            "wake up daddy is home",
            "wake up daddys home",
            "wake up daddies home",
            "wake up daddy s home",
        }
        self.vosk_model_path = Path(vosk_model_path or DEFAULT_DATA_DIR / "vosk-model-small-en-us-0.15")
        self.policy = LocalSpeechPolicy()
        self.available = False
        self.listening = False
        self.activated = False
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._events: queue.Queue[str] = queue.Queue()

    def start(self) -> None:
        self.policy.assert_local_only()
        if self.listening:
            return
        self.error = None
        self.activated = False
        self._stop.clear()
        self.listening = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.listening = False
        self.activated = False
        self.available = False
        self._notify("Voice stopped")

    def poll(self) -> list[str]:
        texts: list[str] = []
        while True:
            try:
                texts.append(self._events.get_nowait())
            except queue.Empty:
                return texts

    def _run(self) -> None:
        first_error: str | None = None
        if self.vosk_model_path.exists():
            try:
                self._run_vosk()
                return
            except Exception as exc:
                first_error = f"Vosk failed: {exc}"
                self._notify(first_error)

        pythoncom.CoInitialize()
        try:
            recognizer = win32com.client.Dispatch("SAPI.SpInprocRecognizer")
            audio_inputs = recognizer.GetAudioInputs()
            if audio_inputs.Count == 0:
                raise RuntimeError("No local SAPI microphone input is available.")
            recognizer.AudioInput = audio_inputs.Item(0)
            context = recognizer.CreateRecoContext()
            sink = win32com.client.WithEvents(context, _SapiRecognitionEvents)
            sink.on_text = self._handle_text
            grammar = context.CreateGrammar()
            grammar.DictationSetState(1)
            self.available = True
            self._notify("Listening locally. Say Wake up Daddy's Home.")
            while not self._stop.is_set():
                pythoncom.PumpWaitingMessages()
                time.sleep(0.05)
            grammar.DictationSetState(0)
        except Exception as exc:
            self.error = f"{first_error}; SAPI failed: {exc}" if first_error else str(exc)
            self.available = False
            self._notify(f"Local recognition unavailable: {self.error}")
        finally:
            self.listening = False
            pythoncom.CoUninitialize()

    def _run_vosk(self) -> None:
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except Exception as exc:
            raise RuntimeError(f"offline speech packages are unavailable: {exc}") from exc

        audio_queue: queue.Queue[bytes] = queue.Queue()
        device_info = sd.query_devices(kind="input")
        sample_rate = int(device_info["default_samplerate"])
        model = Model(str(self.vosk_model_path))
        if self._stop.is_set():
            self.available = False
            self.listening = False
            return
        recognizer = KaldiRecognizer(model, sample_rate)

        def callback(indata: bytes, _frames: int, _time_info: object, status: object) -> None:
            if status:
                self._notify(f"Microphone status: {status}")
            audio_queue.put(bytes(indata))

        try:
            self.available = True
            self._notify("Listening locally with Vosk. Say Wake up Daddy's Home.")
            with sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=8000,
                dtype="int16",
                channels=1,
                callback=callback,
            ):
                while not self._stop.is_set():
                    try:
                        data = audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if recognizer.AcceptWaveform(data):
                        result = json.loads(recognizer.Result())
                        text = str(result.get("text", "")).strip()
                        if text:
                            self._handle_text(text)
        finally:
            self.available = False
            self.listening = False

    def _handle_text(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        normalized = normalize_voice_phrase(cleaned)

        if not self.activated:
            if self._is_activation_phrase(normalized):
                self.activated = True
                self._notify("Welcome Home Sir.")
            return

        if self._is_sleep_phrase(normalized):
            self.activated = False
            self._notify("Going to sleep, sir.")
            return

        if normalized in VOICE_CONFIRMATION_PHRASES:
            self._events.put(cleaned)
            self.on_text(cleaned)
            return

        if normalized == self._normalized_wake_phrase:
            self._notify("Ready. Say Jarvis, then the command.")
            return

        if normalized.startswith(f"{self._normalized_wake_phrase} "):
            self._events.put(cleaned)
            self.on_text(cleaned)
            return

        self._notify("Active, waiting for Jarvis command.")

    def _is_activation_phrase(self, normalized: str) -> bool:
        if normalized in self._activation_variants:
            return True
        if self._is_jarvis_startup_phrase(normalized):
            return True
        return max(SequenceMatcher(None, normalized, variant).ratio() for variant in self._activation_variants) >= 0.88

    def _is_jarvis_startup_phrase(self, normalized: str) -> bool:
        phrase = self._startup_phrase_after_wake_word(normalized)
        if phrase is None:
            return False
        if phrase in STARTUP_PHRASES or phrase in WAKE_UP_STARTUP_VARIANTS:
            return True
        if phrase and self._looks_like_wake_up_phrase(phrase):
            return True
        return max(SequenceMatcher(None, phrase, startup_phrase).ratio() for startup_phrase in STARTUP_PHRASES) >= 0.9

    def _startup_phrase_after_wake_word(self, normalized: str) -> str | None:
        if normalized.startswith(f"{self._normalized_wake_phrase} "):
            return normalized[len(self._normalized_wake_phrase):].strip()

        tokens = normalized.split()
        if len(tokens) < 2:
            return None

        for word_count in range(min(2, len(tokens) - 1), 0, -1):
            wake_candidate = " ".join(tokens[:word_count])
            if self._looks_like_wake_word(wake_candidate):
                return " ".join(tokens[word_count:]).strip()
        return None

    def _looks_like_wake_word(self, phrase: str) -> bool:
        if phrase == self._normalized_wake_phrase:
            return True
        if self._normalized_wake_phrase == "jarvis" and phrase in JARVIS_WAKE_WORD_VARIANTS:
            return True

        compact_phrase = phrase.replace(" ", "")
        compact_wake_phrase = self._normalized_wake_phrase.replace(" ", "")
        if len(compact_phrase) < max(4, len(compact_wake_phrase) - 2):
            return False
        return SequenceMatcher(None, compact_phrase, compact_wake_phrase).ratio() >= 0.82

    def _looks_like_wake_up_phrase(self, phrase: str) -> bool:
        words = phrase.split()
        if not words or words[0] not in {"awake", "wait", "wake", "wakeup", "waking", "way", "week"}:
            return False
        return SequenceMatcher(None, phrase, "wake up").ratio() >= 0.7

    def _is_sleep_phrase(self, normalized: str) -> bool:
        phrases = {normalized}
        if normalized.startswith(f"{self._normalized_wake_phrase} "):
            phrases.add(normalized[len(self._normalized_wake_phrase):].strip())
        return any(self._sleep_similarity(phrase) >= 0.9 for phrase in phrases if phrase)

    def _sleep_similarity(self, phrase: str) -> float:
        if phrase in SLEEP_PHRASES:
            return 1.0
        return max(SequenceMatcher(None, phrase, sleep_phrase).ratio() for sleep_phrase in SLEEP_PHRASES)

    def _notify(self, message: str) -> None:
        if self.on_status:
            self.on_status(message)
