from __future__ import annotations

import argparse
import getpass

from .actions import ActionRegistry
from .app_config import APP_VERSION
from .assistant import AssistantRuntime
from .google_services import GoogleServiceError, GoogleServices
from .health import health_report
from .local_speech import LocalTextToSpeech
from .openai_config import clear_openai_api_key, set_openai_api_key
from .security import SecurityManager
from .storage import JsonStore
from .ui import JarvisWindow


def build_app() -> JarvisWindow:
    store = JsonStore()
    security = SecurityManager(store.settings)
    google = GoogleServices(store)
    actions = ActionRegistry(store, security, google)
    runtime = AssistantRuntime(store, actions, security)
    tts = LocalTextToSpeech(str(store.settings.get("voice_name", "")), store.settings, store.save_settings, store)
    return JarvisWindow(runtime, tts)


def main() -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Private Jarvis desktop assistant")
    parser.add_argument("--health", action="store_true", help="print local health diagnostics and exit")
    parser.add_argument("--version", action="store_true", help="print the app version and exit")
    parser.add_argument("--set-openai-key", action="store_true", help="store an OpenAI API key encrypted in .jarvis_data/environment")
    parser.add_argument("--clear-openai-key", action="store_true", help="remove the locally stored encrypted OpenAI API key")
    parser.add_argument("--connect-google", action="store_true", help="authorize Gmail and Google Calendar in the browser")
    parser.add_argument("--disconnect-google", action="store_true", help="remove the locally stored encrypted Google OAuth token")
    parser.add_argument("--google-status", action="store_true", help="show Gmail and Google Calendar connection status")
    args = parser.parse_args()
    if args.set_openai_key:
        store = JsonStore()
        key = getpass.getpass("OpenAI API key: ")
        try:
            set_openai_api_key(store, key)
        except ValueError as exc:
            print(f"Could not store key: {exc}")
            return
        print("Stored OpenAI API key in .jarvis_data/environment using Windows DPAPI encryption.")
        return
    if args.clear_openai_key:
        removed = clear_openai_api_key(JsonStore())
        print("Removed local OpenAI API key." if removed else "No local OpenAI API key was stored.")
        return
    if args.connect_google:
        store = JsonStore()
        google = GoogleServices(store)
        try:
            status = google.connect()
        except GoogleServiceError as exc:
            print(f"Could not connect Google: {exc}")
            return
        print(f"Google connected. {status.reason}")
        return
    if args.disconnect_google:
        removed = GoogleServices(JsonStore()).disconnect()
        print("Removed local Google OAuth token." if removed else "No local Google OAuth token was stored.")
        return
    if args.google_status:
        print(GoogleServices(JsonStore()).status_summary())
        return
    if args.version:
        print(f"Private Jarvis {APP_VERSION}")
        return
    if args.health:
        print(health_report(JsonStore()))
        return
    app = build_app()
    app.run()


if __name__ == "__main__":
    main()
