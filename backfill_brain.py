"""
One-shot backfill: import existing memory.json and user_model.json into the AXIOM Brain.

Run once from the project root:
    python backfill_brain.py

Safe to re-run — crystallise writes uniquely-named files based on content hash,
so duplicates won't appear.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# ── Load config ───────────────────────────────────────────────────────────────
try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)

with open("config.yaml", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

# ── Load brain ────────────────────────────────────────────────────────────────
try:
    from brain import init_brain, crystallise, update_profile, grow_log, _brain_root
except ImportError as e:
    print(f"ERROR: could not import brain.py: {e}")
    sys.exit(1)

# Ensure vault structure exists
init_brain(CFG)

root = _brain_root(CFG)
if root is None:
    print("ERROR: brain root is None — check obsidian.vault_path in config.yaml")
    sys.exit(1)

print(f"[backfill] Brain root: {root}")


# ── Helper ────────────────────────────────────────────────────────────────────

def _write_backfill_episode(root: Path, utterance: str, response: str, slug_hash: str) -> bool:
    """Write a single backfill episode note. Returns True if written."""
    import re
    from datetime import datetime

    def _slugify(text: str) -> str:
        text = re.sub(r"[^\w\s-]", "", text).strip()
        text = re.sub(r"[\s_-]+", "-", text)
        return text[:40].strip("-")

    now = datetime.now()
    title_slug = _slugify(utterance[:40])
    filename = f"backfill {title_slug} {slug_hash}.md"
    path = root / "Memory" / "Episodes" / filename

    links: set[str] = set()
    text = utterance.lower()
    if any(w in text for w in ("schedule", "calendar", "meeting", "event")):
        links.add("[[Working Patterns]]")
    if any(w in text for w in ("prefer", "always", "never", "like", "hate", "want", "priority")):
        links.add("[[Communication Style]]")
    if any(w in text for w in ("music", "spotify", "weather", "travel", "university", "course", "wake", "obsidian")):
        links.add("[[Interests & Domains]]")
    if any(w in text for w in ("task", "obsidian", "inbox", "note", "capture")):
        links.add("[[Working Patterns]]")
    if not links:
        links.add("[[Working Patterns]]")

    note = f"""---
type: episode
date: {now.strftime('%Y-%m-%d')}
source: backfill
significance: historical interaction
---

**User said:** "{utterance}"

**AXIOM responded:** "{response[:200]}{"…" if len(response) > 200 else ""}"

**Why this was notable:** Imported from conversation history during brain backfill.

{" ".join(sorted(links))}
"""
    try:
        path.write_text(note, encoding="utf-8")
        return True
    except Exception as e:
        print(f"  [error] {e}")
        return False


# ── Back-fill from memory.json ────────────────────────────────────────────────
memory_path = Path("memory.json")
if not memory_path.exists():
    print("[backfill] No memory.json found — skipping conversation history.")
    history = []
else:
    with open(memory_path, encoding="utf-8") as f:
        history = json.load(f)
    print(f"[backfill] Loaded {len(history)} history entries from memory.json")

# Pair up user→model turns (skip leading summary turns)
episodes_written = 0
i = 0
while i < len(history) - 1:
    entry = history[i]
    next_entry = history[i + 1]

    if entry.get("role") == "user" and next_entry.get("role") == "model":
        utterance = entry.get("text", "").strip()
        response = next_entry.get("text", "").strip()

        # Skip the auto-generated summary turn
        if utterance.startswith("Use this brief summary"):
            i += 2
            continue

        # Deduplicate: use a hash of the utterance as part of the filename check
        slug_hash = hashlib.md5(utterance.encode()).hexdigest()[:8]
        episode_dir = root / "Memory" / "Episodes"
        existing = list(episode_dir.glob(f"*{slug_hash}*.md"))
        if existing:
            print(f"  [skip] already exists: {existing[0].name}")
            i += 2
            continue

        # Write the episode with a low significance override (always crystallise for backfill)
        _wrote = _write_backfill_episode(root, utterance, response, slug_hash)
        if _wrote:
            episodes_written += 1
            print(f"  [ok] episode: {utterance[:60]!r}")

        i += 2
    else:
        i += 1

print(f"[backfill] Wrote {episodes_written} episode note(s) from memory.json")

# ── Back-fill profile from user_model.json ────────────────────────────────────
user_model_path = Path("data/user_model.json")
if user_model_path.exists():
    with open(user_model_path, encoding="utf-8") as f:
        user_model = json.load(f)

    freq = user_model.get("frequent_domains", {})
    if freq:
        top_tools = sorted(freq.items(), key=lambda x: -x[1])[:5]
        tools_str = ", ".join(f"{t}({c})" for t, c in top_tools)
        update_profile("Working Patterns", f"[backfill] Top tools from history: {tools_str}", CFG)
        print(f"[backfill] Working Patterns updated: {tools_str}")

    wh = {k: v for k, v in user_model.get("working_hours", {}).items() if str(k).isdigit()}
    if wh:
        peak_hour = max(wh, key=lambda h: wh[h])
        update_profile("Working Patterns", f"[backfill] Peak active hour: {peak_hour}:00", CFG)
        print(f"[backfill] Peak hour: {peak_hour}:00")

    session_count = user_model.get("session_count", 0)
    grow_log(f"[backfill] Brain seeded from {session_count} historical sessions.", CFG)
    print(f"[backfill] Growth log updated ({session_count} sessions)")
else:
    print("[backfill] No user_model.json found — skipping profile backfill.")

print("\n[backfill] Done. Open Obsidian > AXIOM Brain to explore the notes.")
