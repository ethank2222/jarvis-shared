from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .storage import JsonStore, SecretStore


GOOGLE_TOKEN_SECRET_NAME = "google_oauth_token"
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
)


class GoogleServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleStatus:
    gmail_connected: bool
    calendar_connected: bool
    reason: str


class GoogleServices:
    """OAuth-backed Gmail and Calendar adapter with DPAPI-encrypted tokens."""

    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self._credentials: Any | None = None
        self.status = self._build_status()

    def connect(self) -> GoogleStatus:
        client_file = self.client_secret_path()
        if not client_file.is_file():
            raise GoogleServiceError(
                f"Google OAuth client file was not found at {client_file}. "
                "Create a Desktop OAuth client, enable Gmail and Calendar APIs, and save its JSON there."
            )
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except Exception as exc:  # pragma: no cover - environment-specific
            raise GoogleServiceError(f"Google OAuth client is unavailable: {exc}") from exc

        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), list(GOOGLE_SCOPES))
        credentials = flow.run_local_server(port=0, open_browser=True, access_type="offline", prompt="consent")
        SecretStore(self.store).set_secret(GOOGLE_TOKEN_SECRET_NAME, credentials.to_json())
        self._credentials = credentials
        self.status = self._build_status()
        return self.status

    def disconnect(self) -> bool:
        self._credentials = None
        removed = SecretStore(self.store).delete_secret(GOOGLE_TOKEN_SECRET_NAME)
        self.status = self._build_status()
        return removed

    def client_secret_path(self) -> Path:
        configured = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_FILE", "").strip()
        if not configured:
            configured = str(
                self.store.settings.get(
                    "google_oauth_client_secret_file",
                    self.store.base_dir / "environment" / "google-oauth-client.json",
                )
            ).strip()
        return Path(configured).expanduser().resolve()

    def status_summary(self) -> str:
        state = "connected" if self.status.gmail_connected and self.status.calendar_connected else "not connected"
        return f"Google services: {state}. {self.status.reason}"

    def calendar_today(self) -> list[dict[str, str]]:
        now = datetime.now().astimezone()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self._calendar_events(start.isoformat(), end.isoformat())

    def calendar_search(self, query: str) -> list[dict[str, str]]:
        clean_query = query.strip()
        if not clean_query:
            raise GoogleServiceError("Calendar search needs a query.")
        now = datetime.now().astimezone()
        end = now + timedelta(days=365)
        return self._calendar_events(now.isoformat(), end.isoformat(), query=clean_query)

    def calendar_create(self, title: str, time_text: str, duration_minutes: int = 60) -> dict[str, str]:
        clean_title = title.strip()
        clean_time = time_text.strip()
        if not clean_title or not clean_time:
            raise GoogleServiceError("Calendar creation needs both a title and a date/time.")
        try:
            import dateparser
            from tzlocal import get_localzone_name
        except Exception as exc:  # pragma: no cover - environment-specific
            raise GoogleServiceError(f"Natural-language date parser is unavailable: {exc}") from exc

        timezone_name = get_localzone_name()
        start = dateparser.parse(
            clean_time,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": timezone_name,
                "TO_TIMEZONE": timezone_name,
            },
        )
        if start is None:
            raise GoogleServiceError(f"I could not understand the event time '{clean_time}'.")
        if start.tzinfo is None:
            start = start.replace(tzinfo=datetime.now().astimezone().tzinfo)
        end = start + timedelta(minutes=max(5, min(duration_minutes, 24 * 60)))
        body = {
            "summary": clean_title,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        service = self._service("calendar", "v3")
        created = service.events().insert(calendarId="primary", body=body).execute()
        event_id = str(created.get("id", ""))
        if not event_id:
            raise GoogleServiceError("Google Calendar did not return an event ID.")
        verified = service.events().get(calendarId="primary", eventId=event_id).execute()
        return self._calendar_event_view(verified)

    def gmail_search(self, query: str) -> list[dict[str, str]]:
        clean_query = query.strip()
        if not clean_query:
            raise GoogleServiceError("Gmail search needs a query.")
        service = self._service("gmail", "v1")
        response = service.users().messages().list(userId="me", q=clean_query, maxResults=10).execute()
        results: list[dict[str, str]] = []
        for item in response.get("messages", []):
            message = service.users().messages().get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = {
                header.get("name", "").lower(): header.get("value", "")
                for header in message.get("payload", {}).get("headers", [])
            }
            results.append(
                {
                    "id": str(message.get("id", "")),
                    "thread_id": str(message.get("threadId", "")),
                    "from": str(headers.get("from", "")),
                    "subject": str(headers.get("subject", "(no subject)")),
                    "date": str(headers.get("date", "")),
                    "snippet": str(message.get("snippet", "")),
                }
            )
        return results

    def gmail_create_draft(self, to: str, subject: str, body: str) -> dict[str, str]:
        if not to.strip() or not body.strip():
            raise GoogleServiceError("A Gmail draft needs a recipient and body.")
        message = EmailMessage()
        message["To"] = to.strip()
        message["Subject"] = subject.strip()
        message.set_content(body.strip())
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        service = self._service("gmail", "v1")
        draft = service.users().drafts().create(userId="me", body={"message": {"raw": encoded}}).execute()
        draft_id = str(draft.get("id", ""))
        if not draft_id:
            raise GoogleServiceError("Gmail did not return a draft ID.")
        verified = service.users().drafts().get(userId="me", id=draft_id, format="metadata").execute()
        return {
            "id": str(verified.get("id", draft_id)),
            "message_id": str(verified.get("message", {}).get("id", "")),
            "to": to.strip(),
            "subject": subject.strip(),
            "body": body.strip(),
        }

    def gmail_send_draft(self, draft_id: str) -> dict[str, str]:
        clean_id = draft_id.strip()
        if not clean_id:
            raise GoogleServiceError("Gmail send needs a draft ID.")
        service = self._service("gmail", "v1")
        sent = service.users().drafts().send(userId="me", body={"id": clean_id}).execute()
        message_id = str(sent.get("id", ""))
        if not message_id:
            raise GoogleServiceError("Gmail did not return a sent message ID.")
        return {"draft_id": clean_id, "message_id": message_id, "thread_id": str(sent.get("threadId", ""))}

    def _calendar_events(self, time_min: str, time_max: str, query: str = "") -> list[dict[str, str]]:
        service = self._service("calendar", "v3")
        request: dict[str, Any] = {
            "calendarId": "primary",
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 10,
        }
        if query:
            request["q"] = query
        response = service.events().list(**request).execute()
        return [self._calendar_event_view(item) for item in response.get("items", [])]

    def _calendar_event_view(self, event: dict[str, Any]) -> dict[str, str]:
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", "")
        return {
            "id": str(event.get("id", "")),
            "title": str(event.get("summary", "(untitled event)")),
            "start": str(start),
            "end": str(end),
            "link": str(event.get("htmlLink", "")),
        }

    def _service(self, name: str, version: str) -> Any:
        credentials = self._load_credentials()
        try:
            from googleapiclient.discovery import build
        except Exception as exc:  # pragma: no cover - environment-specific
            raise GoogleServiceError(f"Google API client is unavailable: {exc}") from exc
        try:
            return build(name, version, credentials=credentials, cache_discovery=False)
        except Exception as exc:
            raise GoogleServiceError(f"Could not initialize Google {name}: {exc}") from exc

    def _load_credentials(self) -> Any:
        if self._credentials is not None and self._credentials.valid:
            return self._credentials
        token = SecretStore(self.store).get_secret(GOOGLE_TOKEN_SECRET_NAME)
        if not token:
            raise GoogleServiceError("Google is not connected. Run: jarvis --connect-google")
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            credentials = Credentials.from_authorized_user_info(json.loads(token), list(GOOGLE_SCOPES))
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                SecretStore(self.store).set_secret(GOOGLE_TOKEN_SECRET_NAME, credentials.to_json())
            if not credentials.valid:
                raise GoogleServiceError("Google OAuth credentials are invalid. Run: jarvis --connect-google")
        except GoogleServiceError:
            raise
        except Exception as exc:
            raise GoogleServiceError(f"Google OAuth credentials could not be loaded: {exc}") from exc
        self._credentials = credentials
        self.status = GoogleStatus(True, True, "OAuth token is available.")
        return credentials

    def _build_status(self) -> GoogleStatus:
        try:
            token = SecretStore(self.store).get_secret(GOOGLE_TOKEN_SECRET_NAME)
        except Exception as exc:
            return GoogleStatus(False, False, f"OAuth token could not be read: {exc}")
        if not token:
            return GoogleStatus(False, False, "Run: jarvis --connect-google")
        try:
            info = json.loads(token)
        except json.JSONDecodeError:
            return GoogleStatus(False, False, "Stored OAuth token is invalid; reconnect Google.")
        granted = set(info.get("scopes", []))
        if granted and not set(GOOGLE_SCOPES).issubset(granted):
            return GoogleStatus(False, False, "OAuth scopes changed; run: jarvis --connect-google")
        return GoogleStatus(True, True, "Encrypted OAuth token is configured.")
