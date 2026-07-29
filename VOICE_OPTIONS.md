# Realistic Assistant Voice Options

## Boundary

The app should not clone or imitate the exact *Iron Man* Jarvis actor voice. For private use, the safe target is a licensed, realistic British male assistant voice with a calm, precise delivery.

## Best Options

### 1. ElevenLabs

Best fit for realism and a cinematic assistant feel.

- Strong naturalness and emotional delivery.
- Voice Library supports filtering by language, accent, gender, age, and category.
- Text-to-speech API can generate speech from selected voice IDs.
- Choose a licensed British male voice from the Voice Library, put its voice ID and your API key in `.env`, then run `Jarvis, set voice provider ElevenLabs`.

Sources:

- https://elevenlabs.io/docs/eleven-creative/playground/text-to-speech
- https://elevenlabs.io/docs/eleven-creative/voices/voice-library
- https://elevenlabs.io/docs/api-reference/text-to-speech/convert

### 2. OpenAI Text-to-Speech

Best fit for simple integration because the app already uses the OpenAI SDK for ChatGPT-style text answers.

- The app now has an optional OpenAI TTS path.
- It sends only Jarvis reply text to OpenAI, never microphone audio.
- Current voice setting is `cedar`, with an adult male British-assistant instruction.
- OpenAI's built-in voices do not publish gender/accent labels in the API reference; Jarvis uses the `voice` value plus the TTS `instructions` field to target the British male assistant style.
- You can change `openai_tts_voice` in `.jarvis_data/settings.json`.

Sources:

- https://developers.openai.com/api/docs/guides/text-to-speech
- https://developers.openai.com/api/docs/guides/text
- https://developers.openai.com/api/docs/api-reference/responses

### 3. Azure AI Speech

Best fit for predictable, enterprise-style British voices.

- Azure lists several English UK neural voices, including male voices such as `en-GB-RyanNeural`, `en-GB-AlfieNeural`, `en-GB-ElliotNeural`, `en-GB-EthanNeural`, `en-GB-NoahNeural`, `en-GB-OliverNeural`, and HD voices such as `en-GB-Ollie`.
- Good candidate if you want a stable British voice with less experimentation than ElevenLabs.

Source:

- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts

## Recommendation

Use this order:

1. ElevenLabs Flash v2.5 for the default low-latency reply voice, provided the account has available API credits.
2. OpenAI TTS as the alternate cloud provider.
3. Azure Speech if you prefer a reliable British neural voice with clear Microsoft documentation and predictable voice IDs.

## Current App Settings

The app defaults to:

```json
{
  "tts_provider": "elevenlabs",
  "allow_cloud_tts": true,
  "openai_tts_model": "gpt-4o-mini-tts",
  "openai_tts_voice": "cedar",
  "openai_tts_instructions": "Speak as a polished adult male British private assistant...",
  "cache_tts_audio": false
}
```

Cloud TTS is opt-in because reply text can contain private data. In this local build ElevenLabs is selected and cloud TTS is enabled at your request. If the selected provider is unavailable, Jarvis reports the provider error and falls back to local Windows SAPI.

Implemented commands:

- `Jarvis, voice status`
- `Jarvis, test voice`
- `Jarvis, set voice provider local`
- `Jarvis, set voice provider openai`
- `Jarvis, set voice provider elevenlabs`
- `Jarvis, enable voice cache`
- `Jarvis, disable voice cache`

Changing provider or cache settings asks for confirmation. The app tracks generated TTS characters by month; cost estimates are local-only and require setting `openai_tts_estimated_cost_per_1m_chars`.

## Privacy

- Microphone audio remains local.
- Voice recognition remains local through Vosk.
- Cloud TTS receives only reply text.
- Cached TTS audio is disabled by default and stored locally only when explicitly enabled.
- Cloud ChatGPT receives only text from `Jarvis, ...` requests that do not match local commands.
