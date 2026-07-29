from __future__ import annotations

import re


NUMBER_WORDS = {
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "eleven": 11.0,
    "twelve": 12.0,
    "thirteen": 13.0,
    "fourteen": 14.0,
    "fifteen": 15.0,
    "sixteen": 16.0,
    "seventeen": 17.0,
    "eighteen": 18.0,
    "nineteen": 19.0,
    "twenty": 20.0,
    "thirty": 30.0,
    "forty": 40.0,
    "fifty": 50.0,
    "sixty": 60.0,
    "half": 0.5,
}

TIMER_DURATION_PATTERN = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|half)"
    r"\s*(?P<unit>hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b",
    re.I,
)


def parse_reminder_command(raw: str) -> dict[str, str] | None:
    text = _clean_command(raw)
    due_first_patterns = (
        r"^remind me (?P<due>.+?) to (?P<title>.+)$",
        r"^(?:set|add|create|make) (?:a )?reminder (?:for|at|on) (?P<due>.+?) (?:to|about) (?P<title>.+)$",
    )
    for pattern in due_first_patterns:
        match = re.match(pattern, text, re.I)
        if match:
            return _reminder_payload(match.group("title"), match.group("due"))

    due_only_patterns = (
        r"^remind me (?:at|on|for) (?P<due>.+)$",
        r"^(?:set|add|create|make) (?:a )?reminder (?:for|at|on) (?P<due>.+)$",
    )
    for pattern in due_only_patterns:
        match = re.match(pattern, text, re.I)
        if match:
            return _reminder_payload("Reminder", match.group("due"))

    title_match = re.match(
        r"^(?:remind me(?: to)?|(?:set|add|create|make) (?:a )?reminder(?: to| about)?) (?P<title>.+)$",
        text,
        re.I,
    )
    if not title_match:
        return None

    title = title_match.group("title").strip()
    due = ""
    explicit_due = re.match(r"^(?P<title>.+?)\s+(?:at|on)\s+(?P<due>.+)$", title, re.I)
    if explicit_due:
        title = explicit_due.group("title").strip()
        due = explicit_due.group("due").strip()
    else:
        trailing_due = re.match(
            r"^(?P<title>.+?)\s+(?P<due>tomorrow(?:\s+.+)?|tonight(?:\s+.+)?|today(?:\s+.+)?|"
            r"in\s+\d+\s+(?:minutes?|hours?|days?)|next\s+\w+(?:\s+.+)?)$",
            title,
            re.I,
        )
        if trailing_due:
            title = trailing_due.group("title").strip()
            due = trailing_due.group("due").strip()
    return _reminder_payload(title, due)


def parse_timer_command(raw: str) -> dict[str, str | int] | None:
    text = _clean_command(raw)
    if not re.search(r"\btimers?\b", text, re.I):
        return None

    duration = _timer_duration(text)
    if duration is None:
        return None

    duration_text, duration_seconds = duration
    label = _timer_label(text, duration_text)
    return {
        "label": label,
        "duration_text": duration_text,
        "duration_seconds": duration_seconds,
    }


def parse_note_command(raw: str) -> dict[str, str] | None:
    text = _clean_command(raw)
    titled = re.match(
        r"^(?:create|write|make) (?:a )?note (?P<title>.+?) (?:saying|that says|with) (?P<body>.+)$",
        text,
        re.I,
    )
    if titled:
        return {"title": titled.group("title").strip(), "body": titled.group("body").strip()}

    source_text_patterns = (
        r"^(?:save|add|put|store) (?:this|the)?\s*(?:email(?: content)?|message|draft|text|content) "
        r"(?:to|in|into|as) (?:my )?notes?\s*:?\s*(?P<body>.+)$",
        r"^(?:create|make|write) (?:a )?note (?:from|for|with) (?:this|the)?\s*"
        r"(?:email(?: content)?|message|draft|text|content)\s*:?\s*(?P<body>.+)$",
    )
    for pattern in source_text_patterns:
        match = re.match(pattern, text, re.I)
        if match:
            body = match.group("body").strip(" .")
            if body and not _is_reference_only_note_body(body):
                return {"title": _quick_note_title(body), "body": body}

    body_patterns = (
        r"^(?:take|create|write|make|add|save) (?:a )?notes? (?:that|saying|about|of|to)?\s*(?P<body>.+)$",
        r"^(?:add|save) (?:this )?(?:to|in) (?:my )?notes?\s*:?\s*(?P<body>.+)$",
        r"^(?:put|save|add) (?P<body>.+?) (?:in|to) (?:my )?notes?$",
        r"^note (?:that|to self(?: that)?)?\s*(?P<body>.+)$",
        r"^write down\s*:?\s*(?P<body>.+)$",
        r"^write this down\s*:?\s*(?P<body>.+)$",
        r"^jot (?:this )?down\s*:?\s*(?P<body>.+)$",
    )
    for pattern in body_patterns:
        match = re.match(pattern, text, re.I)
        if match:
            body = match.group("body").strip(" .")
            if body and not _is_reference_only_note_body(body):
                return {"title": _quick_note_title(body), "body": body}
    return None


def parse_email_draft_command(raw: str) -> dict[str, str] | None:
    text = _clean_command(raw)
    patterns = (
        r"^(?:draft|write) (?:an )?email to (?P<to>.+?) about (?P<subject>.+?) saying (?P<body>.+)$",
        r"^(?:draft|write) (?:an )?email to (?P<to>.+?) saying (?P<body>.+)$",
        r"^(?:draft|write) (?:an )?email to (?P<to>.+?) about (?P<subject>.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, text, re.I)
        if match:
            values = match.groupdict(default="")
            return {
                "to": values["to"].strip(),
                "subject": values.get("subject", "").strip(),
                "body": values.get("body", "").strip(),
            }
    return None


def _clean_command(raw: str) -> str:
    text = raw.strip().strip(" ,.:;")
    return re.sub(
        r"^(?:please\s+|can you\s+|could you\s+|would you\s+|will you\s+|i need you to\s+|i want you to\s+)",
        "",
        text,
        flags=re.I,
    ).strip()


def _reminder_payload(title: str, due: str) -> dict[str, str] | None:
    clean_title = title.strip(" ,.:;")
    clean_due = due.strip(" ,.:;")
    clean_due = re.sub(r"^(?:at|on|for)\s+", "", clean_due, flags=re.I)
    if not clean_title:
        return None
    return {"title": clean_title, "description": clean_title, "due_text": clean_due}


def _quick_note_title(body: str) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", body)
    summary = " ".join(words[:6]).strip()
    return f"Quick Note - {summary}" if summary else "Quick Note"


def _is_reference_only_note_body(body: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", body.lower()).strip()
    return normalized in {
        "it",
        "that",
        "this",
        "this email",
        "the email",
        "the answer",
        "the response",
        "the reply",
        "the draft",
        "the message",
        "the text",
        "last answer",
        "last response",
        "last reply",
        "previous answer",
        "previous response",
        "previous reply",
    }


def _timer_duration(text: str) -> tuple[str, int] | None:
    matches = list(TIMER_DURATION_PATTERN.finditer(text))
    if matches:
        seconds = 0.0
        for match in matches:
            value = _timer_number(match.group("value"))
            if value is None:
                continue
            seconds += value * _timer_unit_seconds(match.group("unit"))
        if seconds <= 0:
            return None
        duration_text = text[matches[0].start() : matches[-1].end()].strip()
        return duration_text, max(1, int(seconds))

    bare_minutes = re.search(r"\btimers?\s+(?:for\s+)?(?P<value>\d{1,3})\b", text, re.I)
    if not bare_minutes:
        bare_minutes = re.search(r"\b(?:set|start|create|make) (?:a )?timers? (?:for\s+)?(?P<value>\d{1,3})\b", text, re.I)
    if bare_minutes:
        minutes = int(bare_minutes.group("value"))
        if minutes > 0:
            return f"{minutes} minutes", minutes * 60
    return None


def _timer_label(text: str, duration_text: str) -> str:
    named = re.search(r"\b(?:called|named)\s+(?P<label>.+)$", text, re.I)
    if named:
        return named.group("label").strip(" ,.:;")

    without_duration = text.replace(duration_text, " ", 1)
    without_duration = re.sub(r"^(?:set|start|create|make)\s+", "", without_duration, flags=re.I)
    before_timer = re.split(r"\btimers?\b", without_duration, maxsplit=1, flags=re.I)[0]
    before_timer = re.sub(r"\b(a|an|the|for|to|called|named)\b", " ", before_timer, flags=re.I)
    before_timer = re.sub(r"\s+", " ", before_timer).strip(" ,.:;")
    return before_timer


def _timer_number(raw: str) -> float | None:
    lowered = raw.lower()
    if lowered in NUMBER_WORDS:
        return NUMBER_WORDS[lowered]
    try:
        return float(lowered)
    except ValueError:
        return None


def _timer_unit_seconds(raw: str) -> int:
    unit = raw.lower()
    if unit.startswith("h"):
        return 60 * 60
    if unit.startswith("m"):
        return 60
    return 1
