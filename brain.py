"""
AXIOM Brain — Obsidian-backed semantic memory.

The brain is a folder inside the Obsidian vault (default: AXIOM Brain/).
It grows over time as AXIOM crystallises memories, learns preferences,
and reflects on usage patterns. Every note uses wikilinks to connect
related concepts, forming an associative graph visible in Obsidian.

Public API:
    init_brain(cfg)                              — create vault structure on startup
    recall(query, max_tokens, cfg)               — search brain, return context string
    crystallise(utterance, response, tools, cfg) — write episode note if significant
    update_profile(section_note, observation, cfg) — append to a Profile note
    grow_log(entry, cfg)                         — append to Growth Log
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ─── Common words to ignore in concept extraction ────────────────────────────

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "of", "for",
    "and", "or", "but", "so", "with", "what", "how", "can", "you", "me",
    "my", "do", "did", "does", "i", "this", "that", "was", "are", "be",
    "have", "has", "had", "will", "would", "could", "should", "please",
    "okay", "hey", "just", "now", "today", "there", "any", "some", "if",
    "no", "yes", "get", "give", "tell", "show", "open", "check", "make",
    "set", "run", "go", "need", "want", "like", "know", "think", "say",
    "axiom", "from", "here", "when", "where", "which", "who", "why",
})

_PREFERENCE_SIGNALS = (
    "i prefer", "i always", "i never", "remember that", "i like", "i hate",
    "don't ", "always ", "never ", "i want", "i don't want", "make sure",
    "from now on", "please always", "please never",
)


# ─── Path helpers ─────────────────────────────────────────────────────────────

def _brain_root(cfg: dict) -> Optional[Path]:
    brain_cfg = cfg.get("brain", {}) or {}
    if not brain_cfg.get("enabled", True):
        return None
    obsidian_cfg = cfg.get("obsidian", {}) or {}
    vault = obsidian_cfg.get("vault_path", "")
    if not vault:
        return None
    subfolder = brain_cfg.get("vault_subfolder", "AXIOM Brain")
    return Path(vault) / subfolder


def _note_path(cfg: dict, *parts: str) -> Optional[Path]:
    root = _brain_root(cfg)
    if root is None:
        return None
    return root / Path(*parts)


# ─── Initialisation ───────────────────────────────────────────────────────────

def init_brain(cfg: dict) -> None:
    """
    Create the AXIOM Brain folder structure and seed notes on first run.
    Safe to call repeatedly — never overwrites existing notes.
    """
    try:
        root = _brain_root(cfg)
        if root is None:
            return

        folders = [
            root / "Profile",
            root / "Memory" / "Episodes",
            root / "Memory" / "Daily Summaries",
            root / "Skills",
            root / "Self",
        ]
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)

        user_name = cfg.get("assistant", {}).get("name", "Axiom")

        _seed_note(
            root / "Profile" / "User Identity.md",
            f"""---
type: profile
section: identity
---

# User Identity

- **Name:** (to be learned)
- **Assistant name:** {user_name}
- **Background:** (to be learned)
- **Primary language:** English
- **Location:** Eindhoven (inferred from weather queries)

*This note is updated by AXIOM as it learns more about you. You can edit it directly.*
""",
        )

        _seed_note(
            root / "Profile" / "Communication Style.md",
            """---
type: profile
section: communication_style
---

# Communication Style

*AXIOM appends observations here as it learns your preferences.*

## Observations
""",
        )

        _seed_note(
            root / "Profile" / "Working Patterns.md",
            """---
type: profile
section: working_patterns
---

# Working Patterns

*Inferred from session logs and interactions.*

## Observations
""",
        )

        _seed_note(
            root / "Profile" / "Interests & Domains.md",
            """---
type: profile
section: interests
---

# Interests & Domains

*Topics and areas that come up frequently.*

## Observations
""",
        )

        _seed_note(
            root / "Self" / "Growth Log.md",
            """---
type: self
section: growth_log
---

# AXIOM Growth Log

*Append-only record of what AXIOM has learned and what has been improved.*

""",
        )

        _seed_note(
            root / "Self" / "Pending Improvements.md",
            """---
type: self
section: pending
---

# Pending Improvements

*Things AXIOM knows it should be able to do but cannot yet.*

""",
        )

        _seed_capabilities_note(cfg, root)

        print(f"[AXIOM] Brain initialised at {root}")
    except Exception as e:
        print(f"[AXIOM] Brain init warning: {e}")


def _seed_note(path: Path, content: str) -> None:
    """Write note only if it doesn't already exist."""
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _seed_capabilities_note(cfg: dict, root: Path) -> None:
    path = root / "Self" / "Capabilities.md"
    if path.exists():
        return
    try:
        from tools import GEMINI_TOOLS
        declarations = GEMINI_TOOLS[0].get("function_declarations", [])
        lines = [f"- [[{d['name']}]]: {d.get('description', '')}" for d in declarations]
        tools_section = "\n".join(lines)
    except Exception:
        tools_section = "*(tool list unavailable)*"

    scenarios = cfg.get("scenarios", {}) or {}
    scenario_lines = [f"- [[{k}]]: {(v or {}).get('description', '')}" for k, v in scenarios.items()]
    scenarios_section = "\n".join(scenario_lines) if scenario_lines else "*(none defined)*"

    path.write_text(
        f"""---
type: self
section: capabilities
---

# AXIOM Capabilities

*Auto-generated on startup. Re-generated when new tools are added.*

## Tools
{tools_section}

## Scenarios
{scenarios_section}
""",
        encoding="utf-8",
    )


# ─── Recall ───────────────────────────────────────────────────────────────────

def recall(query: str, cfg: dict, max_tokens: int = 400) -> str:
    """
    Search the brain for context relevant to `query`.
    Returns a compact string (≤ max_tokens words) or "" if nothing useful found.
    Never raises.
    """
    try:
        root = _brain_root(cfg)
        if root is None or not root.exists():
            return ""

        concepts = _extract_concepts(query)
        if not concepts:
            return ""

        results: list[tuple[float, str, str]] = []  # (score, note_path, excerpt)

        for md_file in root.rglob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
                score = _score_note(md_file, text, concepts)
                if score > 0:
                    excerpt = _excerpt(text, concepts, max_chars=300)
                    if excerpt:
                        results.append((score, md_file.stem, excerpt))
            except Exception:
                continue

        if not results:
            return ""

        results.sort(key=lambda x: -x[0])
        top = results[:3]

        parts = []
        word_budget = max_tokens
        for _, name, excerpt in top:
            words = excerpt.split()
            if word_budget <= 0:
                break
            chunk = " ".join(words[:word_budget])
            parts.append(f"[{name}] {chunk}")
            word_budget -= len(words)

        return "\n".join(parts)
    except Exception as e:
        print(f"[AXIOM] Brain recall error: {e}")
        return ""


def _extract_concepts(text: str) -> list[str]:
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    seen = set()
    concepts = []
    for w in words:
        if w not in _STOP_WORDS and w not in seen:
            seen.add(w)
            concepts.append(w)
        if len(concepts) >= 6:
            break
    return concepts


def _score_note(path: Path, text: str, concepts: list[str]) -> float:
    text_lower = text.lower()
    name_lower = path.stem.lower()
    score = 0.0
    for concept in concepts:
        if concept in name_lower:
            score += 3.0
        count = text_lower.count(concept)
        score += min(count * 0.5, 2.0)
    # Recency bonus: newer files score higher
    try:
        age_days = (datetime.now().timestamp() - path.stat().st_mtime) / 86400
        score += max(0, 2.0 - age_days * 0.1)
    except Exception:
        pass
    # Wikilink density bonus
    link_count = len(re.findall(r"\[\[", text))
    score += min(link_count * 0.2, 1.0)
    return score


def _excerpt(text: str, concepts: list[str], max_chars: int = 300) -> str:
    # Strip frontmatter
    body = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL).strip()
    # Find a line containing one of the concepts
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    for concept in concepts:
        for i, line in enumerate(lines):
            if concept in line.lower() and len(line) > 10:
                start = max(0, i - 1)
                end = min(len(lines), i + 3)
                snippet = " ".join(lines[start:end])
                return snippet[:max_chars]
    # Fallback: first substantive lines
    return " ".join(lines[:4])[:max_chars]


# ─── Crystallisation ──────────────────────────────────────────────────────────

def crystallise(
    utterance: str,
    response: str,
    tools_called: list[str],
    cfg: dict,
    duration_seconds: float = 0.0,
) -> bool:
    """
    Write an episode note if this interaction is worth remembering.
    Returns True if a note was written.
    """
    try:
        root = _brain_root(cfg)
        if root is None:
            return False

        reason = _significance_reason(utterance, tools_called, duration_seconds, cfg)
        if not reason:
            return False

        now = datetime.now(timezone.utc)
        local_now = datetime.now()
        title_slug = _slugify(utterance[:40])
        filename = f"{local_now.strftime('%Y-%m-%d %H-%M')} {title_slug}.md"
        path = root / "Memory" / "Episodes" / filename

        # Wikilinks: link to tools called and relevant profile notes
        wikilinks = _episode_wikilinks(utterance, tools_called)

        note = f"""---
type: episode
date: {local_now.strftime('%Y-%m-%d')}
time: {local_now.strftime('%H:%M')}
tools: {tools_called}
significance: {reason}
---

**User said:** "{utterance}"

**AXIOM responded:** "{response[:200]}{"…" if len(response) > 200 else ""}"

**Why this was notable:** {reason}

{wikilinks}
"""
        path.write_text(note, encoding="utf-8")
        _maybe_update_skill_notes(tools_called, utterance, cfg, root)
        return True
    except Exception as e:
        print(f"[AXIOM] Brain crystallise error: {e}")
        return False


def _significance_reason(
    utterance: str, tools_called: list[str], duration: float, cfg: dict
) -> str:
    text = utterance.lower()

    # Preference signal
    for signal in _PREFERENCE_SIGNALS:
        if signal in text:
            return f"User expressed a preference: '{signal}' detected"

    # Memory request
    if any(w in text for w in ("remember", "do you know", "have i told you", "recall")):
        return "User referenced memory explicitly"

    # First use of a tool
    try:
        from session_logger import get_recent_logs
        recent_tools: set[str] = set()
        for entry in get_recent_logs(days=30):
            for t in entry.get("tools_called", []):
                recent_tools.add(t)
        for tool in tools_called:
            if tool and tool not in recent_tools:
                return f"First use of tool: {tool}"
    except Exception:
        pass

    # Long interaction
    threshold = float((cfg.get("brain", {}) or {}).get("crystallise_threshold_seconds", 20))
    if duration >= threshold:
        return f"Complex interaction ({duration:.0f}s)"

    # Named entities (capitalised words that aren't common)
    tokens = re.findall(r"\b[A-Z][a-z]{2,}\b", utterance)
    named = [t for t in tokens if t.lower() not in _STOP_WORDS and len(t) > 3]
    if len(named) >= 2:
        return f"Named entities mentioned: {', '.join(named[:3])}"

    return ""


def _episode_wikilinks(utterance: str, tools_called: list[str]) -> str:
    links = set()
    # Add tool links
    for tool in tools_called:
        if tool:
            links.add(f"[[{tool}]]")
    # Add profile links based on content
    text = utterance.lower()
    if any(w in text for w in ("schedule", "calendar", "meeting", "event")):
        links.add("[[Working Patterns]]")
    if any(w in text for w in ("prefer", "always", "never", "like", "hate", "want")):
        links.add("[[Communication Style]]")
    if any(w in text for w in ("music", "spotify", "weather", "travel", "university", "course")):
        links.add("[[Interests & Domains]]")
    if not links:
        links.add("[[Working Patterns]]")
    return " ".join(sorted(links))


def _maybe_update_skill_notes(
    tools_called: list[str], utterance: str, cfg: dict, root: Path
) -> None:
    for tool in tools_called:
        if not tool:
            continue
        path = root / "Skills" / f"{tool}.md"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        if not path.exists():
            path.write_text(
                f"""---
type: skill
tool: {tool}
---

# {tool}

*Auto-created when first used.*

## Usage Notes
- {now_str}: Used for "{utterance[:80]}"
""",
                encoding="utf-8",
            )
        else:
            existing = path.read_text(encoding="utf-8")
            path.write_text(
                existing + f"- {now_str}: \"{utterance[:80]}\"\n",
                encoding="utf-8",
            )


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:40].strip("-")


# ─── Profile updates ──────────────────────────────────────────────────────────

def update_profile(section_note: str, observation: str, cfg: dict) -> None:
    """
    Append a timestamped observation to a Profile note.
    `section_note` is the filename without extension, e.g. 'Communication Style'.
    Never raises.
    """
    try:
        root = _brain_root(cfg)
        if root is None:
            return
        path = root / "Profile" / f"{section_note}.md"
        if not path.exists():
            path.write_text(
                f"""---
type: profile
---

# {section_note}

## Observations
""",
                encoding="utf-8",
            )
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        existing = path.read_text(encoding="utf-8")
        path.write_text(existing + f"- {now_str}: {observation}\n", encoding="utf-8")
    except Exception as e:
        print(f"[AXIOM] Brain update_profile error: {e}")


# ─── Growth log ───────────────────────────────────────────────────────────────

def grow_log(entry: str, cfg: dict) -> None:
    """
    Append a timestamped entry to Self/Growth Log.md. Never raises.
    """
    try:
        root = _brain_root(cfg)
        if root is None:
            return
        path = root / "Self" / "Growth Log.md"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        if not path.exists():
            path.write_text("---\ntype: self\n---\n\n# Growth Log\n\n", encoding="utf-8")
        existing = path.read_text(encoding="utf-8")
        path.write_text(existing + f"- {now_str}: {entry}\n", encoding="utf-8")
    except Exception as e:
        print(f"[AXIOM] Brain grow_log error: {e}")
