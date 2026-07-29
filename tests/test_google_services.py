from __future__ import annotations

import base64
from pathlib import Path

from jarvis_app.google_services import GoogleServices
from jarvis_app.storage import JsonStore


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeCalendarEvents:
    def __init__(self) -> None:
        self.list_args = None
        self.insert_body = None

    def list(self, **kwargs):
        self.list_args = kwargs
        return FakeRequest(
            {
                "items": [
                    {
                        "id": "event1",
                        "summary": "Standup",
                        "start": {"dateTime": "2026-07-11T09:00:00-07:00"},
                        "end": {"dateTime": "2026-07-11T09:30:00-07:00"},
                    }
                ]
            }
        )

    def insert(self, **kwargs):
        self.insert_body = kwargs["body"]
        return FakeRequest({"id": "created1"})

    def get(self, **_kwargs):
        return FakeRequest(
            {
                "id": "created1",
                "summary": self.insert_body["summary"],
                "start": self.insert_body["start"],
                "end": self.insert_body["end"],
                "htmlLink": "https://calendar.test/created1",
            }
        )


class FakeCalendarService:
    def __init__(self) -> None:
        self.resource = FakeCalendarEvents()

    def events(self):
        return self.resource


class FakeMessages:
    def __init__(self) -> None:
        self.search_query = None

    def list(self, **kwargs):
        self.search_query = kwargs["q"]
        return FakeRequest({"messages": [{"id": "message1"}]})

    def get(self, **_kwargs):
        return FakeRequest(
            {
                "id": "message1",
                "threadId": "thread1",
                "snippet": "Invoice attached",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sam@example.com"},
                        {"name": "Subject", "value": "July invoice"},
                        {"name": "Date", "value": "Fri, 10 Jul 2026"},
                    ]
                },
            }
        )


class FakeDrafts:
    def __init__(self) -> None:
        self.raw_message = ""
        self.sent_id = ""

    def create(self, **kwargs):
        self.raw_message = kwargs["body"]["message"]["raw"]
        return FakeRequest({"id": "draft1"})

    def get(self, **_kwargs):
        return FakeRequest({"id": "draft1", "message": {"id": "message2"}})

    def send(self, **kwargs):
        self.sent_id = kwargs["body"]["id"]
        return FakeRequest({"id": "message3", "threadId": "thread2"})


class FakeGmailUsers:
    def __init__(self) -> None:
        self.message_resource = FakeMessages()
        self.draft_resource = FakeDrafts()

    def messages(self):
        return self.message_resource

    def drafts(self):
        return self.draft_resource


class FakeGmailService:
    def __init__(self) -> None:
        self.resource = FakeGmailUsers()

    def users(self):
        return self.resource


def google_services(tmp_path: Path) -> GoogleServices:
    return GoogleServices(JsonStore(tmp_path))


def test_calendar_requests_return_real_event_views(tmp_path: Path) -> None:
    google = google_services(tmp_path)
    service = FakeCalendarService()
    google._service = lambda _name, _version: service

    events = google.calendar_search("dentist")
    created = google.calendar_create("Project Review", "tomorrow at 2 PM")

    assert service.resource.list_args["q"] == "dentist"
    assert events[0]["id"] == "event1"
    assert service.resource.insert_body["summary"] == "Project Review"
    assert created["id"] == "created1"
    assert created["link"] == "https://calendar.test/created1"


def test_gmail_search_draft_and_send_use_verified_api_results(tmp_path: Path) -> None:
    google = google_services(tmp_path)
    service = FakeGmailService()
    google._service = lambda _name, _version: service

    messages = google.gmail_search("invoice")
    draft = google.gmail_create_draft("sam@example.com", "Proposal", "Attached is the proposal.")
    sent = google.gmail_send_draft(draft["id"])

    raw = service.resource.draft_resource.raw_message
    decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
    assert service.resource.message_resource.search_query == "invoice"
    assert messages[0]["subject"] == "July invoice"
    assert "To: sam@example.com" in decoded
    assert "Attached is the proposal." in decoded
    assert draft["message_id"] == "message2"
    assert service.resource.draft_resource.sent_id == "draft1"
    assert sent["message_id"] == "message3"
