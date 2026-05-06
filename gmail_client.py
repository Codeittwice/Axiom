"""Read-only Gmail triage helpers for AXIOM."""

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import yaml

from google_auth import get_service, token_has_scopes


GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _cfg(config: dict | None = None) -> dict:
    return config if config is not None else _load_config()


def _gmail(config: dict | None = None) -> dict:
    return (_cfg(config).get("gmail", {}) or {})


def _max_results(default: int, config: dict | None = None) -> int:
    configured = int(_gmail(config).get("max_results", 20) or 20)
    return min(max(1, int(default or 1)), configured)


def _state_path(config: dict | None = None) -> Path:
    return Path(_gmail(config).get("state_file") or "secrets/last_email_check.json")


def _load_state(config: dict | None = None) -> dict:
    path = _state_path(config)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict, config: dict | None = None) -> None:
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cutoff_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def _service(config: dict | None = None):
    cfg = _gmail(config)
    if not cfg.get("enabled", False):
        raise RuntimeError("Gmail is disabled. Set gmail.enabled to true in config.yaml.")
    scopes = cfg.get("scopes") or GMAIL_SCOPES
    return get_service("gmail", "v1", scopes, _cfg(config))


def has_connection(config: dict | None = None) -> bool:
    cfg = _gmail(config)
    if not cfg.get("enabled", False):
        return False
    scopes = cfg.get("scopes") or GMAIL_SCOPES
    return token_has_scopes(scopes, _cfg(config))


def connect(config: dict | None = None) -> dict:
    service = _service(config)
    profile = service.users().getProfile(userId="me").execute()
    return {
        "email": profile.get("emailAddress", ""),
        "messages_total": int(profile.get("messagesTotal") or 0),
    }


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
        "internal_ts": int(msg.get("internalDate") or 0),
    }


def _messages(query: str = "", n: int = 5, config: dict | None = None) -> list[dict]:
    service = _service(config)
    params = {
        "userId": "me",
        "maxResults": _max_results(n, config),
    }
    if query:
        params["q"] = query
    data = service.users().messages().list(**params).execute()
    return [_format_message(service, item["id"]) for item in data.get("messages", [])]


def unread_count(config: dict | None = None) -> int:
    service = _service(config)
    data = service.users().messages().list(
        userId="me",
        labelIds=["UNREAD"],
        maxResults=1,
    ).execute()
    return int(data.get("resultSizeEstimate") or 0)


def last_emails(n: int = 5, config: dict | None = None) -> list[dict]:
    return _messages(n=n, config=config)


def unread_since_last_check(config: dict | None = None) -> dict:
    state = _load_state(config)
    last_check = state.get("last_check")
    cutoff = _cutoff_ms(last_check)
    query = "is:unread"
    if cutoff:
        dt = datetime.fromtimestamp(cutoff / 1000, tz=timezone.utc)
        query = f"{query} after:{dt.strftime('%Y/%m/%d')}"

    items = _messages(query=query, n=_gmail(config).get("max_results", 20), config=config)
    if cutoff:
        items = [item for item in items if int(item.get("internal_ts") or 0) > cutoff]

    new_state = mark_check_now(config)
    return {
        "count": len(items),
        "items": items,
        "last_check": new_state["last_check"],
        "previous_check": last_check,
    }


def mark_check_now(config: dict | None = None) -> dict:
    state = {"last_check": _now_iso()}
    _save_state(state, config)
    return state


def summarize_inbox(config: dict | None = None) -> dict:
    return {
        "unread_count": unread_count(config),
        "recent": last_emails(3, config),
    }
