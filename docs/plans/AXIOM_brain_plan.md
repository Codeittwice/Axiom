# AXIOM Brain — Obsidian-backed Semantic Memory

## Context

AXIOM currently has three disconnected memory layers:

- `memory.json` — short rolling conversation history (50 turns, auto-summarized)
- `data/user_model.json` — flat JSON with usage tallies and a few typed fields
- `data/session_logs/*.jsonl` — raw per-interaction records, readable only by code

These are machine-legible but not connected, not human-browsable, and don't form a living knowledge graph. The "brain" concept treats AXIOM's Obsidian vault as its actual long-term memory: interconnected notes with wikilinks create an associative graph that AXIOM reads before responding and writes to after learning something. The user can browse, edit, or correct it in Obsidian directly.

Three new behaviours this enables:

1. **Recall** — before answering, AXIOM searches its brain for relevant memories and injects them as context, making responses more personalised over time
2. **Crystallisation** — after notable interactions, AXIOM writes a structured memory note
3. **Growth** — reflection writes findings as living notes (not just JSON) that accumulate semantic links

---

## Vault Structure

Created under the existing vault at `E:/_DEV/Personal Voice Assistant/AXIOM Brain/`:

```
AXIOM Brain/
  Profile/
    User Identity.md       # name, role, background, how the user prefers to be addressed
    Communication Style.md # verbosity, technical depth, tone notes
    Working Patterns.md    # active hours, typical tasks, delegation comfort
    Interests & Domains.md # recurring topics: dev, uni, music, travel, etc.
  Memory/
    Episodes/              # one .md per significant interaction
      YYYY-MM-DD HH-MM Title.md
    Daily Summaries/       # end-of-day digest, written once per day
  Skills/
    [tool_name].md         # usage notes, when to call, observed failures/wins
    [scenario_name].md     # scenario docs, when last used, user feedback
  Self/
    Capabilities.md        # what AXIOM can and cannot currently do
    Growth Log.md          # append-only log: what was learned/changed and when
    Pending Improvements.md # things AXIOM knows it should become able to do
```

Every note uses Obsidian frontmatter + wikilinks. Connections between notes (e.g. an Episode linking to a Skill note) form the associative graph. The user can view this as Obsidian's graph view.

---

## New File: `brain.py`

~350 lines. Four public functions, everything else internal.

### `recall(query: str, max_tokens: int = 500) -> str`

Called inside `ask_ai()` before building the Gemini message.

1. Extract 3-5 key concepts from `query` (simple keyword extraction, no LLM call)
2. Search `AXIOM Brain/` recursively for notes containing those concepts (reuse `search_notes` logic)
3. Score results by: recency of note (mtime), presence of concept in title, number of wikilinks
4. Return top 3 excerpts concatenated, truncated to `max_tokens`
5. Returns `""` if brain folder doesn't exist yet (graceful no-op at startup)

### `crystallise(utterance: str, response: str, tools_called: list[str], cfg: dict) -> bool`

Called after each interaction in `assistant_loop()`.

**Significance heuristic** — crystallise if ANY of:

- A tool was called that hasn't been called before (first use of a skill)
- User utterance contains a preference signal: "I prefer", "I always", "I never", "remember that", "I like", "I hate", "don't", "always"
- User utterance mentions a named person, course, project, or place (NER-lite: capitalized words not in common dict)
- The interaction took > 20 seconds (signals complexity)

If significant, write an episode note to `AXIOM Brain/Memory/Episodes/`:

```markdown
---
type: episode
date: 2026-05-07
time_of_day: morning
tools: [get_weather, today_schedule]
---

**User said:** "What's the weather and do I have anything today?"
**AXIOM did:** Called [[get_weather]] for Eindhoven, then [[today_schedule]].
**Learned:** User checks weather + schedule together every morning. Consider [[morning_routine]] scenario.

[[Working Patterns]] [[get_weather]] [[today_schedule]]
```

Wikilinks at the bottom connect this episode to Profile notes and Skill notes — these are the "synapses".

### `update_profile(section_note: str, observation: str, cfg: dict) -> None`

Appends a timestamped bullet to a Profile note. Used by reflection to update `Communication Style.md`, `Working Patterns.md` etc. Never overwrites — only appends, so history accumulates.

### `grow_log(entry: str, cfg: dict) -> None`

Appends a timestamped entry to `AXIOM Brain/Self/Growth Log.md`. Called whenever a suggestion is implemented or a new skill added.

---

## Changes to Existing Files

### `voice_assistant.py` — `_system_prompt()` and `ask_ai()`

**In `_system_prompt()`**: no change needed — brain context is injected separately.

**In `ask_ai()`**, add before the Gemini call:

```python
# Brain recall — inject relevant long-term context
_brain_ctx = ""
try:
    from brain import recall
    _brain_ctx = recall(user_text, max_tokens=400)
except Exception:
    pass
```

Then prepend to the Gemini message history as a synthetic "system note" turn:

```python
if _brain_ctx:
    gemini_history = [
        {"role": "user",  "parts": [{"text": f"[AXIOM memory context]\n{_brain_ctx}"}]},
        {"role": "model", "parts": [{"text": "Understood, I'll keep this context in mind."}]},
    ] + gemini_history
```

This adds < 400 tokens per call and doesn't touch the stored `memory.json` history.

**In `server.py` `assistant_loop()`**, after `log_session()`:

```python
try:
    from brain import crystallise
    crystallise(text, reply, tools_called, CFG)
except Exception:
    pass
```

### `reflection.py` — extend `run_reflection()`

After writing `suggestions.json`, also call:

```python
from brain import update_profile, grow_log
_write_reflection_to_brain(user_model, logs, new_suggestions, cfg)
```

New helper `_write_reflection_to_brain()`:

- Appends key findings to `Working Patterns.md` and `Interests & Domains.md`
- Writes a `Daily Summaries/YYYY-MM-DD.md` note if not already written today
- Appends each new suggestion title to `Pending Improvements.md`

### `tools.py` — two new voice-accessible brain tools

```python
def recall_memory(query: str) -> str:
    """Search AXIOM's brain for memories related to query."""
    from brain import recall
    result = recall(query, max_tokens=600)
    return result if result else "Nothing found in memory for that topic."

def remember_preference(text: str) -> str:
    """Store a user-dictated preference to the brain."""
    from brain import update_profile
    update_profile("Communication Style", text, CFG)
    return f"Noted and saved to memory: {text}"
```

Register in GEMINI_TOOLS and dispatcher. Add to system prompt rules:

- Call `remember_preference` when user says "remember that", "I prefer", "always", "never"
- Call `recall_memory` when user says "do you remember", "what did I say about", "have I told you"

### `config.yaml` — new `brain:` section

```yaml
brain:
  enabled: true
  vault_subfolder: "AXIOM Brain" # relative to obsidian.vault_path
  recall_on_every_request: true # inject context before each response
  crystallise_threshold_seconds: 20 # crystallise if interaction took this long
  max_recall_tokens: 400
  max_episodes: 500 # prune oldest if exceeded
```

---

## Brain Initialisation

`brain.py` has an `init_brain(cfg)` function called once at startup from `server.py`. It creates the folder structure and seed notes if they don't exist:

- `Profile/User Identity.md` — pre-filled with `name: Hamish` (from config `assistant.name`)
- `Self/Capabilities.md` — auto-generated list of current tools from GEMINI_TOOLS
- `Self/Growth Log.md` — empty, with frontmatter
- All other folders created empty

This means the brain is usable from the first session with no manual setup.

---

## How It Grows Over Time

**Session 1-10**: Brain is sparse. Recall returns little or nothing. Crystallisation starts writing episode notes.

**Session 10-50**: Profile notes accumulate observations. Pattern notes form. Skill notes get usage annotations. Recall starts returning relevant context.

**Session 50+**: AXIOM knows: you work mornings, check weather for Eindhoven, prefer concise answers for routine queries but more detail for technical ones, care about AXIOM and LabForge projects, listen to lo-fi when working. This knowledge shapes every response without the user having to repeat it.

**After reflection runs**: Summaries tie individual episodes into synthesised knowledge. Growth Log records the evolution.

---

## Implementation Order

1. Create `brain.py` — `init_brain`, `recall`, `crystallise`, `update_profile`, `grow_log`
2. Add `brain:` section to `config.yaml`
3. Call `init_brain(CFG)` in `server.py` startup (before `assistant_loop`)
4. Add recall injection to `ask_ai()` in `voice_assistant.py`
5. Add crystallisation call in `assistant_loop()` in `server.py`
6. Add `recall_memory` and `remember_preference` tools to `tools.py`
7. Extend `reflection.py` to write to brain notes
8. Update system prompt rules for the two new tools

---

## Verification

1. Start AXIOM — check `AXIOM Brain/` folder created with seed notes
2. Make 3 voice requests — check `Memory/Episodes/` for crystallised notes
3. Say "remember that I prefer short answers" — check `Profile/Communication Style.md` updated
4. Say "do you remember what I said about short answers?" — AXIOM should reference it
5. Run reflection — check `Daily Summaries/` and `Pending Improvements.md` updated
6. Open Obsidian, open Graph View — verify wikilinks connect episodes to profile and skill notes
