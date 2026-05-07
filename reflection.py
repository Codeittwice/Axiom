"""
Reflection engine — reads session logs + user model, calls Gemini,
writes suggestions and updates the user model.
All public functions swallow exceptions and return safe fallbacks.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

_USER_MODEL_PATH = Path("data/user_model.json")
_SUGGESTIONS_PATH = Path("data/suggestions.json")

_USER_MODEL_SKELETON: dict = {
    "session_count": 0,
    "communication_style": {
        "preferred_response_length": "unknown",
        "technical_level": "unknown",
        "tone_observations": [],
    },
    "working_hours": {},
    "frequent_domains": {},
    "delegation_threshold": "low",
    "interaction_patterns": [],
    "rejected_suggestions": [],
    "approved_suggestions": [],
    "last_updated": None,
}

_REFLECTION_PROMPT_TEMPLATE = """\
You are AXIOM's self-reflection engine. Analyse the data below and suggest improvements.

## Current user model
{user_model_json}

## Skill registry (tools + scenarios available)
{skill_registry_json}

## Session logs (last {days} days, {session_count} sessions)
{sessions_summary}

## Rejected suggestion titles (never re-propose these)
{rejected_titles}

## Task
Identify 1-5 specific, actionable improvements. Focus on:
- Recurring user requests that have no dedicated tool (friction pattern)
- Sequences of actions always done together (chain candidate)
- Tools never used (potential deprecation or user education)
- Inferred user preferences (tone, timing, topics)

Respond ONLY with a JSON array. No prose before or after. Schema for each item:
{{"type": "new_skill | refine_skill | deprecate | chain | preference | scenario",
  "title": "Short human-readable title (max 60 chars)",
  "reasoning": "Why this would help, referencing specific patterns observed",
  "evidence": ["Direct quote or session description that triggered this"],
  "proposal": {{
    "description": "Concrete description of what would be built or changed",
    "estimated_complexity": "trivial | low | medium | high",
    "files_to_modify": ["tools.py"]
  }}
}}\
"""


# ─── Public API ───────────────────────────────────────────────────────────────

def run_reflection(cfg: dict) -> list[dict]:
    """
    Main entry. Reads logs, calls Gemini, updates user_model.json and
    suggestions.json. Returns only newly created suggestions.
    Never raises — returns [] on any failure.
    """
    try:
        from session_logger import get_recent_logs
        import google.generativeai as genai

        learning = cfg.get("learning", {}) or {}
        days = int(learning.get("reflection_window_days", 7))
        logs = get_recent_logs(days=days)
        if not logs:
            print("[AXIOM] Reflection skipped — no session logs yet.")
            return []

        user_model = _load_user_model()
        registry = build_skill_registry(cfg)

        rejected_titles = _rejected_titles_from_suggestions()
        sessions_summary = _summarize_sessions_for_prompt(logs)

        prompt = _REFLECTION_PROMPT_TEMPLATE.format(
            user_model_json=json.dumps(user_model, indent=2),
            skill_registry_json=json.dumps(registry, indent=2),
            sessions_summary=sessions_summary,
            days=days,
            session_count=len(logs),
            rejected_titles=json.dumps(rejected_titles),
        )

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("[AXIOM] Reflection skipped — GEMINI_API_KEY not set.")
            return []

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=cfg["gemini"]["model"],
            generation_config={"response_mime_type": "application/json"},
        )
        response = model.generate_content(prompt)
        raw = response.text.strip()

        candidates = json.loads(raw)
        if not isinstance(candidates, list):
            candidates = [candidates]

        existing = _load_suggestions()
        existing_titles = {s["title"].lower() for s in existing}
        rejected_lower = {t.lower() for t in rejected_titles}

        now = datetime.now(timezone.utc).isoformat()
        new_suggestions: list[dict] = []
        for c in candidates:
            title = c.get("title", "").strip()
            if not title:
                continue
            title_lower = title.lower()
            if title_lower in existing_titles or title_lower in rejected_lower:
                continue
            suggestion = {
                "id": str(uuid.uuid4()),
                "created_at": now,
                "type": c.get("type", "new_skill"),
                "title": title,
                "reasoning": c.get("reasoning", ""),
                "evidence": c.get("evidence", []),
                "proposal": c.get("proposal", {}),
                "status": "pending",
                "user_notes": "",
            }
            new_suggestions.append(suggestion)
            existing_titles.add(title_lower)

        if new_suggestions:
            _save_suggestions(existing + new_suggestions)

        _update_user_model_from_logs(user_model, logs)
        _save_user_model(user_model)

        print(f"[AXIOM] Reflection complete: {len(new_suggestions)} new suggestion(s).")
        return new_suggestions

    except Exception as e:
        print(f"[AXIOM] Reflection failed: {e}")
        return []


def build_skill_registry(cfg: dict) -> dict:
    """
    Compute a live snapshot of AXIOM's current capabilities.
    Reads GEMINI_TOOLS from tools.py + scenarios from config + usage from session logs.
    """
    try:
        from tools import GEMINI_TOOLS
        from session_logger import get_recent_logs

        usage: dict[str, int] = {}
        for entry in get_recent_logs(days=365):
            for t in entry.get("tools_called", []):
                usage[t] = usage.get(t, 0) + 1

        tools_list = []
        try:
            declarations = GEMINI_TOOLS[0]["function_declarations"]
        except (IndexError, KeyError, TypeError):
            declarations = []

        for decl in declarations:
            name = decl.get("name", "")
            if not name:
                continue
            tools_list.append({
                "name": name,
                "description": decl.get("description", ""),
                "usage_count": usage.get(name, 0),
                "type": "tool",
            })

        scenarios_list = []
        for key, sc in (cfg.get("scenarios", {}) or {}).items():
            scenarios_list.append({
                "name": key,
                "description": (sc or {}).get("description", ""),
                "usage_count": usage.get(f"run_scenario:{key}", 0),
                "type": "scenario",
            })

        return {
            "tools": tools_list,
            "scenarios": scenarios_list,
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"[AXIOM] build_skill_registry failed: {e}")
        return {"tools": [], "scenarios": [], "generated_at": datetime.now().isoformat()}


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _load_user_model() -> dict:
    if _USER_MODEL_PATH.exists():
        try:
            with open(_USER_MODEL_PATH, encoding="utf-8") as f:
                data = json.load(f)
            # Merge with skeleton so new keys are always present
            merged = dict(_USER_MODEL_SKELETON)
            merged.update(data)
            return merged
        except Exception:
            pass
    import copy
    return copy.deepcopy(_USER_MODEL_SKELETON)


def _save_user_model(model: dict) -> None:
    _USER_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_USER_MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, ensure_ascii=False)


def _load_suggestions() -> list[dict]:
    if _SUGGESTIONS_PATH.exists():
        try:
            with open(_SUGGESTIONS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else data.get("items", [])
        except Exception:
            pass
    return []


def _save_suggestions(items: list[dict]) -> None:
    _SUGGESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_SUGGESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def _rejected_titles_from_suggestions() -> list[str]:
    return [
        s["title"] for s in _load_suggestions()
        if s.get("status") == "rejected"
    ]


def _summarize_sessions_for_prompt(logs: list[dict]) -> str:
    """
    Compact text representation of session logs for the Gemini prompt.
    Target: under 2000 tokens regardless of log volume.
    """
    tool_counts: dict[str, int] = {}
    utterances: list[str] = []

    for entry in logs:
        for t in entry.get("tools_called", []):
            tool_counts[t] = tool_counts.get(t, 0) + 1
        utt = entry.get("user_utterance", "").strip()
        if utt:
            tod = entry.get("time_of_day", "?")
            utterances.append(f"[{tod}] {utt[:120]}")

    lines = ["=== Tool usage frequency ==="]
    for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1])[:20]:
        lines.append(f"  {tool}: {count}x")

    lines.append("\n=== Recent user utterances (sample, deduplicated) ===")
    seen: set[str] = set()
    shown = 0
    for u in reversed(utterances):
        key = u.lower()[:60]
        if key not in seen:
            seen.add(key)
            lines.append(f"  - {u}")
            shown += 1
        if shown >= 30:
            break

    return "\n".join(lines)


def _update_user_model_from_logs(model: dict, logs: list[dict]) -> None:
    """Update working_hours histogram and frequent_domains tally in-place."""
    for entry in logs:
        ts = entry.get("timestamp", "")
        if ts:
            try:
                hour = str(datetime.fromisoformat(ts.replace("Z", "+00:00")).hour)
                wh = model.setdefault("working_hours", {})
                wh[hour] = wh.get(hour, 0) + 1
            except Exception:
                pass
        for t in entry.get("tools_called", []):
            fd = model.setdefault("frequent_domains", {})
            fd[t] = fd.get(t, 0) + 1

    model["session_count"] = model.get("session_count", 0) + len(logs)
    model["last_updated"] = datetime.now(timezone.utc).isoformat()
