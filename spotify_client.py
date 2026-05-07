"""Spotify Web API helpers for AXIOM."""

import os
from pathlib import Path

import yaml


SPOTIFY_SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)


def _load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _cfg(config: dict | None = None) -> dict:
    return config if config is not None else _load_config()


def _spotify(config: dict | None = None) -> dict:
    return (_cfg(config).get("spotify", {}) or {})


def _settings(config: dict | None = None) -> dict:
    cfg = _spotify(config)
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "client_id": cfg.get("client_id") or os.getenv("SPOTIPY_CLIENT_ID", ""),
        "client_secret": cfg.get("client_secret") or os.getenv("SPOTIPY_CLIENT_SECRET", ""),
        "redirect_uri": cfg.get("redirect_uri") or os.getenv("SPOTIPY_REDIRECT_URI", ""),
        "cache_path": cfg.get("cache_path") or "secrets/spotify_token.json",
    }


def status(config: dict | None = None) -> dict:
    settings = _settings(config)
    token = Path(settings["cache_path"])
    return {
        "enabled": settings["enabled"],
        "has_client_id": bool(settings["client_id"]),
        "has_client_secret": bool(settings["client_secret"]),
        "redirect_uri": settings["redirect_uri"],
        "token_file": str(token),
        "connected": token.exists(),
    }


def _client(config: dict | None = None):
    settings = _settings(config)
    if not settings["enabled"]:
        raise RuntimeError("Spotify is disabled. Set spotify.enabled to true in config.yaml.")

    client_id = settings["client_id"]
    client_secret = settings["client_secret"]
    redirect_uri = settings["redirect_uri"]
    cache_path = settings["cache_path"]

    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError(
            "Spotify is not configured. Add SPOTIPY_CLIENT_SECRET to .env, "
            "and make sure spotify.client_id and redirect_uri are set."
        )

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError as exc:
        raise RuntimeError("spotipy is not installed. Run: pip install -r requirements.txt") from exc

    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SPOTIFY_SCOPES,
        cache_path=cache_path,
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth)


def connect(config: dict | None = None) -> dict:
    sp = _client(config)
    token = sp.auth_manager.get_access_token(as_dict=False)
    if not token:
        raise RuntimeError("Spotify OAuth did not return an access token.")
    return status(config) | {"connected": True}


def _track_summary(track: dict) -> str:
    artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
    return f"{track.get('name', 'Unknown track')} by {artists or 'unknown artist'}"


def play(query: str, config: dict | None = None) -> str:
    sp = _client(config)
    results = sp.search(q=query, type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    if not items:
        return f"No Spotify track found for '{query}'."
    track = items[0]
    sp.start_playback(uris=[track["uri"]])
    return f"Playing {_track_summary(track)}."


def control(action: str, config: dict | None = None) -> str:
    sp = _client(config)
    action_key = action.lower().strip().replace(" ", "_")
    if action_key in {"play", "resume"}:
        sp.start_playback()
        return "Spotify playback resumed."
    if action_key in {"pause", "stop"}:
        sp.pause_playback()
        return "Spotify paused."
    if action_key in {"next", "skip"}:
        sp.next_track()
        return "Skipped to the next Spotify track."
    if action_key in {"previous", "back"}:
        sp.previous_track()
        return "Went back to the previous Spotify track."
    if action_key in {"volume_up", "up"}:
        current = sp.current_playback() or {}
        volume = int((current.get("device") or {}).get("volume_percent") or 50)
        sp.volume(min(100, volume + 10))
        return "Spotify volume up."
    if action_key in {"volume_down", "down"}:
        current = sp.current_playback() or {}
        volume = int((current.get("device") or {}).get("volume_percent") or 50)
        sp.volume(max(0, volume - 10))
        return "Spotify volume down."
    return "Unknown Spotify action. Use play, pause, next, previous, volume_up, or volume_down."


def now_playing(config: dict | None = None) -> str:
    sp = _client(config)
    current = sp.current_playback()
    if not current or not current.get("item"):
        return "Spotify is not currently playing anything."
    state = "playing" if current.get("is_playing") else "paused"
    return f"Spotify is {state}: {_track_summary(current['item'])}."
