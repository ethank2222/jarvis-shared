# Jarvis Security Audit

## Result

Jarvis has been hardened, but no app can honestly be declared "100% secure." The current security posture is suitable for a private local prototype with strict local-audio guarantees and explicit cloud-text boundaries.

## Reviewed Areas

- Local microphone capture and speech recognition.
- OpenAI ChatGPT-style text requests.
- OpenAI text-to-speech output.
- Local TTS fallback.
- Optional reply-audio cache.
- Safe local tool planner.
- Local memory store.
- Local OCR scanning.
- Health diagnostics.
- File search and note reading.
- Screenshot capture.
- Reminder and note actions.
- Multi-command workflows, generated Notepad handoff, and generated/local note handoff.
- Gmail and Calendar OAuth adapters with encrypted refresh-token storage.
- Launcher scripts.
- Local settings, history, and secret storage helpers.
- DPAPI-encrypted local OpenAI key storage.
- Test coverage for blocked actions and cloud payload policy.

## Critical Guarantees

- Microphone audio never goes to cloud services.
- Vosk recognition runs locally.
- Binary/audio-like cloud payloads are blocked by `SecurityManager`.
- ChatGPT text requests require a `Jarvis`-prefixed command.
- OpenAI API key can be stored locally in `.jarvis_data/environment/secrets.json` encrypted with Windows DPAPI.
- Natural-language tool planning executes only approved local actions through `SecurityManager`.
- Multi-command workflow steps still execute through `ActionRegistry` and `SecurityManager`.
- Cloud TTS is opt-in and disabled by default.
- Reply-audio cache is opt-in and disabled by default.
- Cloud image analysis is disabled by default.
- OCR is local-only through Tesseract.
- Shell commands are limited to `APPROVED_SHELL_COMMANDS` in `jarvis_app/app_config.py` and require confirmation.
- File deletion is blocked.
- Gmail deletion is blocked.
- External writes require confirmation or review.

## Hardening Completed

### Cloud Text Gate

Cloud text requests now require structured metadata proving the command came from a `Jarvis, ...` invocation. This is enforced in the central security layer, not only by command parsing.

### Cloud Text Size Limit

Cloud text prompts are capped at `MAX_CLOUD_TEXT_CHARS` to reduce accidental data exfiltration and runaway requests.

### Local OpenAI Key Storage

The preferred OpenAI key setup is `jarvis --set-openai-key`. Jarvis stores the key in `.jarvis_data/environment/secrets.json` using Windows DPAPI encryption tied to the current Windows account. The `OPENAI_API_KEY` environment variable remains supported as a fallback, but the local encrypted key takes priority when present.

### Cloud TTS Opt-In

OpenAI TTS is now disabled by default. It can be re-enabled in `.jarvis_data/settings.json`, but that should be treated as permission to send reply text to OpenAI for speech generation.

Current local profile note: OpenAI TTS has been enabled at the user's request and uses the OpenAI `cedar` voice with an adult male British assistant style instruction. This still sends only reply text, never microphone audio.

### Local History Redaction

The local audit history now redacts common secret-looking text, including API keys, tokens, passwords, and `sk-...` keys. History length and text size are bounded.

### File Search Bounds

Approved-folder file search now:

- Uses a bounded generator.
- Skips hidden folders.
- Skips `node_modules` and `__pycache__`.
- Skips symlinked directories and files.
- Stops after `MAX_SAFE_WALK_FILES`.

### Safe Tool Planner

Natural `Jarvis, ...` requests are routed through a deterministic local planner before any cloud text answer. Planner-selected actions still execute through `ActionRegistry` and `SecurityManager`; unapproved shell-like and destructive requests are refused. Planner selections are logged locally in `tool_audit.json`.

### Multi-Command Workflows

Commands separated with `then` or `and then` are parsed as a bounded workflow and executed one step at a time through the same action registry and security policy. Generated-text-to-Notepad workflows require a Jarvis-prefixed cloud text request, then save a local `.txt` file under `.jarvis_data/notepad` and open it with the allowlisted Notepad command. Generated-text-to-note workflows save local markdown files under `.jarvis_data/notes`. Pronoun-style note commands such as `save it to my notes` reuse the previous Jarvis response locally and do not call cloud AI again.

### Local OCR

Image scanning uses local Tesseract only. The OCR handler accepts images from approved folders or Jarvis data folders, writes extracted text to local notes, and fails safely when Tesseract is missing.

### Explicit Memory

Memory is stored only when the command explicitly asks Jarvis to remember something. Secret-looking values are rejected. Forgetting memory requires confirmation.

### Reply Voice Controls

Voice provider changes and reply-audio cache changes require confirmation. OpenAI TTS, when enabled, receives only reply text. Cache is disabled by default because generated audio may contain private reply content.

### Existing Settings Migration

The current `.jarvis_data/settings.json` was migrated to:

- Keep `cloud_audio_allowed` forced to `false`.
- Keep `cloud_text_requires_jarvis` enabled.
- Turn `allow_cloud_tts` off.
- Mark existing history redacted.

## Residual Risks

- If `allow_cloud_text_ai` is enabled and a local OpenAI key or `OPENAI_API_KEY` fallback is configured, text after `Jarvis, ...` can be sent to OpenAI.
- If `allow_cloud_tts` is enabled, Jarvis reply text can be sent to OpenAI for speech generation.
- If `cache_tts_audio` is enabled, generated reply audio is stored locally and may contain sensitive spoken content.
- Local memories are plaintext in `.jarvis_data/memories.json`.
- OCR notes and saved Jarvis-response notes are plaintext in `.jarvis_data/notes`.
- Generated Notepad handoff files are plaintext in `.jarvis_data/notepad`.
- Local `.jarvis_data` is plaintext except DPAPI-encrypted secrets. Anyone with access to the Windows account may be able to read history, notes, reminders, and screenshots, and DPAPI secrets may be decryptable by that same Windows account.
- Screenshots can capture sensitive information, are stored locally, and require typed or spoken yes/no confirmation.
- The launcher scripts are simple batch files on PATH. If the workspace is modified by malware, the launcher could start modified code.
- Vosk model files are local executable-adjacent data and should come from trusted sources.
- Gmail and Calendar access depends on a user-created Google Desktop OAuth client and grants Calendar event, Gmail read, compose, and send scopes.

## Security Recommendations

1. Keep `cloud_audio_allowed` false.
2. Keep `allow_cloud_tts` false unless you knowingly accept sending reply text to OpenAI. This local profile currently has it enabled by request.
3. Keep `cache_tts_audio` false unless you knowingly accept local storage of generated reply audio.
4. Use `Jarvis, ...` only for text you are comfortable sending to ChatGPT when cloud text is enabled and the request does not map to a local tool.
5. Review `.jarvis_data/history.json`, `.jarvis_data/tool_audit.json`, and `.jarvis_data/memories.json` periodically.
6. Do not approve broad folders such as `C:\Users\ethan` for file search unless necessary.
7. Keep the Google OAuth client JSON and DPAPI-encrypted token under the ignored `.jarvis_data/environment` folder, and disconnect Google when access is no longer needed.
8. Use `jarvis --set-openai-key` instead of plaintext `.env` files for the OpenAI key.
9. Re-run tests after every feature change:

```powershell
python -m pytest -q
python -m compileall jarvis_app tests
```

## Verification

Current automated checks cover:

- Audio-like cloud payload rejection.
- Binary cloud payload rejection.
- Jarvis-only cloud text gate.
- Oversized cloud prompt rejection.
- Cloud TTS default-off posture.
- Approved shell command confirmation policy.
- Sleep/off behavior.
- Local command routing.
- Health diagnostics.
- Safe local planner routing and unapproved shell refusal.
- Multi-command workflow routing and generated Notepad handoff.
- Local OCR-to-note workflow.
- Local memory lifecycle and secret rejection.
- Voice provider settings.
- History redaction and bounding.

Latest expected result:

```text
64 passed
```
