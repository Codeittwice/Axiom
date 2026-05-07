"""
Session logger — writes one JSONL entry per voice interaction to data/session_logs/.
Never raises; log failure must not crash the assistant.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

_SESSION_LOGS_DIR = Path("data/session_logs")


def _time_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _read_session_count() -> int:
    model_path = Path("data/user_model.json")
    if model_path.exists():
        try:
            with open(model_path, encoding="utf-8") as f:
                return int(json.load(f).get("session_count", 0))
        except Exception:
            pass
    return 0


def log_session(
    user_utterance: str,
    axiom_response: str,
    tools_called: list[str],
    duration_seconds: float,
) -> str:
    """Write one JSONL entry. Returns session_id. Never raises."""
    try:
        _SESSION_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        session_id = str(uuid.uuid4())
        entry = {
            "session_id": session_id,
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "user_utterance": user_utterance,
            "axiom_response": axiom_response,
            "tools_called": tools_called,
            "duration_seconds": duration_seconds,
            "time_of_day": _time_of_day(now.hour),
            "day_of_week": now.strftime("%A"),
            "session_number": _read_session_count() + 1,
        }
        log_file = _SESSION_LOGS_DIR / now.strftime("%Y-%m-%d.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return session_id
    except Exception as e:
        print(f"[AXIOM] Session log error: {e}")
        return ""


def get_recent_logs(days: int = 7) -> list[dict]:
    """Read and merge JSONL files for the last N days. Returns list sorted by timestamp."""
    try:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        entries: list[dict] = []
        if not _SESSION_LOGS_DIR.exists():
            return entries
        for log_file in sorted(_SESSION_LOGS_DIR.glob("*.jsonl")):
            try:
                file_date = datetime.strptime(log_file.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if file_date < cutoff - timedelta(days=1):
                    continue
            except ValueError:
                continue
            with open(log_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        return sorted(entries, key=lambda e: e.get("timestamp", ""))
    except Exception as e:
        print(f"[AXIOM] Session log read error: {e}")
        return []


def get_session_count() -> int:
    """Count total sessions logged across all JSONL files."""
    try:
        if not _SESSION_LOGS_DIR.exists():
            return 0
        count = 0
        for log_file in _SESSION_LOGS_DIR.glob("*.jsonl"):
            with open(log_file, encoding="utf-8") as f:
                count += sum(1 for line in f if line.strip())
        return count
    except Exception as e:
        print(f"[AXIOM] Session count error: {e}")
        return 0
