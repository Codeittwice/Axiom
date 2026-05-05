"""Read-only Gmail triage helpers for AXIOM."""

from email.utils import parsedate_to_datetime

import yaml

from google_auth import get_service


GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _cfg(config: dict | None = None) -> dict:
    return config if config is not None else _load_config()


def _gmail(config: dict | None = None) -> dict:
    return (_cfg(config).get("gmail", {}) or {})


def _service(config: dict | None = None):
    cfg = _gmail(config)
    if not cfg.get("enabled", False):
        raise RuntimeError("Gmail is disabled. Set gmail.enabled to true in config.yaml.")
    scopes = cfg.get("scopes") or GMAIL_SCOPES
    return get_service("gmail", "v1", scopes, _cfg(config))


def _header(payload: dict, name: str) -> str:
    for header in payload.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _format_message(service, msg_id: str) -> dict:
    msg = service.users().messages().get(
        userId="me",
        id=msg_id,
        format="metadata",
        metadataHeaders=["From", "Subject", "Date"],
    ).execute()
    payload = msg.get("payload", {})
    date_value = _header(payload, "Date")
    try:
        ts = parsedate_to_datetime(date_value).isoformat() if date_value else ""
    except Exception:
        ts = date_value
    return {
        "id": msg.get("id", ""),
        "sender": _header(payload, "From"),
        "subject": _header(payload, "Subject") or "(no subject)",
        "snippet": (msg.get("snippet", "") or "")[:80],
        "ts": ts,
    }


def unread_count(config: dict | None = None) -> int:
    service = _service(config)
    data = service.users().messages().list(
        userId="me",
        labelIds=["UNREAD"],
        maxResults=1,
    ).execute()
    return int(data.get("resultSizeEstimate") or 0)


def last_emails(n: int = 5, config: dict | None = None) -> list[dict]:
    service = _service(config)
    max_results = min(max(1, int(n or 5)), int(_gmail(config).get("max_results", 20)))
    data = service.users().messages().list(
        userId="me",
        maxResults=max_results,
    ).execute()
    return [_format_message(service, item["id"]) for item in data.get("messages", [])]


def summarize_inbox(config: dict | None = None) -> dict:
    return {
        "unread_count": unread_count(config),
        "recent": last_emails(3, config),
    }
