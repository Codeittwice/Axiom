"""
Reflection engine — reads session logs + user model, calls Gemini,
writes suggestions and updates the user model.
All public functions swallow exceptions and return safe fallbacks.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
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
    "seen_suggestion_fingerprints": [],
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

## Already-seen suggestion titles (never re-propose these)
{blocked_titles}

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

        user_model = _load_user_model()
        last_cursor = user_model.get("last_reflected_until")

        logs = get_recent_logs(days=days, since=last_cursor)
        if not logs:
            print("[AXIOM] Reflection skipped — no new sessions since last run.")
            return []
        registry = build_skill_registry(cfg)

        existing = _load_suggestions()
        blocked_titles = _blocked_suggestion_titles(user_model, existing)
        sessions_summary = _summarize_sessions_for_prompt(logs)

        prompt = _REFLECTION_PROMPT_TEMPLATE.format(
            user_model_json=json.dumps(user_model, indent=2),
            skill_registry_json=json.dumps(registry, indent=2),
            sessions_summary=sessions_summary,
            days=days,
            session_count=len(logs),
            blocked_titles=json.dumps(blocked_titles),
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

        existing_fingerprints = _suggestion_fingerprints(existing, user_model)

        now = datetime.now(timezone.utc).isoformat()
        new_suggestions: list[dict] = []
        for c in candidates:
            title = c.get("title", "").strip()
            if not title:
                continue
            fingerprint = _suggestion_fingerprint(c)
            if _is_duplicate_suggestion(c, existing_fingerprints):
                continue
            suggestion = {
                "id": str(uuid.uuid4()),
                "created_at": now,
                "type": c.get("type", "new_skill"),
                "title": title,
                "fingerprint": fingerprint,
                "reasoning": c.get("reasoning", ""),
                "evidence": c.get("evidence", []),
                "proposal": c.get("proposal", {}),
                "status": "pending",
                "user_notes": "",
            }
            new_suggestions.append(suggestion)
            existing_fingerprints.append(fingerprint)

        if new_suggestions:
            _save_suggestions(existing + new_suggestions)

        _update_user_model_from_logs(user_model, logs)
        _remember_seen_suggestions(user_model, existing + new_suggestions)
        new_cursor = max(e["timestamp"] for e in logs)
        user_model["last_reflected_until"] = new_cursor
        _save_user_model(user_model)

        try:
            _write_reflection_to_brain(user_model, logs, new_suggestions, cfg)
        except Exception as _brain_err:
            print(f"[AXIOM] Brain reflection write skipped: {_brain_err}")

        print(f"[AXIOM] Reflection complete: {len(new_suggestions)} new suggestion(s).")
        return new_suggestions

    except Exception as e:
        import traceback
        print(f"[AXIOM] Reflection failed: {e}\n{traceback.format_exc()}")
        raise


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


def _blocked_suggestion_titles(user_model: dict, suggestions: list[dict]) -> list[str]:
    titles = []
    for suggestion in suggestions:
        title = str(suggestion.get("title") or "").strip()
        if title:
            titles.append(title)
    for item in user_model.get("seen_suggestion_fingerprints", []) or []:
        if isinstance(item, dict) and item.get("title"):
            titles.append(str(item["title"]))
    return sorted(set(titles), key=str.lower)


def _normalize_suggestion_text(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [
        word
        for word in text.split()
        if word not in {"a", "an", "the", "to", "for", "and", "or", "of", "in", "with"}
    ]
    return " ".join(words)


def _suggestion_fingerprint(suggestion: dict) -> str:
    title = _normalize_suggestion_text(suggestion.get("title", ""))
    proposal = suggestion.get("proposal", {}) or {}
    description = _normalize_suggestion_text(proposal.get("description", ""))
    kind = _normalize_suggestion_text(suggestion.get("type", ""))
    return " | ".join(part for part in [kind, title, description[:160]] if part)


def _suggestion_fingerprints(suggestions: list[dict], user_model: dict) -> list[str]:
    fingerprints = []
    for suggestion in suggestions:
        fingerprint = suggestion.get("fingerprint") or _suggestion_fingerprint(suggestion)
        if fingerprint:
            fingerprints.append(fingerprint)
    for item in user_model.get("seen_suggestion_fingerprints", []) or []:
        if isinstance(item, dict) and item.get("fingerprint"):
            fingerprints.append(str(item["fingerprint"]))
        elif isinstance(item, str):
            fingerprints.append(item)
    return list(dict.fromkeys(fingerprints))


def _is_duplicate_suggestion(candidate: dict, existing_fingerprints: list[str]) -> bool:
    fingerprint = _suggestion_fingerprint(candidate)
    if not fingerprint:
        return True
    for existing in existing_fingerprints:
        if fingerprint == existing:
            return True
        if SequenceMatcher(None, fingerprint, existing).ratio() >= 0.86:
            return True
    return False


def _remember_seen_suggestions(user_model: dict, suggestions: list[dict]) -> None:
    existing = user_model.setdefault("seen_suggestion_fingerprints", [])
    by_fingerprint: dict[str, dict] = {}
    for item in existing:
        if isinstance(item, dict) and item.get("fingerprint"):
            by_fingerprint[str(item["fingerprint"])] = item
        elif isinstance(item, str):
            by_fingerprint[item] = {"fingerprint": item, "title": "", "status": "seen"}

    now = datetime.now(timezone.utc).isoformat()
    for suggestion in suggestions:
        fingerprint = suggestion.get("fingerprint") or _suggestion_fingerprint(suggestion)
        if not fingerprint:
            continue
        by_fingerprint[fingerprint] = {
            "fingerprint": fingerprint,
            "title": suggestion.get("title", ""),
            "status": suggestion.get("status", "pending"),
            "last_seen": now,
        }

    user_model["seen_suggestion_fingerprints"] = list(by_fingerprint.values())[-200:]


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


def _write_reflection_to_brain(
    user_model: dict,
    logs: list[dict],
    new_suggestions: list[dict],
    cfg: dict,
) -> None:
    """Write reflection findings as Obsidian notes in the AXIOM Brain."""
    from brain import update_profile, grow_log, _brain_root  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    root = _brain_root(cfg)
    if root is None or not root.exists():
        return

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    today = now.strftime("%Y-%m-%d")

    # 1. Working patterns — top tools used
    freq = user_model.get("frequent_domains", {})
    if freq:
        top_tools = sorted(freq.items(), key=lambda x: -x[1])[:5]
        tools_str = ", ".join(f"{t}({c})" for t, c in top_tools)
        update_profile("Working Patterns", f"Top tools this period: {tools_str}", cfg)

    # 2. Working hours peak
    wh = user_model.get("working_hours", {})
    if wh:
        peak_hour = max(wh, key=lambda h: wh[h])
        update_profile("Working Patterns", f"Peak active hour: {peak_hour}:00", cfg)

    # 3. Daily summary note
    summary_path = root / "Memory" / "Daily Summaries" / f"{today}.md"
    if not summary_path.exists():
        utterances = list(dict.fromkeys(
            e.get("user_utterance", "").strip()
            for e in logs
            if e.get("user_utterance", "").strip()
        ))[:10]
        utterance_lines = "\n".join(f"- {u}" for u in utterances)
        summary_path.write_text(
            f"""---
type: daily_summary
date: {today}
---

# Daily Summary — {today}

## Interactions ({len(logs)} total)

{utterance_lines}

## Reflection timestamp
Generated at {now_str}.
""",
            encoding="utf-8",
        )

    # 4. Pending improvements — add new suggestion titles
    pending_path = root / "Self" / "Pending Improvements.md"
    if new_suggestions and pending_path.exists():
        existing = pending_path.read_text(encoding="utf-8")
        lines = [f"- {now_str}: [[{s['title']}]] (complexity: {s.get('complexity', '?')})"
                 for s in new_suggestions]
        pending_path.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")

    # 5. Growth log entry
    grow_log(
        f"Reflection ran over {len(logs)} sessions; {len(new_suggestions)} new suggestion(s).",
        cfg,
    )

    # 6. Mark episode notes as processed
    _mark_episodes_reflected(root, logs)


def _mark_episodes_reflected(root: "Path", logs: list[dict]) -> None:
    """
    For each episode note whose `date` frontmatter falls within the dates
    covered by `logs`, add `reflection_processed: true` and `reflected_at`.
    Idempotent — skips notes that already have the flag.
    """
    covered_dates = {e["timestamp"][:10] for e in logs if e.get("timestamp")}
    if not covered_dates:
        return

    episodes_dir = root / "Memory" / "Episodes"
    if not episodes_dir.exists():
        return

    today_iso = datetime.now().strftime("%Y-%m-%d")

    for note_path in episodes_dir.glob("*.md"):
        try:
            text = note_path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            if "reflection_processed: true" in text:
                continue
            end = text.find("\n---", 3)
            if end == -1:
                continue
            frontmatter = text[3:end]
            date_match = re.search(r"^date:\s*(\S+)", frontmatter, re.MULTILINE)
            if not date_match:
                continue
            note_date = date_match.group(1).strip("'\"")
            if note_date not in covered_dates:
                continue
            new_text = (
                text[:end]
                + f"\nreflection_processed: true\nreflected_at: {today_iso}"
                + text[end:]
            )
            note_path.write_text(new_text, encoding="utf-8")
        except Exception as _e:
            print(f"[AXIOM] Episode flag error ({note_path.name}): {_e}")
