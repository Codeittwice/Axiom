# AXIOM Phase 6 — Academic & Productivity Skills

## Context

AXIOM has completed Phase 4 (Settings UI). The user is a student and wants to extend AXIOM with skills that support their daily academic workflow:

- Voice access to Google Calendar ("what's on today")
- On-demand reading of unread Gmail since last check
- Side-panel UI widgets on the Live view showing schedule, todos, assignments, project progress, course objectives, unread email
- Reading todos / assignments / learning objectives from the user's existing **Obsidian vault** (single source of truth)
- Lecture slide ingestion (PDF/PPTX) into AI-summarized Obsidian notes — Canvas is inaccessible, so slides are dropped manually into the vault and synced across devices via the user's existing Obsidian vault sync (Obsidian Sync / OneDrive / Syncthing)
- Scenario-based NotebookLM session (NotebookLM has no public API; just open it + the slides folder)
- Optional bonus skills: Pomodoro, flashcards, quick capture, reading queue, weekly review

This expands the existing **Phase 6: Advanced Tools** in `AXIOM_development_plan.md` with concrete student-focused work, sequenced into independently-shippable sub-phases.

## Decisions already locked in (from clarifying questions)

| Topic | Decision |
|---|---|
| NotebookLM | Launch via scenario only — open in browser + open slides folder. No browser automation. |
| Todos / courses / objectives | **Source of truth = Obsidian markdown.** Parse `- [ ]` checkboxes with inline metadata + frontmatter. |
| Lecture slides | Stored in Obsidian vault under `Lectures/<course>/Slides/`; sync handled by user's existing vault sync mechanism. AXIOM reads local copy and writes summaries to `Lectures/<course>/Notes/`. |
| Email | On-demand only. Persistent `last_checked` cursor. No background polling. Subjects+senders+snippet only — never full bodies unless explicitly asked. |

## Architecture rules to respect

- New helper modules carry the complexity (`google_auth.py`, `google_calendar.py`, `gmail_client.py`, `tasks_index.py`, `lectures.py`).
- `tools.py` stays flat: each tool is a thin wrapper that returns ≤800 chars of speakable prose.
- REST endpoints in `server.py` return rich JSON for the UI; voice tools summarize.
- All tool implementations catch their own exceptions and return friendly error strings (per §15.3 of dev plan).
- Reuse existing helpers where possible: `create_note`, `read_note`, `append_daily_note`, `search_notes`, `_send`, `set_emit`, `reload_runtime_config`, `ScenarioEngine`.

---

## Sub-phase 6a — Google Calendar

**New files**

- `google_auth.py` (~120 lines) — shared OAuth helper.
  - `get_credentials(scopes) -> Credentials` using `InstalledAppFlow.run_local_server()`.
  - Reads `secrets/google_oauth_client.json`, caches token at `secrets/google_token.json`, refreshes silently.
  - Module-level service cache keyed on `(api, version, scopes)`.
  - `revoke()` clears the token (used by future Settings disconnect).
- `google_calendar.py` (~140 lines) wrapping `googleapiclient.discovery.build("calendar","v3")`.
  - `today_events()`, `next_event()`, `list_events(start_iso, end_iso)`, `create_event(title, when, duration_min)`.
  - `dateparser` for natural-language `when`.
  - `_format_event` returns `{id, title, start, end, location, link}`.
  - Catches `HttpError` and returns `[]` / `{}` so tool wrappers stay simple.

**Modify [tools.py](tools.py)** — add tool declarations after the existing block (~line 339) and dispatch entries in the lambda map (~line 692):

| Tool | Params |
|---|---|
| `today_schedule` | — |
| `next_event` | — |
| `list_events` | `start: str, end: str` (ISO) |
| `create_event` | `title: str, when: str, duration_minutes?: int=60` |

**Modify [server.py](server.py)** — add after line ~180:

- `GET /api/calendar/today` → `{events: [...]}`
- `GET /api/calendar/upcoming?days=7`

**`config.yaml`** additions:
```yaml
google:
  oauth_credentials_file: "secrets/google_oauth_client.json"
  token_file: "secrets/google_token.json"
  enable_calendar: false
  calendar_id: "primary"
  timezone: "Europe/Sofia"
```

**`requirements.txt`**: `google-auth-oauthlib`, `google-api-python-client`, `dateparser`.

**`.gitignore`**: `secrets/`, `*.token.json`.

**Voice phrases**
- "What's on my schedule today?"
- "What's my next meeting?"
- "Add an event 'study session' tomorrow at 2pm for 90 minutes"
- "What do I have on Friday?"

**Acceptance**
- First call opens browser for OAuth; token persists; second call is silent.
- `curl http://127.0.0.1:5000/api/calendar/today` returns JSON.
- Voice "what's on today" speaks the events.

---

## Sub-phase 6b — Gmail (read-only, on-demand)

**New file** `gmail_client.py` (~150 lines)
- Uses `google_auth.get_credentials([gmail.readonly])`.
- State file `secrets/last_email_check.json` carries the last-checked ISO timestamp.
- `unread_since_last_check()` queries `is:unread after:{ts}`, updates the timestamp on success.
- `last_emails(n=5)` newest n.
- `summarize_inbox()` returns count + 3 most-recent senders+subjects (≤80 char snippet).
- All returned dicts: `{id, sender, subject, snippet, ts}`. Bodies never returned.
- `mark_check_now()` to manually reset the cursor.

**Modify [tools.py](tools.py)** — add three tools and dispatch entries:

| Tool | Behavior |
|---|---|
| `unread_since_last_check` | "Any new email since I last checked?" |
| `last_emails` | `n: int=5` |
| `summarize_inbox` | Speakable inbox summary |

**Modify [server.py](server.py)**:
- `GET /api/email/unread` → `{count, items: [...]}` (no bodies)
- `GET /api/email/recent?n=10`
- `POST /api/email/mark_check`

**`config.yaml`**:
```yaml
gmail:
  enabled: false
  scopes: ["https://www.googleapis.com/auth/gmail.readonly"]
  state_file: "secrets/last_email_check.json"
  use_gemini_summary: false
  max_results: 20
```

**Privacy rules**
- `gmail.readonly` scope only — never `modify` or `send`.
- Snippets ≤80 chars. Full body access requires explicit voice phrase ("read the full email from X") and is gated by a confirm step in the tool wrapper.
- No bodies sent to Gemini for summaries unless `gmail.use_gemini_summary: true` AND the user has explicitly requested it.

**Voice phrases**
- "Any new emails since I last checked?"
- "Show the last five emails"
- "Summarize my inbox"
- "Mark email check now"

**Acceptance**
- `unread_since_last_check()` returns N first call, 0 second call (no new mail).
- Body fields never appear in REST response payloads.

---

## Sub-phase 6c — Obsidian Tasks, Courses, Objectives

**New file** `tasks_index.py` (~280 lines) — vault parser with mtime cache.

**Parsing rules**
- Task line regex: `^\s*-\s*\[( |x|X)\]\s*(.+)$`
- Inline metadata in the task text: `due:YYYY-MM-DD`, `priority:(high|med|low)`, `course:cs101`, `#cs101` hashtag → course, `@today`/`@tomorrow`/`@thisweek` → resolved dates, `type:assignment`.
- Frontmatter parsed with `pyyaml`. Course `index.md` example:
  ```yaml
  ---
  course_id: cs101
  course_name: "Intro to CS"
  learning_objectives: ["LO1", "LO2"]
  progress_pct: 60
  ---
  ```

**Public API**
- `list_todos(filter)` — filter by `course`, `due_before`, `priority`, `done`.
- `list_assignments(course=None)` — tasks under `# Assignments` heading or with `type:assignment`.
- `next_due(n=5)` — sorted ascending by due date.
- `mark_done(task_id)` — atomic rewrite (`[ ]` → `[x]`) via temp file + rename.
- `list_courses()` — scans `<vault>/<courses_folder>/<id>/index.md`.
- `course_objectives(course)` / `course_progress(course)`.

**Caching**
- In-memory `{path: (mtime, parsed)}`; on every call walk vault, reparse only changed files.
- Bounded scan via `obsidian.tasks_scan_paths`.
- Task IDs = stable hash of `(path, line_number, raw_text)`.

**Modify [tools.py](tools.py)** — add 6 tools + dispatch entries:

| Tool | Params |
|---|---|
| `list_todos` | `filter?: str` (e.g. `today`, `this_week`, `overdue`, `course=cs101`, `priority=high`) |
| `list_assignments` | `course?: str` |
| `next_due` | `n: int=5` |
| `mark_done` | `task_id: str` |
| `list_courses` | — |
| `course_objectives` | `course: str` |

Voice wrappers truncate output to ~8 items with "and N more".

**Modify [server.py](server.py)**:
- `GET /api/tasks?course=&due_before=&priority=&done=`
- `GET /api/tasks/next?n=5`
- `POST /api/tasks/done` body `{id}`
- `GET /api/courses`
- `GET /api/courses/<course_id>` — objectives + progress

**`config.yaml`**:
```yaml
obsidian:
  vault_path: ""
  daily_notes_folder: ""
  tasks_scan_paths: []          # empty = whole vault
  courses_folder: "Courses"
  assignments_folder: "Assignments"
  lectures_folder: "Lectures"
```

**Vault structure expected** (auto-bootstrap missing folders on first call):
```
Courses/
  cs101/
    index.md            # frontmatter: course_id, learning_objectives, progress_pct
    Assignments/
      hw3.md            # - [ ] read ch4 due:2026-05-12 priority:high
Lectures/
  cs101/
    Slides/
    Notes/
```

**Voice phrases**
- "What's due today?"
- "List my assignments for CS101"
- "What are my top priorities?"
- "Mark linear algebra problem set done"
- "What courses am I taking?"
- "What are the learning objectives for CS101?"

**Acceptance**
- Edit a task in vault → next call reflects within 1s.
- `mark_done` flips the checkbox in the actual file (Obsidian undo restores it).
- Frontmatter parse errors are logged but don't crash the scan.

---

## Sub-phase 6d — Lecture Ingestion

**New file** `lectures.py` (~220 lines)
- `extract_pdf(path)` via `pypdf.PdfReader` (cap 60k chars).
- `extract_pptx(path)` via `python-pptx` — text frames + speaker notes, slide-numbered.
- `extract(path)` dispatches on extension.
- `summarize_lecture(course, slide_path, text)` — Gemini prompt asking for: TL;DR (3 bullets), key concepts (5–10), glossary, study questions (5), suggested flashcards (`Q :: A`). Override `max_output_tokens=1500` per call without mutating shared config.
- `write_lecture_note(course, slide_path, summary_md)` — writes to `<vault>/<lectures_folder>/<course>/Notes/YYYY-MM-DD-<stem>.md` with frontmatter `course_id, slide_path, ingested_at, tags:[lecture, ai-summary]` and a `## Source` wikilink.
- Public: `ingest_lecture(course, slide_path, generate_flashcards=False)` returns `{note_path, slide_path, char_count, summary_excerpt}`.

**Modify [tools.py](tools.py)** — add tool + dispatch:
- `ingest_lecture(course: str, slide_path: str, flashcards?: bool=false)`

**Modify [server.py](server.py)**:
- `POST /api/lectures/ingest` (multipart: `course`, `file`) — saves upload to `<vault>/Lectures/<course>/Slides/`, calls `lectures.ingest_lecture`. Returns `{ok, note_path, summary_excerpt}`.
- `GET /api/lectures/<course>` — list ingested notes.

**`config.yaml`**:
```yaml
lectures:
  generate_flashcards: false
  max_chars: 60000
  summary_model: ""           # empty = use gemini.model
  summary_max_tokens: 1500
```

**`requirements.txt`**: `pypdf`, `python-pptx`.

**Voice phrases**
- "Ingest week 5 lecture for CS101 from Lectures/cs101/Slides/week5-trees.pdf"
- Primary entry is the **UI upload** in the Lectures view; voice triggers `ingest_latest_lecture(course)` (suggested skill — see §6h).

**Acceptance**
- Drop a 20-page PDF → Markdown note created in the right folder with all five sections.
- Source wikilink resolves in Obsidian.

**Sync prerequisite (must be documented)**
AXIOM reads slides from the local vault path. Slides arrive on the local machine via the user's existing vault sync (Obsidian Sync / OneDrive / Syncthing). If sync isn't set up, cross-device slide ingestion won't work.

---

## Sub-phase 6e — NotebookLM Scenario

No new tools. Pure scenario.

**Modify [scenarios.py:_build_context](scenarios.py)** — expose `vault_path` for substitution:
```python
ctx["vault_path"] = self.config.get("obsidian", {}).get("vault_path", "")
```

**`config.yaml`** under `scenarios:`:
```yaml
notebooklm_session:
  description: "Open NotebookLM and stage slides for upload"
  steps:
    - action: ask
      prompt: "Which course are we studying?"
      slot: course
    - action: speak
      text: "Opening NotebookLM and your slides folder for {course}."
    - action: open_website
      target: "https://notebooklm.google.com/"
    - action: run_terminal
      command: 'explorer "{vault_path}/Lectures/{course}/Slides"'
    - action: speak
      text: "Drag the slides you want to study into NotebookLM."
```

**Voice phrase**: "Start a NotebookLM session"

---

## Sub-phase 6f — Dashboard Side Widgets

**New REST endpoint** `GET /api/dashboard` aggregates:
```json
{
  "schedule":   [...3 next events...],
  "todos":      [...top 5 by due date...],
  "assignments":{"course":"cs101","items":[...]},
  "courses":    [{"id":"cs101","objectives":[...],"progress_pct":60}],
  "active_course":"cs101",
  "email":      {"unread_count":3,"last_check_iso":"..."},
  "ts":"2026-05-05T12:34:00"
}
```
Each block wrapped in try/except — partial failures return `null` with an `error` field, never break the response.

**Modify [voice_assistant_ui.html](voice_assistant_ui.html)**

CSS — replace centered `.wrap` rule with a 3-column grid that toggles on the Live tab and collapses on narrow viewports:

```css
body.with-widgets .wrap {
  max-width: 1280px;
  display: grid;
  grid-template-columns: 220px 720px 220px;
  column-gap: 1.25rem;
  align-items: start;
}
body:not(.with-widgets) .wrap { max-width: 720px; }   /* preserve current centered layout */
.side-panel { display:flex; flex-direction:column; gap:1rem; position:sticky; top:1rem; }
.side-panel.left  { grid-column: 1; }
.side-panel.right { grid-column: 3; }
.wrap > .conn-banner,
.wrap > .sysbar,
.wrap > .tabs,
.wrap > .view { grid-column: 2; }
@media (max-width: 1100px) {
  body.with-widgets .wrap { grid-template-columns: 1fr; max-width: 720px; }
  .side-panel { position: static; }
}
.widget {
  background:var(--panel); border:1px solid var(--border2); border-radius:2px;
  padding:.75rem; display:flex; flex-direction:column; gap:.4rem;
}
.widget-head {
  font-family:'Share Tech Mono',monospace; font-size:.62rem;
  letter-spacing:.14em; color:var(--accent); text-transform:uppercase;
  border-bottom:1px solid var(--border); padding-bottom:.3rem;
}
.widget-row { font-size:.78rem; line-height:1.35; display:flex; justify-content:space-between; gap:.5rem; }
.widget-row .meta { font-family:'Share Tech Mono',monospace; font-size:.62rem; color:var(--muted); }
.widget-empty { font-family:'Share Tech Mono',monospace; font-size:.65rem; color:var(--muted); }
.widget.email-badge .count { font-size:1.6rem; color:var(--green); font-family:'Share Tech Mono',monospace; }
```

HTML — inside `.wrap` after `.tabs`:
```html
<aside class="side-panel left">
  <div class="widget" id="w-schedule"></div>
  <div class="widget" id="w-todos"></div>
</aside>
<aside class="side-panel right">
  <div class="widget" id="w-assignments"></div>
  <div class="widget" id="w-objectives"></div>
  <div class="widget email-badge" id="w-email">
    <div class="widget-head">UNREAD</div>
    <div class="count" id="emailCount">0</div>
  </div>
</aside>
```

JS
- `setTab(name)` toggles `body.classList.with-widgets` only when `name === 'live'`.
- `loadDashboard()` fetches `/api/dashboard` and hydrates the five widgets.
- Poll every 60s but only when Live tab is active **and** `document.visibilityState === 'visible'`.
- Re-fetch on socket events `tool` (when name is in `mark_done|create_event|ingest_lecture`) and `config_reloaded`.

**Sci-fi aesthetic preserved**: same color palette (`--panel`, `--border2`, `--accent`, `--green`, `--muted`), Share Tech Mono headings, dark grid background. No new colors introduced.

**Acceptance**
- Live tab → widgets visible left + right of main column at ≥1100px viewport.
- Settings/Projects/Scenarios/History tabs → widgets hidden, layout returns to 720px centered.
- "Mark linear algebra done" → todos widget updates within 1s without page refresh.

---

## Sub-phase 6g — NotebookLM scenario

(Folded into 6e above.)

---

## Sub-phase 6h — Suggested bonus skills

I'd recommend doing these only after 6a–6f are stable. They are small individually and reuse what's been built.

1. **`pomodoro_session(course?, minutes=25)`** — wraps existing `set_timer` + `append_daily_note` to log `- 25m focus on {course}`. Course-tagged sessions roll up into the weekly review. ~30 lines in `tools.py`, no new module.
2. **`generate_flashcards(note_title, count=10)`** — reads a note via `read_note`, asks Gemini for Q/A pairs, writes `<title>-flashcards.md` next to it (Anki-importable `Q :: A` format). Reuses the `lectures.summarize_lecture` plumbing.
3. **`quick_capture(text)`** — appends to `Inbox.md` in vault root with timestamp. ~15 lines. Voice-friendly dump for "I just had an idea". Pairs with weekly review.
4. **`reading_queue(action, url?)`** — `add` / `list` / `mark_done` over `Reading Queue.md` (same checkbox grammar that `tasks_index` already understands). Tags items with `source:youtube|article|paper`.
5. **`weekly_review` scenario** — chains: list completed-this-week, list overdue, list new lecture notes, ask "what's the win?", append summary to `Weekly Reviews/<date>.md`. Mostly YAML + one new `week_summary()` tool.
6. **`ingest_latest_lecture(course)`** — finds newest file in `Lectures/<course>/Slides/`, calls `lectures.ingest_lecture` on it. Bridges the gap that voice can't dictate file paths cleanly.

---

## Auth & privacy summary

| Concern | Boundary |
|---|---|
| Calendar scopes | `calendar.events` (write needed for `create_event`) |
| Gmail scope | `gmail.readonly` only — never `modify`/`send` |
| Token cache | `secrets/google_token.json` (gitignored) |
| Client secrets | `secrets/google_oauth_client.json` (user-supplied via Google Cloud Console) |
| Email cursor | `secrets/last_email_check.json` |
| Body exposure | Snippets ≤80 chars only; full body access gated by explicit voice phrase + per-call confirm |
| Polling | Disabled. Every Gmail/Calendar fetch is user-initiated (voice / dashboard widget refresh / scenario step). Dashboard polls our own aggregator endpoint, not Google. |
| Revocation | `google_auth.revoke()` clears the token (Settings disconnect button later) |

`.gitignore` additions: `secrets/`, `*.token.json`, `last_email_check.json`.

---

## Risks & open questions

- **First-time OAuth in `run.pyw`**: `InstalledAppFlow.run_local_server()` opens a browser; `run.pyw` is windowless. **First Google auth must happen via `python server.py` in console mode.** Document in onboarding.
- **Token refresh failures mid-conversation**: must be silent; on revoke, tool returns "Google access expired — re-authenticate via Settings."
- **Scanned PDFs**: `pypdf` returns empty text. Add `pytesseract` OCR fallback only if user reports issues — not in v1.
- **Gemini token cap**: `lectures.summarize_lecture` overrides `max_output_tokens=1500` per-call without touching shared config.
- **Task ID stability**: edits change the hash. `mark_done` re-hashes incoming IDs and tolerates one retry.
- **Vault structure assumption**: AXIOM auto-bootstraps missing `Courses/`, `Lectures/<course>/Notes/` folders on first relevant call rather than failing.
- **Slide sync**: AXIOM does not sync. Cross-device requires Obsidian Sync / OneDrive / Syncthing on the user's vault.
- **Dashboard polling cost**: 60s × 5 widgets is fine, but pause when tab hidden (`visibilitychange`) and when not on Live tab.
- **Privacy regression**: a future tool change could leak email bodies. Add a unit test that asserts `gmail_client.unread_since_last_check()` items have only the whitelisted keys.

---

## Critical files to modify or create

| File | Type | Sub-phase | Purpose |
|---|---|---|---|
| `google_auth.py` | NEW (~120) | 6a | Shared OAuth helper |
| `google_calendar.py` | NEW (~140) | 6a | Calendar CRUD |
| `gmail_client.py` | NEW (~150) | 6b | Read-only Gmail with cursor |
| `tasks_index.py` | NEW (~280) | 6c | Vault scanner / task+course parser / mtime cache |
| `lectures.py` | NEW (~220) | 6d | PDF/PPTX extract + Gemini summary + writer |
| [tools.py](tools.py) | MODIFY | 6a–6d | Add ~13 tool decls (after the existing block ~line 339), 13 dispatch entries (in lambda map ~line 692), and wrapper functions |
| [server.py](server.py) | MODIFY | 6a–6f | Add ~10 REST routes after line ~180; multipart handling for `/api/lectures/ingest`; new `/api/dashboard` aggregator |
| [scenarios.py](scenarios.py) | MODIFY | 6e | Add `vault_path` to `_build_context` |
| [config.yaml](config.yaml) | MODIFY | all | New `google.*`, `gmail.*`, `lectures.*` sections; expand `obsidian.*`; add `notebooklm_session` scenario |
| [voice_assistant_ui.html](voice_assistant_ui.html) | MODIFY | 6f | 3-col grid CSS, `.side-panel` + `.widget`, HTML for 5 widgets, JS dashboard polling + tab toggle |
| [requirements.txt](requirements.txt) | MODIFY | 6a, 6b, 6d | `google-auth-oauthlib`, `google-api-python-client`, `dateparser`, `pypdf`, `python-pptx` |
| `.gitignore` | MODIFY | 6a, 6b | `secrets/`, `*.token.json`, `last_email_check.json` |

Existing functions to reuse: `tools.create_note`, `tools.read_note`, `tools.append_daily_note`, `tools.search_notes`, `tools.set_timer`, `voice_assistant._send`, `voice_assistant.reload_runtime_config`, `scenarios.ScenarioEngine`, `projects.ProjectRegistry`.

---

## Verification (end-to-end)

| Sub-phase | Voice / action | Expected |
|---|---|---|
| 6a | "What's on today?" | Speaks today's events from Google Calendar |
| 6a | "Add event 'lab' tomorrow 3pm 60 min" | Event appears in Google Calendar web UI |
| 6a | `curl /api/calendar/today` | Returns JSON list |
| 6b | "Any new emails?" | Speaks count + senders+subjects+snippet (no bodies) |
| 6b | Send self a test email, ask again | Count increments by exactly 1 |
| 6b | Inspect any `/api/email/*` response | No `body`/`payload` keys |
| 6c | Add `- [ ] test task due:2026-05-06` to vault, "what's due tomorrow?" | Speaks the task |
| 6c | "Mark test task done" | Checkbox flipped in `.md`; todos widget updates |
| 6c | "List my courses" | Speaks course names |
| 6c | "What are the learning objectives for CS101?" | Speaks LO list |
| 6d | UI upload PDF for cs101 | Note created at `Lectures/cs101/Notes/YYYY-MM-DD-<stem>.md` with TL;DR + study questions |
| 6e | "Start a NotebookLM session" | Asks for course, opens NotebookLM tab + slides folder in Explorer |
| 6f | Switch to Live tab | Widgets visible left/right at ≥1100px |
| 6f | Switch to Settings tab | Widgets hidden; layout returns to 720px centered |
| 6f | "Mark task done" via voice | Todos widget refreshes within 1s |
| 6f | `curl /api/dashboard` | Returns aggregated `{schedule, todos, assignments, courses, email, ...}` |

After 6a–6f land, append a new `## 2026-05-05 — Phase 6: Academic Skills` section to [AXIOM_progress.md](AXIOM_progress.md) using the existing entry style (Goal → Acceptance criteria → Implementation log → Verification → Files touched).

---

## Out of scope for this plan

- Phase 5 Electron packaging (deferred per user direction).
- Custom "Hey Axiom" wake-word training (Phase 3 leftover).
- Browser automation of NotebookLM (rejected; scenario-only integration).
- Background email polling / push notifications (rejected; on-demand only).
- OCR for scanned PDFs (deferred until a real failure case appears).
- Spotify, Home Assistant, code-intelligence tools from the original Phase 6 in `AXIOM_development_plan.md` — those remain queued but are not part of this academic-skills batch.
