# Private Jarvis

Security-first Windows desktop assistant prototype.

Current version: `0.6.0` with a CustomTkinter animated command HUD.

## Run

Install or repair the `jarvis` command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_jarvis_command.ps1
```

After installation, open a new PowerShell or Command Prompt and run:

```powershell
jarvis
```

Direct project run:

```powershell
python run_jarvis.py
```

Diagnostics:

```powershell
jarvis --health
python run_jarvis.py --health
```

Repair the launcher and print diagnostics:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\repair_environment.ps1
```

## API Credentials

The project root contains an ignored `.env` file for local OpenAI and ElevenLabs credentials:

```dotenv
OPENAI_API_KEY=
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_MODEL_ID=eleven_flash_v2_5
```

Fill in the values after each `=` and restart Jarvis. Do not add quotes unless they are part of the value. The `.env` file is plaintext, is excluded by `.gitignore`, and is loaded only when a variable is not already set in Windows or the launching shell. `.env.example` is the safe template to commit.

Find the ElevenLabs voice ID for a voice you are licensed to use in the ElevenLabs voice library. The API key should be restricted to the text-to-speech permissions and quota Jarvis needs.

Jarvis can also store your OpenAI key in a stronger local form instead of plaintext. The recommended OpenAI setup stores it under `.jarvis_data/environment/secrets.json`, encrypted with Windows DPAPI for your Windows account.

Recommended one-time setup:

```powershell
jarvis --set-openai-key
```

Jarvis will prompt for the key without echoing it. Do not put keys in source code, `README.md`, or `.jarvis_data/settings.json`.

Remove the locally stored key:

```powershell
jarvis --clear-openai-key
```

The same OpenAI key is used for ChatGPT-style text answers and optional OpenAI TTS. Microphone audio is still never sent to OpenAI or ElevenLabs. The encrypted local OpenAI key takes priority over `OPENAI_API_KEY` from `.env` or Windows.

## Voice Privacy Rule

Microphone audio never goes to cloud services or AI services.

The app uses local speech recognition only. It prefers Vosk with a local model under `.jarvis_data/vosk-model-small-en-us-0.15`, then falls back to Windows SAPI only if a registered local SAPI engine is available. If local speech recognition is unavailable or inaccurate, use the typed command box. Typed text may be routed to ChatGPT only when the command starts with `Jarvis`. Audio remains blocked either way.

## Voice Activation

Voice mode starts automatically when the app opens.

1. Say: `Wake up Daddy's Home`, or say `Jarvis, wake up` / `Jarvis, turn on`
2. Jarvis replies: `Welcome Home Sir.`
3. Wait for the HUD to show `ACTIVE`.
4. Say: `Jarvis, ...` followed by the command.
5. To power down the app, say a sleep/off phrase such as `Jarvis, bedtime`

Examples:

- `Wake up Daddy's Home`
- `Jarvis, wake up`
- `Jarvis, turn on`
- `Jarvis, power on`
- `Jarvis, come online`
- `Jarvis, remind me to call Alex at 4 PM`
- `Jarvis, list reminders`
- `Jarvis, search files for budget`
- `Jarvis, create note Project Alpha saying First draft is ready`
- `Jarvis, take screenshot`
- `Jarvis, bedtime`
- `Jarvis, power off`
- `go to sleep`

Typed commands do not require the activation phrase. You can type `Jarvis, remind me...` or just `remind me...`.

## Current Functionality

- CustomTkinter command HUD with a state-driven reactor, speech animation, moving telemetry, and operations console.
- Async command handling so the HUD keeps animating while ChatGPT text requests are in flight.
- Automatic local listening on launch.
- Local text-to-speech through Windows SAPI as fallback.
- Optional OpenAI TTS for more realistic speech when explicitly enabled and a local OpenAI key is configured.
- Local speech recognition through Vosk with a local model.
- Windows SAPI recognition fallback where available.
- Typed command fallback.
- Activation phrase: `Wake up Daddy's Home`.
- Alternate Jarvis-prefixed activation phrases such as `Jarvis, wake up`, `Jarvis, turn on`, `Jarvis, power on`, and `Jarvis, come online`.
- Command prefix after activation: `Jarvis, ...`.
- Sleep/off phrases power down the app.
- Local reminders.
- Local note creation, listing, and reading.
- Save the previous Jarvis response to a local note.
- Local OCR scanning from images and captured screenshots into notes.
- Explicit local memory for preferences.
- Approved-folder file search.
- Local screenshot capture with confirmation.
- Approved app launching.
- Multi-command workflows using `then` or `and then`.
- ChatGPT-generated text handoff to Notepad through a local `.txt` file.
- Local time/date answers.
- Local health diagnostics.
- Safe planner routing for natural `Jarvis, ...` requests that map to approved tools.
- ChatGPT-style answers for unknown `Jarvis, ...` commands that do not map to local tools.
- Voice provider status, test command, provider switching, optional TTS cache, and TTS usage character tracking.
- OAuth-backed Gmail search/draft/send and Google Calendar read/search/create actions.
- Security gate that blocks cloud audio, file deletion, email deletion, unapproved shell commands, and app closing.

## Commands

Voice commands require activation first:

1. `Wake up Daddy's Home`, or a Jarvis-prefixed startup phrase such as `Jarvis, wake up`
2. Wait for `Welcome Home Sir.`
3. Say `Jarvis, ...`

Typed commands can be entered directly. Open-ended cloud-text answers still require the `Jarvis` prefix.

### Wake, Help, And Status

- `help`
- `what can you do`
- `security status`
- `status`
- `health check`
- `system health`
- `diagnostics`
- `run diagnostics`
- `what time is it`
- `time`
- `current time`
- `what date is it`
- `date`
- `today's date`
- `todays date`
- `Wake up Daddy's Home`
- `Jarvis, wake up`
- `Jarvis, wake`
- `Jarvis, turn on`
- `Jarvis, power on`
- `Jarvis, start listening`
- `Jarvis, start up`
- `Jarvis, come online`
- `Jarvis, go online`
- `Jarvis, activate`
- `Jarvis, engage`
- `Jarvis, bedtime`
- `Jarvis, power off`
- `Jarvis, good night`
- `Jarvis, stand down`
- `go to sleep`
- `power down`

Sleep/off phrases power down the app.

### ChatGPT Text Answers

- `Jarvis, explain black holes simply`
- `Jarvis, write a short packing list for a weekend trip`
- `Jarvis, answer this question: ...`
- `Jarvis, brainstorm ideas for ...`
- `Jarvis, rewrite this paragraph: ...`
- `Jarvis, draft an email to Taylor about the launch and put it in Notepad`
- `Jarvis, draft an email to Taylor about the launch and save it to my notes`
- `Jarvis, write a short packing list and put it in a notepad`

Open-ended answers only go to ChatGPT when the command starts with `Jarvis`. Before cloud text is used, Jarvis tries to route natural wording to approved local tools. Non-Jarvis unknown text stays local and is not sent to cloud AI.

### Multi-Command Workflows

- `Jarvis, take a note that the budget is approved and then show my notes`
- `Jarvis, set a timer for five minutes then show timers`
- `Jarvis, open notepad then show reminders`
- `Jarvis, draft an email to Sam and put it in Notepad`
- `Jarvis, write a short email to Sam then save it to my notes`

Use `then` or `and then` to chain existing commands in one voice request. Each step still runs through the same local parser, allowlists, and confirmation rules. For example, screenshot capture and approved shell commands still ask for yes/no confirmation inside a chain.

Generated text can be handed to Notepad with phrases like `and put it in Notepad` or `and save it to a text file`. Jarvis asks ChatGPT for the requested text, saves it under `.jarvis_data/notepad`, and opens that `.txt` file with the approved Notepad app.

Generated text can also be saved directly to notes with phrases like `and save it to my notes` or `and put it in a note`. Jarvis asks ChatGPT for the requested text, saves it under `.jarvis_data/notes`, and can later list or read that note locally.

### Reminders

- `remind me to call Alex at 4 PM`
- `remind me at 4 PM to call Alex`
- `set a reminder for 11:15`
- `remind me tomorrow to call Alex`
- `set reminder for tomorrow to send the report`
- `set a reminder to check the oven at 7`
- `list reminders`
- `show reminders`
- `what are my reminders`
- `edit reminder <id> to call Jordan at 5 PM`
- `reschedule reminder <id> for tomorrow at 9 AM`
- `complete reminder <id>`
- `finish reminder <id>`
- `done reminder <id>`
- `delete reminder <id>`
- `remove reminder <id>`

Reminders are structured scheduled records with `description`, `date`, `time`, and `due_at` fields. Bare times like `11:15` schedule for today if still upcoming, otherwise tomorrow. When the desktop app is open, due reminders are announced in the UI and spoken through the configured reply voice. Deleting a reminder asks for confirmation.

### Timers

- `set a timer for five minutes`
- `start a 10 minute timer`
- `start a tea timer for 3 minutes`
- `list timers`
- `show timers`
- `cancel timer <id>`

Timers are stored locally in `.jarvis_data/timers.json`. When the desktop app is open, due timers are announced in the UI and spoken through the configured reply voice.

### Notes

- `create note Project Alpha saying First draft is ready`
- `write note Grocery List saying eggs, milk, coffee`
- `take a note that the budget is approved`
- `add this to my notes: reorder filters`
- `save this in my notes: review the estimate`
- `save this email to my notes: Please review the Q3 plan`
- `save the email content to my notes: Please review the Q3 plan`
- `save it to my notes`
- `save the last response to my notes`
- `draft an email to Sam and save it to my notes`
- `note that the budget is approved`
- `write down: send the proposal Friday`
- `write this down: send the proposal Friday`
- `list notes`
- `show notes`
- `what notes do I have`
- `read note Project Alpha`
- `open note Project Alpha`
- `show note Project Alpha`
- `scan latest screenshot`
- `look at the last screenshot you took`
- `scan image C:\path\to\whiteboard.png`
- `ocr image C:\path\to\whiteboard.png`
- `read text from C:\path\to\whiteboard.png`

Notes are stored locally under `.jarvis_data/notes` by default. Jarvis can create, list, read, and search those local markdown notes. `save it to my notes` saves the previous Jarvis response, while commands with a colon save the text after the colon. OCR is local-only through Tesseract. If Tesseract is not installed, scan commands fail safely with setup guidance.

Notes are plain text files, not scheduled reminders. Use reminders when Jarvis should notify you at a specific date and time.

### Memory

- `remember that I prefer short answers`
- `what do you remember`
- `show memories`
- `list memories`
- `what do you remember about schedule`
- `forget memory <id>`
- `forget that I prefer short answers`

Memory is local and explicit. Jarvis rejects memory text that looks like an API key, token, password, or secret.

### Files

- `search files for budget`
- `search file for budget`
- `find files for meeting notes`
- `find file meeting notes`
- `Jarvis, find my budget notes`
- `Jarvis, locate the project document`
- `summarize file C:\path\to\file.md`
- `Jarvis, summarize document C:\path\to\file.md`

File search only runs inside approved folders. By default, the workspace folder is approved.

### Screen

- `take screenshot`
- `capture screen`
- `scan screen`
- `scan latest screenshot`
- `ocr latest screenshot`
- `look at the last screenshot you took`

Screenshots are saved locally under `.jarvis_data/screenshots`. Capture requires confirmation because screen contents may be sensitive. Jarvis asks in the command log and voice channel; answer `yes` or `no` by voice or typed input. Looking at the latest screenshot uses local OCR and creates a note with extracted text.

### Voice

- `voice status`
- `voice settings`
- `tts status`
- `sound settings`
- `test voice`
- `voice test`
- `test your voice`
- `set voice provider local`
- `set voice provider windows`
- `set voice provider sapi`
- `set voice provider openai`
- `set voice provider elevenlabs`
- `use openai voice`
- `enable voice cache`
- `turn on voice cache`
- `disable voice cache`
- `turn off voice cache`

Changing provider or cache settings asks for confirmation. Cloud TTS sends only Jarvis reply text when enabled; microphone audio still never leaves the machine. ElevenLabs Flash v2.5 is the low-latency default, with OpenAI `cedar` and Windows SAPI available as fallbacks. The cache is disabled by default because cached reply audio may contain private information.

### Apps

- `open notepad`
- `open calculator`
- `open calc`
- `open paint`
- `open explorer`
- `open chrome`
- `open edge`
- `open firefox`
- `open slack`
- `open discord`
- `open github desktop`
- `open word`
- `open excel`
- `open powerpoint`
- `open power point`
- `open outlook`
- `open teams`
- `open onenote`
- `open vs code`

Only approved apps can be launched, and this action only opens the app; it does not send commands into the app or close it. The generated-text Notepad workflow creates a local `.txt` file and opens that file in Notepad. The app allowlist is defined in `jarvis_app/app_config.py` as `APPROVED_APP_COMMANDS`.

### Gmail And Calendar

These commands use the live Google APIs after desktop OAuth is connected.

- `what meetings do I have today`
- `what is on my calendar today`
- `what is on my schedule today`
- `search calendar for dentist`
- `search email for invoice`
- `find gmail for invoice`
- `search gmail for invoice`
- `draft email to Sam saying I will send the proposal Friday`
- `write an email to Sam about proposal saying I will send it Friday`
- `send email draft <draft-id>`
- `google status`
- `schedule meeting Project Review at Friday 2 PM`
- `create calendar event Project Review at Friday 2 PM`
- `set appointment Dentist at next Thursday 3 PM`

Calendar creation requires confirmation. Email drafts are created without sending; sending a draft requires a separate UI review.

To connect Google:

1. Enable the Gmail and Google Calendar APIs in a Google Cloud project and create a Desktop app OAuth client.
2. Save the downloaded client JSON as `.jarvis_data/environment/google-oauth-client.json`, or set `GOOGLE_OAUTH_CLIENT_SECRET_FILE` to its path.
3. Run `jarvis --connect-google` and finish consent in the browser.
4. Verify the connection with `jarvis --google-status` or `google status`.

The resulting OAuth token is encrypted for the current Windows account with DPAPI. Run `jarvis --disconnect-google` to remove it.

### Natural Local Planner

These `Jarvis, ...` requests are routed to approved local tools instead of ChatGPT when possible:

- `Jarvis, find my budget notes`
- `Jarvis, locate the project document`
- `Jarvis, add this to my notes: reorder filters`
- `Jarvis, show my reminders`
- `Jarvis, set a timer for five minutes`
- `Jarvis, scan this screenshot`
- `Jarvis, remember that I prefer short answers`
- `Jarvis, what do you remember about meetings`
- `Jarvis, show my email about invoice`
- `Jarvis, run diagnostics`
- `Jarvis, test your voice`
- `Jarvis, run shell command python version`
- `Jarvis, show approved shell commands`
- `Jarvis, take a note that sequence works and then show my notes`
- `Jarvis, draft an email to Sam and put it in Notepad`

The planner refuses unapproved shell-like and destructive requests, including requests to run arbitrary PowerShell, delete files, wipe folders, delete email, or format drives. The app and shell allowlists are defined in `jarvis_app/app_config.py` as `APPROVED_APP_COMMANDS` and `APPROVED_SHELL_COMMANDS`.

### Terminal Commands

- `jarvis`
- `jarvis --health`
- `jarvis --version`
- `jarvis --set-openai-key`
- `jarvis --clear-openai-key`
- `jarvis --connect-google`
- `jarvis --google-status`
- `jarvis --disconnect-google`
- `python run_jarvis.py`
- `python run_jarvis.py --health`
- `python run_jarvis.py --version`
- `powershell -ExecutionPolicy Bypass -File .\scripts\install_jarvis_command.ps1`
- `powershell -ExecutionPolicy Bypass -File .\scripts\repair_environment.ps1`

## Security Model

See [SECURITY_AUDIT.md](SECURITY_AUDIT.md) for the latest audit notes.

Always blocked:

- Sending microphone audio to cloud services.
- Sending voice recordings to AI services.
- Running unapproved shell commands.
- Deleting files.
- Deleting Gmail messages.
- Closing applications.

Requires confirmation or review:

- Screenshots, answered with typed or spoken yes/no.
- Reminder deletion.
- Forgetting local memories.
- Approved shell commands.
- Voice provider changes.
- Reply-audio cache changes.
- Calendar creation once Google is connected.
- Sending an existing Gmail draft once Google is connected.
- File move/rename if implemented later.

Allowed automatically:

- Local structured reminders with due notifications.
- Local countdown timers.
- Local note creation/listing/reading.
- Local OCR scanning inside approved folders or Jarvis data folders.
- Local memory creation/listing.
- Approved-folder file search.
- Approved app opening only.
- Opening generated text in Notepad through a local `.txt` file.
- Local time/date answers.
- Health diagnostics.

## Data Locations

Default local data folder:

```text
.jarvis_data
```

Important files:

- `.jarvis_data/settings.json`
- `.jarvis_data/history.json`
- `.jarvis_data/reminders.json`
- `.jarvis_data/timers.json`
- `.jarvis_data/memories.json`
- `.jarvis_data/tool_audit.json`
- `.jarvis_data/environment/secrets.json`
- `.jarvis_data/environment/google-oauth-client.json`
- `.jarvis_data/notes`
- `.jarvis_data/notepad`
- `.jarvis_data/screenshots`
- `.jarvis_data/tts_cache`

`.jarvis_data` is ignored by git.

## Settings

The app creates `.jarvis_data/settings.json` on first run.

Useful settings:

- `activation_phrase`: defaults to `wake up daddy's home`
- `wake_phrase`: defaults to `jarvis`
- `approved_folders`: folders Jarvis may search
- `notes_folder`: where local notes are stored
- `notepad_folder`: where generated Notepad handoff files are stored
- `screenshots_folder`: where screenshots are stored
- `allow_cloud_text_ai`: default `true`
- `cloud_text_requires_jarvis`: default `true`
- `openai_text_model`: default `gpt-5.5`
- `openai_max_output_tokens`: default `320` to keep spoken answers responsive
- `openai_request_timeout_seconds`: default `20`
- `allow_cloud_tts`: default `false`; this local profile is currently `true` at your request
- `tts_provider`: default `elevenlabs`
- `openai_tts_model`: default `gpt-4o-mini-tts`
- `openai_tts_voice`: default/current `cedar`
- `openai_tts_instructions`: adult male British private-assistant style
- `elevenlabs_tts_model`: default `eleven_flash_v2_5` for lower reply latency
- `elevenlabs_voice_id`: optional settings fallback; prefer `ELEVENLABS_VOICE_ID` in `.env`
- `elevenlabs_tts_output_format`: default `pcm_24000` for Windows WAV playback
- `cache_tts_audio`: default `false`
- `tts_cache_folder`: defaults to `.jarvis_data/tts_cache`
- `tts_monthly_chars`: generated TTS character counter
- `openai_tts_estimated_cost_per_1m_chars`: optional local estimate rate
- `include_memory_in_cloud_text`: default `false`
- `ocr_language`: default `eng`
- `tesseract_cmd`: optional path to `tesseract.exe`
- `google_oauth_client_secret_file`: path to the Google Desktop OAuth client JSON
- `allow_cloud_image_analysis`: default `false`
- `cloud_audio_allowed`: always forced to `false`
- `vosk_model_path`: defaults to `.jarvis_data/vosk-model-small-en-us-0.15`

Restart the app after editing settings.

## Troubleshooting

### Voice does not activate

- Say: `Wake up Daddy's Home`
- Listen for: `Welcome Home Sir.`
- Watch for the HUD to change to `ACTIVE`.
- Then say: `Jarvis, list reminders`

If it still does not work, check that `.jarvis_data/vosk-model-small-en-us-0.15` exists. Typed commands will still work.

Run this for a full local diagnostic report:

```powershell
jarvis --health
```

### Commands trigger at the wrong time

Voice commands are ignored until activation. After activation, commands must start with `Jarvis`.

Say `go to sleep`, `Jarvis, bedtime`, `Jarvis, power off`, `Jarvis, good night`, or `Jarvis, stand down` to power down the app.

### Text looks small or blurry

The UI now uses a larger text panel with no visible scrollbar. If Windows display scaling still makes text soft, try running the app on your primary monitor or adjust Windows display scaling.

### ChatGPT Answers

Set your OpenAI API key once:

```powershell
jarvis --set-openai-key
```

Jarvis stores it encrypted under `.jarvis_data/environment/secrets.json` using Windows DPAPI. The key is not stored in `.jarvis_data/settings.json`.

Remove the local key:

```powershell
jarvis --clear-openai-key
```

Then ask open-ended questions with `Jarvis` at the start:

```text
Jarvis, explain how solar panels work
```

Microphone audio is still never sent to OpenAI. Only the recognized text after local Vosk transcription can be sent.

If Jarvis says OpenAI rejected the configured key, the app found a key but OpenAI did not accept it. Create a fresh key at https://platform.openai.com/api-keys, then run `jarvis --set-openai-key` again. The app trims accidental spaces, quotes, and a leading `Bearer ` prefix, but it cannot repair a deleted, expired, copied-wrong, or non-API key.

### Realistic Voice

See [VOICE_OPTIONS.md](VOICE_OPTIONS.md) for researched options. The app supports local Windows SAPI plus optional OpenAI and ElevenLabs TTS. Use `voice status`, `test voice`, `set voice provider local`, `set voice provider openai`, or `set voice provider elevenlabs`. Cloud voice failures fall back to Windows SAPI.

### OCR

Install Tesseract locally and make sure `tesseract` is on PATH, or set `tesseract_cmd` in `.jarvis_data/settings.json`. OCR does not use cloud image analysis.

### Local History

The app keeps a bounded local audit history in `.jarvis_data/history.json`. Secret-looking text such as API keys, tokens, passwords, and `sk-...` keys is redacted before storage.

## Tests

```powershell
python -m pytest -q
python -m compileall jarvis_app tests
```
