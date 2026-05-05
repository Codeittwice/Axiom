"""
Google OAuth helper for AXIOM integrations.

Keeps Google API setup out of tools.py. Tokens live under secrets/ and are
never committed.
"""

from pathlib import Path
from typing import Iterable

import yaml


class GoogleAuthError(RuntimeError):
    """Raised when Google OAuth cannot be completed."""


_SERVICE_CACHE = {}


def _load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _google_config(config: dict | None = None) -> dict:
    cfg = config if config is not None else _load_config()
    return cfg.get("google", {}) or {}


def _scope_list(scopes: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(scope) for scope in scopes if scope))


def _token_path(config: dict | None = None) -> Path:
    google = _google_config(config)
    return Path(google.get("token_file") or "secrets/google_token.json")


def get_credentials(scopes: Iterable[str], config: dict | None = None):
    """
    Return valid Google credentials for the requested scopes.

    First use opens the browser for consent. Later calls refresh silently from
    the cached token file.
    """
    scope_values = _scope_list(scopes)
    google = _google_config(config)
    credentials_file = Path(
        google.get("oauth_credentials_file") or "secrets/google_oauth_client.json"
    )
    token_file = _token_path(config)

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise GoogleAuthError(
            "Google API packages are not installed. Run: pip install -r requirements.txt"
        ) from exc

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scope_values)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not credentials_file.exists():
            raise GoogleAuthError(
                f"Google OAuth credentials not found at {credentials_file}. "
                "Create a Google OAuth desktop client and save it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scope_values)
        creds = flow.run_local_server(port=0)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_service(api: str, version: str, scopes: Iterable[str], config: dict | None = None):
    """Build and cache a Google API service client."""
    scope_values = tuple(_scope_list(scopes))
    cache_key = (api, version, scope_values, str(_token_path(config)))
    if cache_key in _SERVICE_CACHE:
        return _SERVICE_CACHE[cache_key]

    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleAuthError(
            "google-api-python-client is not installed. Run: pip install -r requirements.txt"
        ) from exc

    service = build(api, version, credentials=get_credentials(scope_values, config))
    _SERVICE_CACHE[cache_key] = service
    return service


def revoke(config: dict | None = None) -> bool:
    """Remove the cached token. Returns true when a token was removed."""
    _SERVICE_CACHE.clear()
    token_file = _token_path(config)
    if token_file.exists():
        token_file.unlink()
        return True
    return False
