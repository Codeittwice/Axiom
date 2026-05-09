"""
AXIOM User Profile — read/write module for user-profile.md.

Maintains a single structured markdown file that serves as the living
user model. Separate from brain.py's Profile/*.md files (raw observations);
this file holds clean, parsed facts that are injected into the system prompt.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── Template ────────────────────────────────────────────────────────────────

PROFILE_TEMPLATE = """\
# AXIOM — User Profile
> Last updated: {date}

## Identity
- Name:
- Age range:
- Location:
- Languages:
- Pronouns:

## Work & Career
- Job / field:
- Industry:
- Work style:
- Current goal:

## Daily Life
- Morning or night person:
- Schedule structure:
- Peak energy time:
- Main uses for Axiom:

## Interests & Hobbies
- Hobbies:
- Favourite topics:
- Media habits:
- How they learn:

## Personality & Mindset
- Decision style:
- Social energy:
- Stress triggers:
- Motivators:

## Axiom Preferences
- Preferred tone:
- Answer detail level:
- Should Axiom challenge them:

## Inferred Traits
<!-- Gemini fills this in over time — do not manually edit -->

## Open Questions
<!-- Questions Axiom still wants to ask -->
"""

_PLACEHOLDERS = {"", "(to be learned)", "unknown", "n/a", "none", "tbd", "—", "-"}

_STRUCTURED_SECTIONS = {
    "Identity", "Work & Career", "Daily Life",
    "Interests & Hobbies", "Personality & Mindset", "Axiom Preferences",
}

# ─── Path helpers ─────────────────────────────────────────────────────────────

def _profile_path(cfg: dict) -> Optional[Path]:
    obsidian_cfg = cfg.get("obsidian", {}) or {}
    vault = obsidian_cfg.get("vault_path", "")
    if not vault:
        return None
    brain_cfg = cfg.get("brain", {}) or {}
    subfolder = brain_cfg.get("vault_subfolder", "AXIOM Brain")
    return Path(vault) / subfolder / "user-profile.md"


def _read_raw(cfg: dict) -> str:
    path = _profile_path(cfg)
    if path is None or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _write_raw(content: str, cfg: dict) -> None:
    path = _profile_path(cfg)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"[AXIOM] user_profile write error: {e}")


def _touch_last_updated(content: str) -> str:
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    return re.sub(r"> Last updated:.*", f"> Last updated: {date_str}", content)


# ─── Key setter (used internally) ────────────────────────────────────────────

def _set_key(content: str, category: str, key: str, value: str) -> str:
    """Set a key's value within a ## Category section. Returns unchanged content on no match."""
    pattern = rf"(## {re.escape(category)}.*?)(-[ \t]*{re.escape(key)}[ \t]*:)[^\n\r]*"
    return re.sub(pattern, rf"\1\2 {value}", content, flags=re.DOTALL)


# ─── Public API ───────────────────────────────────────────────────────────────

def init_profile(cfg: dict) -> None:
    """
    Create user-profile.md if it doesn't exist.
    Migrates known facts from the existing Profile/*.md brain files.
    Never raises.
    """
    try:
        path = _profile_path(cfg)
        if path is None or path.exists():
            return

        content = PROFILE_TEMPLATE.format(date=datetime.now().strftime("%Y-%m-%d %H:%M"))

        # Migrate from existing brain Profile/*.md files
        obsidian_cfg = cfg.get("obsidian", {}) or {}
        vault = obsidian_cfg.get("vault_path", "")
        brain_cfg = cfg.get("brain", {}) or {}
        subfolder = brain_cfg.get("vault_subfolder", "AXIOM Brain")
        profile_dir = Path(vault) / subfolder / "Profile"

        if profile_dir.exists():
            identity_file = profile_dir / "User Identity.md"
            if identity_file.exists():
                id_text = identity_file.read_text(encoding="utf-8")
                loc = re.search(r"\*\*Location:\*\*\s*([^\n(]+)", id_text)
                if loc and loc.group(1).strip().lower() not in _PLACEHOLDERS:
                    content = _set_key(content, "Identity", "Location", loc.group(1).strip())

            comm_file = profile_dir / "Communication Style.md"
            if comm_file.exists():
                comm_text = comm_file.read_text(encoding="utf-8")
                hobbies = []
                if "guitar" in comm_text.lower():
                    hobbies.append("guitar")
                if "bass" in comm_text.lower():
                    hobbies.append("bass")
                if "music" in comm_text.lower():
                    hobbies.append("music production")
                if hobbies:
                    content = _set_key(content, "Interests & Hobbies", "Hobbies", ", ".join(hobbies))
                if "the river" in comm_text.lower() or ("spotify" in comm_text.lower() and "song" in comm_text.lower()):
                    trait = 'Has a song on Spotify called "The River" (in Bulgarian)'
                    content = content.replace(
                        "## Inferred Traits\n<!-- Gemini fills this in over time — do not manually edit -->",
                        f"## Inferred Traits\n<!-- Gemini fills this in over time — do not manually edit -->\n- {trait}",
                    )

        _write_raw(content, cfg)
        print("[AXIOM] Created user-profile.md with migrated data")
    except Exception as e:
        print(f"[AXIOM] init_profile error: {e}")


def read_profile(cfg: dict) -> str:
    """
    Return the profile as a clean string trimmed to ~600 words.
    Returns "" if the file doesn't exist or has no filled fields.
    """
    raw = _read_raw(cfg)
    if not raw:
        return ""
    text = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    text = re.sub(r"> Last updated:.*\n?", "", text)
    words = text.split()
    if len(words) > 600:
        text = " ".join(words[:600]) + "…"
    if re.search(r"-\s+\w[\w &]+\s*:\s+\S", text):
        return text.strip()
    return ""


def update_profile(category: str, key: str, value: str, cfg: dict) -> None:
    """
    Write a key's value into the ## Category section of user-profile.md.
    Updates the last-updated timestamp. Never raises.
    """
    try:
        if not value or value.strip().lower() in _PLACEHOLDERS:
            return
        content = _read_raw(cfg)
        if not content:
            init_profile(cfg)
            content = _read_raw(cfg)
        content = _set_key(content, category, key, value.strip())
        content = _touch_last_updated(content)
        _write_raw(content, cfg)
    except Exception as e:
        print(f"[AXIOM] update_profile error: {e}")


def has_info(key: str, cfg: dict) -> bool:
    """
    Return True if `key` already has a non-empty, non-placeholder value.
    Uses [ \\t]* (not \\s*) so the match never crosses line boundaries.
    """
    try:
        content = _read_raw(cfg)
        match = re.search(rf"-[ \t]*{re.escape(key)}[ \t]*:[ \t]*([^\n\r]*)", content, re.I)
        if not match:
            return False
        val = match.group(1).strip().lower()
        return bool(val) and val not in _PLACEHOLDERS
    except Exception:
        return False


def get_missing_topics(cfg: dict) -> list[str]:
    """
    Return a list of "Category / Key" strings for all unfilled structured fields.
    """
    try:
        content = _read_raw(cfg)
        if not content:
            from question_engine import QUESTION_BANK
            return [f"{q['category']} / {q['profile_key'][1]}" for q in QUESTION_BANK]
        missing = []
        current_section = ""
        for line in content.splitlines():
            line = line.strip("\r")
            section_match = re.match(r"^##\s+(.+)", line)
            if section_match:
                current_section = section_match.group(1).strip()
                continue
            if current_section not in _STRUCTURED_SECTIONS:
                continue
            key_match = re.match(r"^-\s+(.+?)\s*:\s*(.*)", line)
            if key_match:
                key = key_match.group(1).strip()
                val = key_match.group(2).strip().lower()
                if not val or val in _PLACEHOLDERS:
                    missing.append(f"{current_section} / {key}")
        return missing
    except Exception:
        return []


def append_inferred_trait(trait: str, cfg: dict) -> None:
    """Append a bullet to the ## Inferred Traits section. Never raises."""
    try:
        content = _read_raw(cfg)
        if not content:
            return
        marker = "## Inferred Traits"
        idx = content.find(marker)
        if idx == -1:
            return
        comment_start = content.find("<!--", idx)
        comment_end = content.find("-->", comment_start)
        if comment_end == -1:
            insert_pos = idx + len(marker) + 1
        else:
            insert_pos = content.find("\n", comment_end) + 1
        content = content[:insert_pos] + f"- {trait.strip()}\n" + content[insert_pos:]
        content = _touch_last_updated(content)
        _write_raw(content, cfg)
    except Exception as e:
        print(f"[AXIOM] append_inferred_trait error: {e}")


def append_open_question(question: str, cfg: dict) -> None:
    """Append a checkbox item to the ## Open Questions section. Never raises."""
    try:
        content = _read_raw(cfg)
        if not content:
            return
        marker = "## Open Questions"
        idx = content.find(marker)
        if idx == -1:
            return
        comment_start = content.find("<!--", idx)
        comment_end = content.find("-->", comment_start)
        if comment_end == -1:
            insert_pos = idx + len(marker) + 1
        else:
            insert_pos = content.find("\n", comment_end) + 1
        content = content[:insert_pos] + f"- [ ] {question.strip()}\n" + content[insert_pos:]
        _write_raw(content, cfg)
    except Exception as e:
        print(f"[AXIOM] append_open_question error: {e}")
