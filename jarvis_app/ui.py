from __future__ import annotations

import ctypes
import math
import re
import threading
import tkinter as tk
from collections import deque
from datetime import datetime

import customtkinter as ctk

from .assistant import AssistantRuntime
from .local_speech import LocalSpeechRecognizer, LocalTextToSpeech, normalize_voice_phrase
from .security import ActionPolicy, ApprovalLevel


BG = "#02070d"
SURFACE = "#06111b"
SURFACE_2 = "#081925"
GRID = "#0b2433"
LINE = "#14506a"
CYAN = "#27d8ff"
BLUE = "#1687ff"
PALE = "#b9f4ff"
TEXT = "#dffaff"
MUTED = "#5c95a8"
GREEN = "#39f2ae"
AMBER = "#ffbf5b"
MAGENTA = "#e56bff"
FONT_MONO = "Cascadia Mono"
APPROVAL_YES = {"approve", "approved", "confirm", "do it", "go ahead", "proceed", "sure", "yes", "yeah", "yep"}
APPROVAL_NO = {"cancel", "do not", "dont", "never mind", "no", "nope", "stop"}


class JarvisWindow:
    def __init__(self, runtime: AssistantRuntime, tts: LocalTextToSpeech) -> None:
        self.runtime = runtime
        self.tts = tts
        self._enable_dpi_awareness()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk(fg_color=BG)
        self.root.title("Jarvis Command Interface")
        self.root.geometry("1320x800")
        self.root.minsize(1080, 680)
        self.root.protocol("WM_DELETE_WINDOW", self._power_down)

        self.phase = 0.0
        self.shutting_down = False
        self.pending_requests = 0
        self.tts_active = False
        self.voice_status = "VOICE OFF"
        self.telemetry: deque[tuple[str, str, str]] = deque(maxlen=14)
        self._main_thread_id = threading.get_ident()
        self.pending_approval: dict[str, object] | None = None

        self.recognizer = LocalSpeechRecognizer(
            self._handle_voice_text,
            runtime.parser.wake_phrase,
            str(runtime.store.settings.get("activation_phrase", "wake up daddy's home")),
            self._handle_voice_status,
            runtime.store.settings.get("vosk_model_path"),
        )

        self._build()
        self.tts.status_callback = self._handle_voice_status
        self.tts.activity_callback = self._handle_tts_activity
        self.root.after(450, self._start_listening)
        self._tick()
        self._check_due_timers()

    def run(self) -> None:
        self.root.mainloop()

    def _enable_dpi_awareness(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def _build(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=0, minsize=380)
        self.root.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0, height=82)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=26, pady=(18, 0))
        header.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkLabel(
            header,
            text="JARVIS // COMMAND INTERFACE",
            text_color=TEXT,
            font=(FONT_MONO, 24, "bold"),
            anchor="w",
        )
        brand.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="LOCAL CORE  /  SECURE TOOL CHANNEL",
            text_color=MUTED,
            font=(FONT_MONO, 10),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.status = ctk.CTkLabel(
            header,
            text="BOOTING",
            text_color=CYAN,
            font=(FONT_MONO, 13, "bold"),
            anchor="e",
        )
        self.status.grid(row=0, column=1, sticky="e", padx=(0, 22))
        self.clock = ctk.CTkLabel(
            header,
            text="00:00:00",
            text_color=MUTED,
            font=(FONT_MONO, 10),
            anchor="e",
        )
        self.clock.grid(row=1, column=1, sticky="e", padx=(0, 22), pady=(4, 0))

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=(20, 8), pady=(10, 26))
        self.canvas.bind("<Configure>", self._draw_static)

        console = ctk.CTkFrame(
            self.root,
            fg_color=SURFACE,
            corner_radius=2,
            border_width=1,
            border_color=LINE,
            width=380,
        )
        console.grid(row=1, column=1, sticky="nsew", padx=(8, 22), pady=(10, 26))
        console.grid_propagate(False)
        console.grid_columnconfigure(0, weight=1)
        console.grid_rowconfigure(2, weight=1)

        console_head = ctk.CTkFrame(console, fg_color="transparent", corner_radius=0)
        console_head.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        console_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            console_head,
            text="OPERATIONS LOG",
            text_color=PALE,
            font=(FONT_MONO, 13, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.channel_label = ctk.CTkLabel(
            console_head,
            text="CHANNEL // LOCAL",
            text_color=GREEN,
            font=(FONT_MONO, 9),
            anchor="e",
        )
        self.channel_label.grid(row=0, column=1, sticky="e")

        separator = ctk.CTkFrame(console, fg_color=LINE, corner_radius=0, height=1)
        separator.grid(row=1, column=0, sticky="ew", padx=18)

        self.transcript = ctk.CTkTextbox(
            console,
            fg_color="#030a11",
            text_color="#80dfff",
            border_width=0,
            corner_radius=0,
            scrollbar_button_color=LINE,
            scrollbar_button_hover_color=BLUE,
            font=(FONT_MONO, 11),
            wrap="word",
            activate_scrollbars=True,
        )
        self.transcript.grid(row=2, column=0, sticky="nsew", padx=18, pady=14)
        self.transcript.bind("<MouseWheel>", self._scroll_transcript)

        command = ctk.CTkFrame(console, fg_color="transparent", corner_radius=0)
        command.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 12))
        command.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(
            command,
            height=42,
            fg_color=SURFACE_2,
            border_color=LINE,
            border_width=1,
            corner_radius=2,
            text_color=TEXT,
            placeholder_text="COMMAND INPUT",
            placeholder_text_color=MUTED,
            font=(FONT_MONO, 11),
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<Return>", lambda _event: self._submit())
        self._button(command, "RUN", self._submit, width=76).grid(row=0, column=1)

        controls = ctk.CTkFrame(console, fg_color="transparent", corner_radius=0)
        controls.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 16))
        controls.grid_columnconfigure((0, 1, 2), weight=1)
        self.listen_button = self._button(controls, "MIC", self._toggle_listen)
        self.listen_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self._button(controls, "STATUS", lambda: self._handle_text("Jarvis health check")).grid(
            row=0, column=1, sticky="ew", padx=5
        )
        self._button(controls, "SECURITY", self._show_security).grid(
            row=0, column=2, sticky="ew", padx=(5, 0)
        )

        self._write("SYSTEM", "Command interface initialized.")
        self._write("SECURITY", "Local audio guard active.")

    def _button(
        self,
        parent: ctk.CTkBaseClass,
        text: str,
        command: object,
        width: int = 90,
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=38,
            fg_color="#0b2b3d",
            hover_color="#10445e",
            border_width=1,
            border_color=LINE,
            corner_radius=2,
            text_color=PALE,
            font=(FONT_MONO, 10, "bold"),
        )

    def _start_listening(self) -> None:
        if self.recognizer.listening:
            return
        self.recognizer.start()
        self.voice_status = "STANDBY"
        self._set_status("STANDBY", CYAN)

    def _submit(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self._handle_text(text)

    def _handle_voice_text(self, text: str) -> None:
        self._queue_ui(lambda: self._handle_text(text, source="VOICE"))

    def _handle_voice_status(self, text: str) -> None:
        self._queue_ui(lambda: self._set_voice_status(text))

    def _handle_tts_activity(self, active: bool) -> None:
        self._queue_ui(lambda: self._set_tts_activity(active))

    def _set_tts_activity(self, active: bool) -> None:
        self.tts_active = active
        if active:
            self._set_status("SPEAKING", CYAN)
            self.channel_label.configure(text="CHANNEL // VOICE OUT", text_color=CYAN)
        elif not self.pending_requests:
            self._set_status("ACTIVE" if self.recognizer.activated else "STANDBY", GREEN if self.recognizer.activated else CYAN)
            self.channel_label.configure(text="CHANNEL // LOCAL", text_color=GREEN)

    def _set_voice_status(self, text: str) -> None:
        self.voice_status = text
        self._write("VOICE", text)
        if text in {"Welcome Home Sir.", "Going to sleep, sir."}:
            self.tts.speak_async(text)
        if text == "Going to sleep, sir.":
            self._set_status("POWERING DOWN", AMBER)
            self._schedule_power_down()

    def _handle_text(self, text: str, source: str = "YOU") -> None:
        if self._handle_pending_approval_response(text, source):
            return
        self._write(source, text)
        self.pending_requests += 1
        self._set_status("PROCESSING", AMBER)
        self.channel_label.configure(text="CHANNEL // TASK", text_color=AMBER)
        threading.Thread(target=self._run_command, args=(text,), daemon=True).start()

    def _run_command(self, text: str) -> None:
        result = self.runtime.handle(text, self._approve_threadsafe)
        self._queue_ui(lambda: self._finish_command(result))

    def _finish_command(self, result: object) -> None:
        from .actions import ActionResult

        self.pending_requests = max(0, self.pending_requests - 1)
        if not isinstance(result, ActionResult):
            result = ActionResult(False, "Error: command worker returned an invalid result.")
        self._write("JARVIS" if result.ok else "FAULT", result.message)
        if result.data and result.data.get("voice_mode") == "sleep":
            self.recognizer.activated = False
            self.voice_status = "POWERING DOWN"
            self._set_status("POWERING DOWN", AMBER)
            self._schedule_power_down()
        elif self.pending_requests:
            self._set_status(f"PROCESSING {self.pending_requests}", AMBER)
        elif result.ok:
            self._set_status("RESPONDING", CYAN)
        else:
            self._set_status("ATTENTION", MAGENTA)
        if result.ok:
            self.tts.speak_async(result.message.splitlines()[0][:240])
        elif not self.pending_requests:
            self.channel_label.configure(text="CHANNEL // FAULT", text_color=MAGENTA)

    def _queue_ui(self, callback: object) -> None:
        try:
            self.root.after(0, callback)
        except (tk.TclError, RuntimeError):
            pass

    def _set_status(self, text: str, color: str) -> None:
        self.status.configure(text=text, text_color=color)

    def _schedule_power_down(self) -> None:
        if self.shutting_down:
            return
        self.shutting_down = True
        self.root.after(2400, self._power_down)

    def _power_down(self) -> None:
        self.shutting_down = True
        try:
            self.recognizer.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _approve(self, policy: ActionPolicy, payload: dict[str, object]) -> bool:
        if policy.approval is ApprovalLevel.REVIEW:
            return self._review_dialog(policy, payload)
        return False

    def _approve_threadsafe(self, policy: ActionPolicy, payload: dict[str, object]) -> bool:
        if policy.approval is ApprovalLevel.CONFIRM:
            return self._confirm_threadsafe(policy, payload)
        if threading.get_ident() == self._main_thread_id:
            return self._approve(policy, payload)
        if self.shutting_down:
            return False
        completed = threading.Event()
        outcome = {"value": False}

        def ask() -> None:
            try:
                outcome["value"] = self._approve(policy, payload)
            finally:
                completed.set()

        self._queue_ui(ask)
        completed.wait()
        return bool(outcome["value"])

    def _confirm_threadsafe(self, policy: ActionPolicy, payload: dict[str, object]) -> bool:
        if self.shutting_down:
            return False
        if threading.get_ident() == self._main_thread_id:
            self._write("CONFIRM", "Confirmation must be answered from the command or voice channel. Cancelled.")
            return False
        completed = threading.Event()
        outcome = {"value": False}

        def ask() -> None:
            self._ask_in_app_confirmation(policy, payload, completed, outcome)

        self._queue_ui(ask)
        if not completed.wait(timeout=45):
            self._queue_ui(lambda: self._timeout_pending_approval(completed))
            return False
        return bool(outcome["value"])

    def _ask_in_app_confirmation(
        self,
        policy: ActionPolicy,
        payload: dict[str, object],
        completed: threading.Event,
        outcome: dict[str, bool],
    ) -> None:
        if self.pending_approval is not None:
            self._write("CONFIRM", "Another confirmation is already pending. Cancelled the new request.")
            completed.set()
            return
        self.pending_approval = {
            "policy": policy,
            "payload": payload,
            "completed": completed,
            "outcome": outcome,
        }
        prompt = self._confirmation_prompt(policy, payload)
        self._write("JARVIS", prompt)
        self._set_status("CONFIRM?", AMBER)
        self.channel_label.configure(text="CHANNEL // CONFIRM", text_color=AMBER)
        self.tts.speak_async(prompt)

    def _confirmation_prompt(self, policy: ActionPolicy, payload: dict[str, object]) -> str:
        if policy.action_id == "screen.capture":
            return "Are you sure you want me to take a screenshot? Say yes or no."
        detail = str(payload.get("command") or payload.get("provider") or payload.get("id") or "").strip()
        suffix = f" ({detail})" if detail else ""
        return f"Are you sure you want to {policy.description.lower()}{suffix}? Say yes or no."

    def _handle_pending_approval_response(self, text: str, source: str) -> bool:
        pending = self.pending_approval
        if pending is None:
            return False
        answer = self._approval_answer(text)
        self._write(source, text)
        if answer is None:
            prompt = "Please answer yes or no."
            self._write("CONFIRM", prompt)
            self.tts.speak_async(prompt)
            return True

        outcome = pending.get("outcome")
        completed = pending.get("completed")
        if isinstance(outcome, dict):
            outcome["value"] = answer
        self.pending_approval = None
        self._write("CONFIRM", "Approved." if answer else "Cancelled.")
        if hasattr(completed, "set"):
            completed.set()
        return True

    def _approval_answer(self, text: str) -> bool | None:
        normalized = normalize_voice_phrase(text)
        wake = normalize_voice_phrase(self.runtime.parser.wake_phrase)
        if normalized.startswith(f"{wake} "):
            normalized = normalized[len(wake) :].strip()
        normalized = re.sub(r"\b(please|jarvis)\b", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if normalized in APPROVAL_YES:
            return True
        if normalized in APPROVAL_NO:
            return False
        return None

    def _timeout_pending_approval(self, completed: threading.Event) -> None:
        pending = self.pending_approval
        if pending is None or pending.get("completed") is not completed:
            return
        self.pending_approval = None
        self._write("CONFIRM", "No yes or no response received. Cancelled.")
        if not self.pending_requests:
            self._set_status("ATTENTION", MAGENTA)
            self.channel_label.configure(text="CHANNEL // FAULT", text_color=MAGENTA)

    def _review_dialog(self, policy: ActionPolicy, payload: dict[str, object]) -> bool:
        dialog = ctk.CTkToplevel(self.root, fg_color=BG)
        dialog.title("Review Action")
        dialog.geometry("560x390")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            dialog,
            text=policy.description.upper(),
            text_color=CYAN,
            font=(FONT_MONO, 13, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        text = ctk.CTkTextbox(
            dialog,
            fg_color=SURFACE,
            text_color=PALE,
            border_width=1,
            border_color=LINE,
            corner_radius=2,
            font=(FONT_MONO, 10),
            wrap="word",
        )
        text.grid(row=1, column=0, sticky="nsew", padx=20)
        text.insert("1.0", str(payload))
        text.configure(state="disabled")
        approved = {"value": False}

        def close(value: bool) -> None:
            approved["value"] = value
            dialog.destroy()

        row = ctk.CTkFrame(dialog, fg_color="transparent", corner_radius=0)
        row.grid(row=2, column=0, sticky="e", padx=20, pady=20)
        self._button(row, "CANCEL", lambda: close(False)).grid(row=0, column=0, padx=(0, 8))
        self._button(row, "APPROVE", lambda: close(True)).grid(row=0, column=1)
        self.root.wait_window(dialog)
        return approved["value"]

    def _show_security(self) -> None:
        self._write("SECURITY", "\n".join(self.runtime.security.security_summary()))

    def _toggle_listen(self) -> None:
        if self.recognizer.listening:
            self.recognizer.stop()
            self.voice_status = "VOICE OFF"
            self._set_status("VOICE OFF", MUTED)
            self.listen_button.configure(text="MIC")
            return
        self.recognizer.start()
        self.voice_status = "STANDBY"
        self._set_status("STANDBY", CYAN)
        self.listen_button.configure(text="MIC ON")

    def _write(self, speaker: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        clean = str(text).strip()
        preview = " ".join(clean.split())[:48]
        self.telemetry.append((stamp, speaker.upper(), preview))
        self.transcript.configure(state="normal")
        self.transcript.insert(tk.END, f"[{stamp}] {speaker.upper()}\n{clean}\n\n")
        self.transcript.configure(state="disabled")
        self.transcript.see(tk.END)

    def _scroll_transcript(self, event: tk.Event) -> str:
        self.transcript.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _tick(self) -> None:
        if self.shutting_down:
            return
        self.phase += 0.065
        self.clock.configure(text=datetime.now().strftime("%Y-%m-%d  //  %H:%M:%S"))
        self._draw_hud()
        self.root.after(40, self._tick)

    def _check_due_timers(self) -> None:
        if self.shutting_down:
            return
        try:
            due_timers = self.runtime.actions.due_timers()
            due_reminders = self.runtime.actions.due_reminders()
        except Exception as exc:
            self._write("FAULT", f"Reminder/timer check failed: {exc}")
            due_timers = []
            due_reminders = []
        for timer in due_timers:
            label = str(timer.get("label", "Timer")).strip() or "Timer"
            message = f"Timer complete: {label}."
            self._write("TIMER", message)
            self.tts.speak_async(message)
        for reminder in due_reminders:
            description = str(reminder.get("description") or reminder.get("title") or "Reminder").strip()
            message = f"Reminder: {description}."
            self._write("REMINDER", message)
            self.tts.speak_async(message)
        self.root.after(1000, self._check_due_timers)

    def _draw_static(self, _event: object | None = None) -> None:
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        self.canvas.delete("static")
        self.canvas.create_rectangle(0, 0, width, height, fill=BG, outline="", tags="static")
        for x in range(0, width, 48):
            major = x % 192 == 0
            self.canvas.create_line(x, 0, x, height, fill=LINE if major else GRID, width=1, tags="static")
        for y in range(0, height, 48):
            major = y % 192 == 0
            self.canvas.create_line(0, y, width, y, fill=LINE if major else GRID, width=1, tags="static")
        margin = 18
        bracket = 48
        for x_sign, y_sign in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            x = margin if x_sign > 0 else width - margin
            y = margin if y_sign > 0 else height - margin
            self.canvas.create_line(x, y, x + bracket * x_sign, y, fill=CYAN, width=2, tags="static")
            self.canvas.create_line(x, y, x, y + bracket * y_sign, fill=CYAN, width=2, tags="static")

    def _draw_hud(self) -> None:
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        self.canvas.delete("dynamic")
        cx = width * 0.52
        cy = height * 0.50
        radius = max(122, min(205, width * 0.23, height * 0.30))
        mode, detail, accent = self._visual_state()
        speaking_gain = 1.0 if self.tts_active else 0.25

        self.canvas.create_text(
            30,
            34,
            text="CORE TELEMETRY",
            anchor="w",
            fill=MUTED,
            font=(FONT_MONO, 9),
            tags="dynamic",
        )
        self.canvas.create_text(
            width - 30,
            34,
            text=f"MODE // {mode}",
            anchor="e",
            fill=accent,
            font=(FONT_MONO, 9, "bold"),
            tags="dynamic",
        )

        for index in range(5):
            pulse = math.sin(self.phase * (1.2 + speaking_gain) + index * 0.9) * (3 + speaking_gain * 5)
            ring_radius = radius + index * 18 + pulse
            start = (self.phase * (34 + index * 7) * (-1 if index % 2 else 1) + index * 41) % 360
            extent = 205 - index * 16
            color = [LINE, BLUE, CYAN, LINE, PALE][index]
            self.canvas.create_arc(
                cx - ring_radius,
                cy - ring_radius,
                cx + ring_radius,
                cy + ring_radius,
                start=start,
                extent=extent,
                style=tk.ARC,
                outline=color,
                width=3 if index in {1, 2} else 1,
                tags="dynamic",
            )
            self.canvas.create_arc(
                cx - ring_radius,
                cy - ring_radius,
                cx + ring_radius,
                cy + ring_radius,
                start=start + 220,
                extent=58,
                style=tk.ARC,
                outline=AMBER if index == 3 else color,
                width=2,
                tags="dynamic",
            )

        for tick in range(72):
            angle = math.tau * tick / 72 + self.phase * (0.12 if tick % 2 else -0.08)
            inner = radius * (0.74 if tick % 6 else 0.68)
            outer = radius * (0.82 if tick % 6 else 0.92)
            x1 = cx + math.cos(angle) * inner
            y1 = cy + math.sin(angle) * inner
            x2 = cx + math.cos(angle) * outer
            y2 = cy + math.sin(angle) * outer
            self.canvas.create_line(
                x1,
                y1,
                x2,
                y2,
                fill=PALE if tick % 6 == 0 else LINE,
                width=2 if tick % 6 == 0 else 1,
                tags="dynamic",
            )

        for node in range(8):
            angle = self.phase * (0.8 + node * 0.035) + math.tau * node / 8
            orbit = radius + 54 + (node % 2) * 18
            x = cx + math.cos(angle) * orbit
            y = cy + math.sin(angle) * orbit
            size = 3 + (node % 3)
            self.canvas.create_oval(x - size, y - size, x + size, y + size, fill=accent, outline="", tags="dynamic")
            if node % 2 == 0:
                self.canvas.create_line(cx, cy, x, y, fill=GRID, width=1, tags="dynamic")

        core_pulse = math.sin(self.phase * (4.8 if self.tts_active else 1.8))
        core_radius = radius * 0.43 + core_pulse * (10 if self.tts_active else 3)
        for glow in range(4, 0, -1):
            glow_radius = core_radius + glow * 8
            self.canvas.create_oval(
                cx - glow_radius,
                cy - glow_radius,
                cx + glow_radius,
                cy + glow_radius,
                outline=[GRID, LINE, BLUE, CYAN][glow - 1],
                width=1,
                tags="dynamic",
            )
        self.canvas.create_oval(
            cx - core_radius,
            cy - core_radius,
            cx + core_radius,
            cy + core_radius,
            fill="#03131e",
            outline=accent,
            width=3,
            tags="dynamic",
        )

        sweep = self.phase * 1.7
        self.canvas.create_line(
            cx,
            cy,
            cx + math.cos(sweep) * radius * 0.92,
            cy + math.sin(sweep) * radius * 0.92,
            fill=accent,
            width=2,
            tags="dynamic",
        )

        self.canvas.create_text(
            cx,
            cy - 30,
            text=mode,
            fill=TEXT,
            font=(FONT_MONO, 20, "bold"),
            tags="dynamic",
        )
        self.canvas.create_text(
            cx,
            cy + 42,
            text=detail,
            fill=accent,
            font=(FONT_MONO, 9),
            tags="dynamic",
        )

        self._draw_voice_bars(cx, cy, radius, accent)
        self._draw_telemetry(width, height, cx, cy, radius)
        self._draw_data_tracks(width, height, accent)

    def _visual_state(self) -> tuple[str, str, str]:
        if self.shutting_down:
            return "SHUTDOWN", "SESSION TERMINATION", AMBER
        if self.tts_active:
            return "SPEAKING", "VOICE SYNTHESIS ACTIVE", CYAN
        if self.pending_requests:
            return "PROCESSING", "COMMAND PIPELINE ACTIVE", AMBER
        if not self.recognizer.listening:
            return "OFFLINE", "VOICE CHANNEL CLOSED", MUTED
        if self.recognizer.activated:
            return "ACTIVE", "COMMAND CHANNEL OPEN", GREEN
        return "STANDBY", "WAKE LOCK ENGAGED", BLUE

    def _draw_voice_bars(self, cx: float, cy: float, radius: float, accent: str) -> None:
        bars = 42
        for index in range(bars):
            angle = math.tau * index / bars
            base = radius * 0.49
            activity = 18 if self.tts_active else 5 if self.pending_requests else 2
            amplitude = abs(math.sin(self.phase * 5.5 + index * 0.73)) * activity
            x1 = cx + math.cos(angle) * base
            y1 = cy + math.sin(angle) * base
            x2 = cx + math.cos(angle) * (base + 5 + amplitude)
            y2 = cy + math.sin(angle) * (base + 5 + amplitude)
            self.canvas.create_line(x1, y1, x2, y2, fill=accent, width=2, tags="dynamic")

    def _draw_telemetry(self, width: int, height: int, cx: float, cy: float, radius: float) -> None:
        events = list(self.telemetry)[-10:]
        left_x = 30
        right_x = width - 30
        start_y = max(92, int(cy - radius - 76))
        for index, (stamp, speaker, preview) in enumerate(events):
            side_left = index % 2 == 0
            row = index // 2
            x = left_x if side_left else right_x
            anchor = "w" if side_left else "e"
            y = start_y + row * 50
            label = f"{stamp} // {speaker[:10]}"
            value = preview[:34]
            color = GREEN if speaker in {"JARVIS", "SECURITY"} else CYAN if speaker in {"VOICE", "SYSTEM"} else MUTED
            self.canvas.create_text(x, y, text=label, anchor=anchor, fill=color, font=(FONT_MONO, 8, "bold"), tags="dynamic")
            self.canvas.create_text(x, y + 17, text=value, anchor=anchor, fill="#6eb4c8", font=(FONT_MONO, 8), tags="dynamic")
            line_start = x + 6 if side_left else x - 6
            line_end = cx - radius - 72 if side_left else cx + radius + 72
            if (side_left and line_end > line_start) or (not side_left and line_end < line_start):
                self.canvas.create_line(line_start, y + 31, line_end, y + 31, fill=GRID, width=1, tags="dynamic")

    def _draw_data_tracks(self, width: int, height: int, accent: str) -> None:
        baseline = height - 46
        self.canvas.create_line(28, baseline, width - 28, baseline, fill=LINE, width=1, tags="dynamic")
        for index in range(18):
            x = 28 + ((self.phase * (28 + index) + index * 61) % max(1, width - 56))
            bar_height = 5 + abs(math.sin(self.phase * 2.6 + index)) * (18 if self.tts_active else 9)
            color = accent if index % 5 == 0 else BLUE
            self.canvas.create_line(x, baseline, x, baseline - bar_height, fill=color, width=2, tags="dynamic")
        self.canvas.create_text(
            30,
            height - 22,
            text="AUDIO LOCAL  //  TOOLS VERIFIED  //  HISTORY REDACTED",
            anchor="w",
            fill=MUTED,
            font=(FONT_MONO, 8),
            tags="dynamic",
        )
