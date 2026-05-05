"""
Google Calendar integration for AXIOM.

Public functions return dictionaries/lists suitable for REST responses. Voice
wrappers in tools.py turn those into short speakable summaries.
"""

from datetime import datetime, timedelta
from typing import Any

import yaml

from google_auth import get_service


CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _cfg(config: dict | None = None) -> dict:
    return config if config is not None else _load_config()


def _google(config: dict | None = None) -> dict:
    return (_cfg(config).get("google", {}) or {})


def _ensure_enabled(config: dict | None = None) -> None:
    if not _google(config).get("enable_calendar", False):
        raise RuntimeError("Google Calendar is disabled. Set google.enable_calendar to true.")


def _calendar_id(config: dict | None = None) -> str:
    return _google(config).get("calendar_id") or "primary"


def _timezone(config: dict | None = None) -> str:
    return _google(config).get("timezone") or "UTC"


def _service(config: dict | None = None):
    _ensure_enabled(config)
    return get_service("calendar", "v3", CALENDAR_SCOPES, _cfg(config))


def _parse_datetime(value: str | datetime, config: dict | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        parsed = None
        try:
            import dateparser

            settings = {
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": _timezone(config),
                "TO_TIMEZONE": _timezone(config),
            }
            parsed = dateparser.parse(text, settings=settings)
        except ImportError:
            parsed = None

        if parsed is None:
            raw = text.replace("Z", "+00:00")
            if len(raw) == 10:
                raw = f"{raw}T00:00:00"
            parsed = datetime.fromisoformat(raw)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _format_event(event: dict[str, Any]) -> dict[str, str]:
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id", ""),
        "title": event.get("summary", "Untitled event"),
        "start": start.get("dateTime") or start.get("date", ""),
        "end": end.get("dateTime") or end.get("date", ""),
        "location": event.get("location", ""),
        "link": event.get("htmlLink", ""),
    }


def _is_http_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "HttpError"


def list_events(
    start_iso: str | datetime,
    end_iso: str | datetime,
    config: dict | None = None,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """List events between two datetimes."""
    service = _service(config)
    start = _parse_datetime(start_iso, config).isoformat()
    end = _parse_datetime(end_iso, config).isoformat()
    try:
        data = service.events().list(
            calendarId=_calendar_id(config),
            timeMin=start,
            timeMax=end,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return [_format_event(item) for item in data.get("items", [])]
    except Exception as exc:
        if _is_http_error(exc):
            return []
        raise


def today_events(config: dict | None = None) -> list[dict[str, str]]:
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return list_events(start, end, config=config, max_results=20)


def upcoming_events(
    days: int = 7,
    config: dict | None = None,
    max_results: int = 10,
) -> list[dict[str, str]]:
    now = datetime.now().astimezone()
    end = now + timedelta(days=max(1, days))
    return list_events(now, end, config=config, max_results=max_results)


def next_event(config: dict | None = None) -> dict[str, str]:
    events = upcoming_events(days=14, config=config, max_results=1)
    return events[0] if events else {}


def create_event(
    title: str,
    when: str,
    duration_min: int = 60,
    config: dict | None = None,
) -> dict[str, str]:
    service = _service(config)
    start = _parse_datetime(when, config)
    end = start + timedelta(minutes=max(1, int(duration_min or 60)))
    body = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": _timezone(config)},
        "end": {"dateTime": end.isoformat(), "timeZone": _timezone(config)},
    }
    try:
        event = service.events().insert(
            calendarId=_calendar_id(config),
            body=body,
        ).execute()
        return _format_event(event)
    except Exception as exc:
        if _is_http_error(exc):
            return {}
        raise
