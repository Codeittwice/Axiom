# AXIOM Self-Learning Intelligence Layer

## Context

AXIOM currently treats every interaction as stateless beyond a rolling conversation history (`memory.json`). There is no record of _which tools_ were used, _when_ the user typically works, _what patterns_ repeat across sessions, or _what gaps_ exist between what the user asks for and what AXIOM can do. This plan adds a self-learning layer: AXIOM observes interactions, builds a user model, generates suggestions, and presents them for human approval. Nothing auto-implements.

---

## New Files to Create

### 1. `session_logger.py`

Thin write-only module. Called after every voice interaction.

**Log entry schema** — written as JSONL to `data/session_logs/YYYY-MM-DD.jsonl`:

```json
{
  "session_id": "uuid4",
  "timestamp": "2026-05-07T14:32:11Z",
  "user_utterance": "open the axiom project",
  "axiom_response": "Opening AXIOM in VS Code.",
  "tools_called": ["open_repo"],
  "duration_seconds": 3.2,
  "time_of_day": "afternoon",
  "day_of_week": "Wednesday",
  "session_number": 142
}
```

**Public API:**

```python
def log_session(user_utterance, axiom_response, tools_called, duration_seconds) -> str
def get_recent_logs(days=7) -> list[dict]
def get_session_count() -> int
```

- `_SESSION_LOGS_DIR = Path("data/session_logs")` — created on first write
- `time_of_day` derived from hour: 5-11=morning, 12-16=afternoon, 17-21=evening, else night
- All exceptions swallowed — log failure must never crash the assistant

---

### 2. `reflection.py`

The intelligence core. Reads logs + user model, calls Gemini, writes suggestions.

**Public API:**

```python
def run_reflection(cfg: dict) -> list[dict]
def build_skill_registry(cfg: dict) -> dict
```

**`build_skill_registry()`** — computed live, not stored. Reads `GEMINI_TOOLS` from `tools.py` + `scenarios` from config + usage counts from session logs.

**`run_reflection()` flow:**

1. Read last N days of session logs (`cfg["learning"]["reflection_window_days"]`, default 7)
2. Load `data/user_model.json` (or skeleton if not yet created)
3. Call `build_skill_registry()`
4. Compress logs to a token-efficient summary (top tool counts + last 30 utterances)
5. Call Gemini with `response_mime_type: "application/json"` — forces structured output
6. Parse result into suggestion dicts (UUID, type, title, reasoning, evidence, proposal, status=pending)
7. Skip duplicates by title (case-insensitive) and anything matching `rejected_suggestions` in user model
8. Append new suggestions to `data/suggestions.json`
9. Update `data/user_model.json` (working_hours histogram, domain tallies, session count)

**Gemini prompt structure:**

```
Current user model (JSON) + Skill registry (JSON) + Session summary text + Rejected suggestion IDs
→ JSON array of 1-5 suggestions
```

**Suggestion schema:**

```json
{
  "id": "uuid",
  "created_at": "ISO timestamp",
  "type": "new_skill | refine_skill | deprecate | chain | preference | scenario",
  "title": "Short title (max 60 chars)",
  "reasoning": "Pattern observed and why this helps",
  "evidence": ["specific utterances or session IDs"],
  "proposal": {
    "description": "What would be built/changed",
    "estimated_complexity": "trivial | low | medium | high",
    "files_to_modify": ["tools.py"]
  },
  "status": "pending",
  "user_notes": ""
}
```

---

## Existing Files to Modify

### 3. `voice_assistant.py` — `ask_ai()` at line 317

Change return type from `tuple[str, list]` → `tuple[str, list, list[str]]`.

**Step 1** — add at top of function body:

```python
_tools_called: list[str] = []
```

**Step 2** — direct-tool return at line 340:

```python
# after: reply = clean_text(execute_tool(name, args))
_tools_called.append(name)
# change: return reply, _maybe_summarize_history(updated_history)
return reply, _maybe_summarize_history(updated_history), _tools_called
```

**Step 3** — inside the tool-use loop, after `result = clean_text(execute_tool(fn.name, args))` (line ~373):

```python
_tools_called.append(fn.name)
```

**Step 4** — final return at line 392:

```python
return reply, _maybe_summarize_history(updated_history), _tools_called
```

No other file imports `ask_ai` — the only downstream change is in `server.py`.

---

### 4. `server.py` — `assistant_loop()` at lines 407-456

**Step 1** — Add session timing. Before `record_audio()` (line 419):

```python
import time as _time
session_start = _time.time()
```

**Step 2** — Unpack new return value. Line 443:

```python
# was: reply, history = ask_ai(text, history)
reply, history, tools_called = ask_ai(text, history)
```

**Step 3** — Log session after `speak()` returns (after line 454):

```python
session_duration = _time.time() - session_start
try:
    from session_logger import log_session
    log_session(text, reply, tools_called, round(session_duration, 2))
    _check_auto_reflect(CFG)
except Exception as e:
    emit("log", {"level": "warn", "text": f"Session log failed: {e}"})
```

**Step 4** — Add module-level helpers:

```python
_sessions_since_reflect = 0

def _check_auto_reflect(cfg):
    global _sessions_since_reflect
    learning = cfg.get("learning", {}) or {}
    if not learning.get("reflection_enabled", True):
        return
    threshold = int(learning.get("auto_reflect_after_sessions", 10))
    _sessions_since_reflect += 1
    if _sessions_since_reflect >= threshold:
        _sessions_since_reflect = 0
        threading.Thread(target=_run_reflection_bg, daemon=True).start()

def _run_reflection_bg():
    try:
        from reflection import run_reflection
        suggestions = run_reflection(CFG)
        if suggestions:
            emit("log", {"level": "system", "text": f"Reflection: {len(suggestions)} new suggestion(s)."})
            socketio.emit("suggestions_updated", {"count": len(suggestions)})
    except Exception as e:
        print(f"[AXIOM] Reflection error: {e}")
```

**Step 5** — Add new API endpoints:

- `GET /api/suggestions?status=pending` — return `data/suggestions.json`
- `POST /api/suggestions/<id>/approve` — mark approved, update `data/user_model.json`
- `POST /api/suggestions/<id>/reject` — mark rejected, add to `rejected_suggestions` in user model
- `GET /api/user-model` — return `data/user_model.json`
- `POST /api/reflect` — trigger `_run_reflection_bg()` in daemon thread
- `GET /api/skill-registry` — call `build_skill_registry(CFG)`

**Step 6** — Add `_update_user_model_approval(suggestion_id, approved: bool)` helper for approve/reject endpoints.

---

### 5. `config.yaml` — add `learning:` section

```yaml
learning:
  reflection_enabled: true
  auto_reflect_after_sessions: 10
  reflection_window_days: 7
  session_logs_dir: data/session_logs
  user_model_file: data/user_model.json
  suggestions_file: data/suggestions.json
```

---

### 6. `voice_assistant_ui.html` — "Learn" tab

**Tab button** — insert after line 879 (after the History button):

```html
<button class="tab-btn" data-tab="learn">Learn</button>
```

**Tab view** — insert between line 1120 (`</section>` end of history) and line 1121 (`</div>` closing `.wrap`):

```html
<section class="view" id="view-learn">
  <div class="ops-panel">
    <div class="ops-head">
      <span>// INTELLIGENCE</span><span class="toast" id="learnToast"></span>
    </div>
    <div class="learn-model-strip" id="learnModelStrip"></div>
    <div class="btn-row">
      <button class="cmd-btn primary" id="runReflectBtn">Run Reflection</button>
      <button class="cmd-btn" id="refreshLearnBtn">Refresh</button>
    </div>
    <div class="learn-section-label">// PENDING SUGGESTIONS</div>
    <div id="suggestionsList"></div>
    <div class="learn-section-label">// APPROVED</div>
    <div id="approvedList"></div>
  </div>
</section>
```

**Tab click handler** — extend the existing check at line 1609:

```javascript
if (btn.dataset.tab === "history") await loadHistory();
if (btn.dataset.tab === "learn") await loadLearn();
```

**SocketIO event** — add alongside existing socket event handlers:

```javascript
socket.on("suggestions_updated", (data) => {
  if (document.getElementById("view-learn").classList.contains("active"))
    loadLearn().catch(() => {});
  addLog("system", `Reflection: ${data.count} new suggestion(s).`);
});
```

**JavaScript functions to add:**

- `loadLearn()` — parallel `GET /api/suggestions` + `GET /api/user-model`
- `renderUserModel(model)` — chips: session count, top tool, peak hour, last updated
- `renderSuggestions(items)` — split pending/approved, render cards
- `renderCard(s)` — title, type badge, complexity badge, reasoning, proposal, evidence, Approve/Reject buttons
- `approveSuggestion(id)` — POST then reload
- `rejectSuggestion(id)` — POST then reload
- `runReflection()` — POST `/api/reflect` then reload after 3s

**CSS additions** — inside existing `<style>` block:

- `.learn-model-strip` — flex row of chips
- `.learn-chip` — monospace, bordered, accent color
- `.suggestion-card` — panel background with border (`.approved` gets green border, `.rejected` gets 0.45 opacity)
- `.complexity-badge` — colored by level: trivial=green, low=cyan, medium=orange, high=red
- `.learn-section-label` — muted monospace section dividers

---

## Data Directory Created

```
data/
  session_logs/
    YYYY-MM-DD.jsonl    (one per day, append-only)
  user_model.json       (created on first reflection)
  suggestions.json      (created on first reflection)
```

The `data/` directory is created at first write — no migration script needed. Add `data/` to `.gitignore` (personal data).

---

## User Model Schema

```json
{
  "session_count": 0,
  "communication_style": {
    "preferred_response_length": "unknown",
    "technical_level": "unknown",
    "tone_observations": []
  },
  "working_hours": { "14": 12, "15": 8 },
  "frequent_domains": { "today_schedule": 18, "open_repo": 14 },
  "delegation_threshold": "low",
  "interaction_patterns": [],
  "rejected_suggestions": [],
  "approved_suggestions": [],
  "last_updated": "ISO timestamp"
}
```

---

## Implementation Order

1. Create `session_logger.py` (standalone, no new dependencies)
2. Update `ask_ai()` in `voice_assistant.py` — add `_tools_called` list and return it
3. Update `assistant_loop()` in `server.py` — unpack new return, add timing, call `log_session()`
4. Add `learning:` section to `config.yaml`
5. Create `reflection.py` (depends on session_logger + Gemini API already in use)
6. Add new API endpoints to `server.py`
7. Add "Learn" tab to `voice_assistant_ui.html` (HTML, CSS, JS)
8. Add `data/` to `.gitignore`

---

## Verification

1. Start AXIOM normally — run 3+ voice interactions
2. Check `data/session_logs/YYYY-MM-DD.jsonl` was created with correct entries
3. Call `POST /api/reflect` from browser console: `fetch('/api/reflect',{method:'POST'})`
4. Check `data/suggestions.json` and `data/user_model.json` created
5. Open the Learn tab — verify suggestion cards render with Approve/Reject buttons
6. Approve one suggestion — verify `status` changes to `approved` in the JSON and moves to the Approved section
7. Reject one — verify it gets `status: rejected` and is added to `user_model.rejected_suggestions`
8. Run 10 more sessions — verify auto-reflection triggers and the `suggestions_updated` SocketIO event logs to the terminal
