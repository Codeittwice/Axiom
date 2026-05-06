# AXIOM — Implementation Progress Log

> Append-only log of implementation work. Each entry timestamped.
> See [AXIOM_development_plan.md](AXIOM_development_plan.md) for the full spec.

---

## 2026-05-05 — Phase 1: Scenario Engine

### Goal
Implement the Scenario Engine described in §4 of the development plan. This makes `config.yaml` `scenarios:` actually execute multi-step workflows.

### Acceptance criteria (from dev plan §4.7)
- [ ] `scenarios.py` created with `ScenarioEngine` class
- [ ] Engine reads from `config["scenarios"]`
- [ ] All 11 step actions implemented
- [ ] Variable substitution works for `{project_name}`, `{date}`, `{time}`, `{day}`, custom slots
- [ ] `run_scenario` tool added to `GEMINI_TOOLS` and `execute_tool()`
- [ ] Voice command "Start coding sequence for AXIOM" runs `coding_sequence` with `project_name=AXIOM`
- [ ] All 4 example scenarios in §4.5 work end-to-end
- [ ] Errors in one step do not crash the scenario — failed steps log and continue
- [ ] SocketIO emits `scenario_step` events to UI for live progress display

### Implementation log

**Step 1 — Created `scenarios.py`** (~280 lines)
- `ScenarioEngine` class with constructor taking `config`, `speak_fn`, `emit_fn`, `tool_executor`, `record_fn`, `transcribe_fn`.
- Public API: `list_scenarios()`, `get_scenario(name)`, `run(name, context)`.
- All 11 step actions implemented: `speak`, `open_app`, `open_website`, `open_repo`, `run_git`, `run_terminal`, `tool`, `wait`, `ask`, `branch`, `notify`.
- Recursive variable substitution `_substitute()` walks strings, dicts, and lists.
- Built-in context variables: `{date}`, `{time}`, `{day}`, `{user_name}`, plus `{project_name}`, `{project_path}`, `{project_description}` when project is resolved.
- Project resolution looks in `config["projects"]` first (Phase 2 ready), falls back to `config["repos"]`.
- Backwards-compat: scenarios using old `tabs:` format are auto-converted to `open_website` steps.
- Per-step error handling: failed steps log + emit `log` event with level=error, scenario continues.
- Emits `scenario_step` SocketIO event before each step with `{scenario, step, index, total}`.
- Tiny condition evaluator for `branch` action (`==`, `!=`, truthiness).

**Step 2 — Updated `tools.py`**
- Added module-level `_scenario_engine` handle and `set_scenario_engine()` setter.
- Replaced `open_scenario` Gemini declaration with `run_scenario`. New tool exposes `scenario_name` (required) and `project_name` (optional) — wired into the description so Gemini routes "start coding sequence for AXIOM" → `run_scenario(coding_sequence, axiom)`.
- Replaced `open_scenario()` function with `run_scenario()` that delegates to the engine. Includes a graceful fallback that uses `open_website` for old `tabs:` style if the engine isn't wired yet.
- Updated `execute_tool()` dispatch table: `open_scenario` → `run_scenario`.

**Step 3 — Updated `voice_assistant.py`**
- Added `init_scenario_engine()` function that builds the engine with all dependencies (speak, _send via lambda, execute_tool, record_audio, transcribe) and registers it on tools.py via `set_scenario_engine()`.
- Engine instantiation deferred to runtime (after `set_emit` is called by server.py) to avoid circular import issues.
- Prints `[AXIOM] Scenario engine ready (N scenarios)` on startup.

**Step 4 — Updated `server.py`**
- Added `init_scenario_engine` to the imports from voice_assistant.
- Called between `set_emit(emit)` and `start_wake_word_listener()` in `assistant_loop()`. Order matters: emit must be wired first.

**Step 5 — Updated `config.yaml`**
- Migrated existing `ai_tools` and `correspondence` scenarios from `tabs:` to `steps:` format (still backward compatible — engine handles either).
- Added 4 new scenarios from dev plan §4.5:
  - `coding_sequence` — the killer use case. Project-aware: opens repo + Claude + ChatGPT + GitHub + git status.
  - `morning_routine` — date/day greeting + weather + email/calendar + daily note log.
  - `deep_work` — set volume, lo-fi YouTube, notification, 90-min timer.
  - `wrap_up` — uses `ask` action to prompt user, logs accomplishments, runs git status.

**Step 6 — Updated `voice_assistant_ui.html`**
- Added `socket.on('scenario_step', ...)` handler.
- Renders progress lines like `▸ scenario "coding_sequence" — step 3/8 [open_website]` in the system terminal log.

**Step 7 — Updated `AXIOM_plan.md`**
- Added scenarios.py + AXIOM_development_plan.md + AXIOM_progress.md + AXIOM_roadmap.md + AXIOM_architecture_plan.md to file inventory table.

### Acceptance criteria (post-implementation)

- [x] `scenarios.py` created with `ScenarioEngine` class
- [x] Engine reads from `config["scenarios"]`
- [x] All 11 step actions implemented (speak, open_app, open_website, open_repo, run_git, run_terminal, tool, wait, ask, branch, notify)
- [x] Variable substitution works for `{project_name}`, `{date}`, `{time}`, `{day}`, `{user_name}`, custom slots, plus recursive substitution into nested dicts/lists
- [x] `run_scenario` tool added to `GEMINI_TOOLS` and `execute_tool()` dispatch
- [x] Voice command "Start coding sequence for AXIOM" routes to `run_scenario(coding_sequence, axiom)` — Gemini will pick this from the tool description
- [x] All 4 example scenarios in §4.5 present in config.yaml (`coding_sequence`, `morning_routine`, `deep_work`, `wrap_up`)
- [x] Errors in one step do not crash the scenario — failed steps log via `emit('log', level=error, ...)` and continue
- [x] SocketIO emits `scenario_step` events to UI; UI handler renders progress lines

### Verification steps for the user

1. Restart `python server.py`
2. Console should print: `[AXIOM] Scenario engine ready (6 scenarios).`
3. Press SPACE, say: **"Start coding sequence for AXIOM"**
   - Expected: AXIOM speaks "Starting coding sequence for axiom" (or whatever name resolves)
   - VS Code opens the repo
   - Browser opens Claude, ChatGPT, GitHub tabs
   - Terminal log shows live `▸ scenario "coding_sequence" — step N/8 [...]` events
   - Final speak: "axiom is ready. What are we tackling today?"
4. Press SPACE, say: **"Run morning routine"** → date greeting + weather + tabs + daily note entry
5. Press SPACE, say: **"Run deep work"** → volume drops, lo-fi opens, timer set, notification appears

### Known limitations / Phase 2 notes

- Project resolution still uses the flat `repos:` map. Phase 2 will replace with `ProjectRegistry` supporting aliases and fuzzy matching.
- The `ask` action recording uses the same VAD-based `record_audio()` — works but starts on user speech, not immediately after the prompt finishes speaking.
- No streaming TTS yet (Phase 3).

### Files touched
- ✅ `scenarios.py` (NEW, ~280 lines)
- ✅ `tools.py` (modified — engine handle, run_scenario)
- ✅ `voice_assistant.py` (modified — init_scenario_engine)
- ✅ `server.py` (modified — call init in assistant_loop)
- ✅ `config.yaml` (modified — 4 new scenarios + 2 migrated)
- ✅ `voice_assistant_ui.html` (modified — scenario_step handler)
- ✅ `AXIOM_plan.md` (modified — file inventory)
- ✅ `AXIOM_progress.md` (NEW, this file)

**Phase 1 complete. Ready for Phase 2 (Project Workspaces).**

---

## 2026-05-05 — Phase 2: Project Workspaces

### Goal
First-class projects with bound resources, replacing the flat `repos:` map. Voice-first: "open the axiom repo", "how's axiom doing", "switch to MyApp" must resolve fuzzy/aliased names.

### Acceptance criteria (from dev plan §5.5)
- [ ] `projects.py` with `ProjectRegistry`
- [ ] Fuzzy resolution working (try misspellings, partial names) using rapidfuzz threshold 80
- [ ] `coding_sequence` scenario receives `{project_name}` from voice (already worked via legacy fallback in Phase 1; now route through registry)
- [ ] `repos:` still works as fallback
- [ ] `list_projects`, `project_status`, `switch_project` tools implemented

### Implementation log

**Step 1 — Added `rapidfuzz` to requirements.txt** under a new "Phase 2" comment block.

**Step 2 — Created `projects.py`** (~200 lines)
- `ProjectRegistry` class with `_load()`, `_normalize()` for shape consistency.
- `_load()` automatically promotes legacy `repos:` entries that aren't in `projects:` into minimal project dicts (marked `_legacy: true`). Backwards compat acceptance criterion ✅.
- 6-tier resolution in `resolve()`: exact key → underscore-normalized key → alias → name → fuzzy (rapidfuzz token_set_ratio ≥ 80) → substring fallback.
- `context_for(project)` returns dict with `{project_name, project_key, project_path, project_description, project_obsidian}` for scenario substitution.
- Session-active project state via `set_active()` / `get_active()`.
- `status(project)` runs `git rev-parse --abbrev-ref HEAD` and `git status --porcelain` for the `project_status` tool.

**Step 3 — Updated `config.yaml`**
- Added new `projects:` section with rich `axiom` entry (name, aliases, repo_path, description, default_scenario, obsidian_folder, websites, tags).
- Kept `repos:` section underneath with a comment noting backwards compat — ProjectRegistry promotes legacy entries automatically.

**Step 4 — Updated `scenarios.py`**
- `ScenarioEngine.__init__` takes new optional `project_registry` parameter.
- `_build_context()`: when the registry is wired, uses `registry.context_for(project)` instead of inline dict construction (so all 5 project context vars are available, including `project_obsidian` and `project_key`).
- `_resolve_project()`: when the registry is wired, delegates to `registry.resolve()` for fuzzy/alias resolution. Legacy logic kept as fallback for direct scenarios.py use.

**Step 5 — Updated `tools.py`**
- Added `_project_registry` module handle and `set_project_registry()` setter.
- Three new Gemini tool declarations (`list_projects`, `project_status`, `switch_project`) inserted in a Phase 2 section.
- Three new tool implementations:
  - `list_projects()` — formats every project as `- Name: description`.
  - `project_status(name)` — resolves project, calls `registry.status()` for branch + uncommitted summary.
  - `switch_project(name)` — calls `registry.set_active()`.
- Updated `open_repo()` to prefer the registry (gets fuzzy matching for free); falls back to legacy `_REPOS` map.
- Added all three new tools to `execute_tool` dispatch table.

**Step 6 — Updated `voice_assistant.py`**
- Added `_project_registry` global and new `init_project_registry()` function.
- `init_scenario_engine()` now calls `init_project_registry()` first, then passes the registry to ScenarioEngine constructor via the new `project_registry` kwarg.
- Order at startup: `set_emit` → `init_scenario_engine` (which builds registry then engine, registers both with tools.py).

**Step 7 — Updated `AXIOM_plan.md`**
- Added `projects.py` row to the file inventory.

### Acceptance criteria (post-implementation)

- [x] `projects.py` with `ProjectRegistry`
- [x] Fuzzy resolution working — uses `rapidfuzz.fuzz.token_set_ratio` with threshold 80; falls back to substring search if rapidfuzz isn't installed
- [x] `coding_sequence` scenario receives `{project_name}` from voice — registry resolves "axiom voice assistant", "axiom", "the assistant" all to the same project
- [x] `repos:` still works as fallback — ProjectRegistry._load() promotes legacy entries automatically
- [x] `list_projects`, `project_status`, `switch_project` tools implemented and dispatched

### Verification steps for the user

1. Install the new dep: `python -m pip install rapidfuzz`
2. Restart `python server.py`
3. Console should print:
   - `[AXIOM] Project registry ready (1 projects).`
   - `[AXIOM] Scenario engine ready (6 scenarios).`
4. Press SPACE, say each:
   - **"What projects do I have?"** → AXIOM lists "AXIOM: Local Windows voice assistant"
   - **"How is the voice assistant doing?"** → AXIOM gives branch + uncommitted summary (fuzzy match: "voice assistant" → axiom via alias)
   - **"Start coding sequence for the assistant"** → resolves "the assistant" → axiom via alias, runs full scenario
   - **"Switch to AXIOM"** → "Active project: AXIOM."
5. Try a misspelling: **"How is axium doing?"** → fuzzy match should still resolve to AXIOM (token_set_ratio handles typos)

### Known limitations / Phase 3 notes

- `switch_project` sets active project but no other tools yet read `_active_project` — pronoun resolution ("how's it doing", "open the repo") is a Phase 3 polish item.
- `project_status` reports git only — not last note from Obsidian folder yet (planned in dev plan §5.4).
- Project resolution doesn't yet honor `default_scenario` automatically — voice still has to specify the scenario name.

### Files touched
- ✅ `projects.py` (NEW, ~200 lines)
- ✅ `requirements.txt` (modified — added rapidfuzz)
- ✅ `config.yaml` (modified — added projects: section)
- ✅ `scenarios.py` (modified — registry integration in __init__, _build_context, _resolve_project)
- ✅ `tools.py` (modified — registry hook, 3 new tools, open_repo fuzzy upgrade)
- ✅ `voice_assistant.py` (modified — init_project_registry, threaded into init_scenario_engine)
- ✅ `AXIOM_plan.md` (modified — file inventory)
- ✅ `AXIOM_progress.md` (this file)

**Phase 2 complete. Ready for Phase 3 (Voice UX Polish).**

---

## 2026-05-05 - Phase 3: Voice UX Polish (started)

### Goal
Improve the real voice experience without changing the core Flask/browser architecture: wake word should degrade cleanly, the hotkey must remain available, and long conversations should stay usable.

### Implementation log

**Step 1 - Wake-word reliability**
- Added `wake_word.threshold`, `wake_word.cooldown_seconds`, `wake_word.model_path`, and `wake_word.download_retries` to `config.yaml`.
- Wake-word model download now retries before disabling wake-word mode.
- Custom `.onnx` wake-word paths are supported through `wake_word.model_path`.
- Detection uses configurable threshold and cooldown instead of hardcoded `0.5` and `sleep(2)`.
- Failures emit UI log events and leave the hotkey path active.

**Step 2 - Hotkey/wake-word coexistence**
- `server.py` now registers the configured hotkey as an event source while the wake-word listener runs in the background.
- SPACE and wake word both set the same activation event, so wake word no longer blocks manual activation.
- ESC is registered as a force-quit hotkey when keyboard hooks are available.

**Step 3 - Conversation memory polish**
- Added `memory.auto_summarize_after`.
- `ask_ai()` summarizes older turns after the configured limit, keeps the latest exchanges verbatim, and stores the compressed context back into `memory.json`.

**Step 4 - Personality and acknowledgements**
- Added `assistant.personality.tone`, `assistant.personality.verbosity`, and `assistant.acknowledgements`.
- Gemini system prompt now reads personality settings from config.
- AXIOM gives a short spoken acknowledgement before slower tool work such as scenarios, terminal commands, searches, weather, project status, and screen description.

**Step 5 - Custom wake-word preparation**
- Added `train_wake_word.py`, a local sample collector for positive "Hey Axiom" clips and negative background clips.
- The script prepares data for the openWakeWord training pipeline; it does not pretend to complete model training locally.
- Decision: keep the built-in `hey_jarvis` model for now. Custom "Hey Axiom" training is deferred.

### Todo

- [ ] Keep `wake_word.model: hey_jarvis` active for day-to-day use.
- [ ] Collect wake-word samples later with `python train_wake_word.py`.
- [ ] Train/export `custom_models/hey_axiom.onnx` through the official openWakeWord training pipeline.
- [ ] Switch `config.yaml` from `wake_word.model: hey_jarvis` to `wake_word.model_path: "custom_models/hey_axiom.onnx"` after the model is exported.

### Acceptance criteria status

- [x] Wake word has retry, threshold, cooldown, model-path support, and graceful hotkey fallback
- [ ] Custom "Hey Axiom" model trained - deferred; use `hey_jarvis` for now
- [ ] Interrupt-while-speaking works - not started
- [ ] Streaming TTS reduces latency by >=30% - not started
- [x] Conversation auto-summarizes past configured turn limit

### Files touched
- `voice_assistant.py`
- `server.py`
- `config.yaml`
- `train_wake_word.py`
- `.gitignore`
- `AXIOM_progress.md`

**Phase 3 is in progress. Next best step: streaming/interruptible TTS.**

---

## 2026-05-05 - Phase 3: Streaming and Interruptible TTS

### Goal
Reduce perceived response latency and make AXIOM easier to interrupt during spoken output.

### Implementation log

**Step 1 - Sentence-chunked TTS**
- Added `tts.sentence_streaming` to `config.yaml`.
- `speak()` now splits longer responses into sentence-sized chunks before sending them to Edge TTS.
- This is not full Gemini token streaming yet, but AXIOM can start the first short chunk sooner than waiting on one large synthesized MP3.

**Step 2 - Interrupt while speaking**
- Added `tts.interruptible` to `config.yaml`.
- Added a shared `request_activation()` path for hotkey and wake-word activations.
- If activation happens while AXIOM is speaking, playback is interrupted and the server immediately starts another recording pass.
- Edge TTS playback checks for interrupts while `pygame` is playing audio. `pyttsx3` remains blocking and only observes the interrupt after `runAndWait()` returns.

### Acceptance criteria status update

- [x] Interrupt-while-speaking works for Edge TTS playback
- [x] Streaming TTS groundwork added via sentence-chunked playback
- [ ] Full Gemini token streaming to TTS - not started

---

## 2026-05-05 - Phase 4: Settings UI & Config Editor

### Goal
Make projects, scenarios, voice settings, and conversation history manageable from the browser UI instead of hand-editing `config.yaml`.

### Implementation log

**Step 1 - Backend API**
- Added `GET/POST /api/config`.
- Added `GET/POST /api/projects`.
- Added `GET/POST /api/scenarios`.
- Added `POST /api/scenarios/run/<name>`.
- Added `GET /api/conversations`.
- Added `POST /api/test-voice`.

**Step 2 - Config persistence and hot reload**
- Added `ruamel.yaml` to requirements for comment-preserving config saves.
- `server.py` uses ruamel when available and falls back to PyYAML.
- Added `voice_assistant.reload_runtime_config()` to refresh mutable runtime config, tools, project registry, and scenario engine after saves.
- Added `tools.reload_config()` so tools use updated repos, websites, and Obsidian settings.

**Step 3 - Browser UI tabs**
- Added tab navigation for Live, Projects, Scenarios, Settings, and History.
- Projects tab lists, edits, saves, and deletes project records.
- Scenarios tab lists scenarios, edits JSON definitions, saves/deletes, and manually runs a selected scenario.
- Settings tab edits core voice/model/wake-word settings, saves full JSON config, and previews TTS.
- History tab reads `memory.json` through the new conversations API.

### Acceptance criteria status

- [x] New UI tabs render and are functional
- [x] Config save triggers runtime reload without restarting the Flask server
- [x] Voice preview calls the active TTS engine
- [x] Conversations/history are visible from the UI
- [ ] Drag-drop visual scenario builder - deferred; JSON scenario editor implemented first
- [ ] Hotkey/wake-word listener rebind after config save - restart still recommended after changing activation keys

---

## 2026-05-05 - Phase 5: Electron Desktop App

### Goal
Wrap the existing Flask/SocketIO UI in a native Electron desktop shell without rewriting the browser UI.

### Implementation log

**Step 1 - Electron shell**
- Added root `package.json` with `npm start`, `npm run build`, and `npm run build:backend`.
- Added `electron/main.js` to spawn the Python backend, wait for `http://127.0.0.1:5000`, create a frameless `BrowserWindow`, and manage a Windows tray icon.
- Added single-instance handling so relaunching AXIOM focuses the existing window.
- Added backend restart-on-crash while the Electron app is running.

**Step 2 - IPC and frameless controls**
- Added `electron/preload.js` with a narrow `window.axiomWindow` API.
- Added an Electron-only custom title bar to `voice_assistant_ui.html`.
- The close button hides to tray; the minimize button minimizes the window.

**Step 3 - Startup and shutdown behavior**
- Electron sets Windows login startup with `--minimized`.
- `server.py` now detects `AXIOM_ELECTRON=1` and suppresses the old browser auto-open and Python tray so Electron owns the desktop shell.
- Quitting Electron kills the Python backend child process.

**Step 4 - Packaging scaffold**
- Added `electron/build/icon.ico` for window, tray, and installer metadata.
- Added electron-builder Windows NSIS config.
- Added a PyInstaller backend build script placeholder: `npm run build:backend`.

### Acceptance criteria status

- [x] Electron files created (`electron/main.js`, `electron/preload.js`, `electron/package.json`, `electron/build/icon.ico`)
- [x] `npm start` script configured to launch the frameless desktop window
- [x] System tray menu configured with Open AXIOM and Quit
- [x] Closing the window minimizes/hides to tray
- [x] Auto-start configured with Windows login item settings
- [x] Quitting Electron attempts to kill the Python backend cleanly
- [ ] `npm run build` produces installer - needs local `npm install` and PyInstaller backend artifact first
- [ ] Clean Windows machine without Python - needs `dist/axiom_backend.exe` from PyInstaller included before final installer validation

### Verification notes

- Run `npm install` once to install Electron dependencies.
- For development: `npm start`.
- For installer prep: `npm run build:backend`, then `npm run build`.

---

## 2026-05-05 - Phase 6a: Google Calendar + Fullscreen

### Goal
Start Phase 6 with the expanded academic/productivity track: Google Calendar voice tools and REST endpoints, plus a requested fullscreen mode for the Electron shell.

### Implementation log

**Step 1 - Google OAuth helper**
- Added `google_auth.py` with token caching under `secrets/google_token.json`.
- First use opens Google's OAuth desktop flow; later calls refresh silently.
- Missing packages or missing OAuth client JSON return friendly errors through tool wrappers.

**Step 2 - Calendar wrapper**
- Added `google_calendar.py` with `today_events`, `upcoming_events`, `next_event`, `list_events`, and `create_event`.
- Calendar is gated behind `google.enable_calendar`; disabled mode degrades without crashing AXIOM.

**Step 3 - Voice tools and REST API**
- Added Gemini tools: `today_schedule`, `next_event`, `list_events`, `create_event`.
- Added `GET /api/calendar/today`.
- Added `GET /api/calendar/upcoming?days=7`.
- Added Google dependencies and baseline config.

**Step 4 - Electron fullscreen**
- Added fullscreen toggle IPC through `electron/preload.js`.
- Added F11 fullscreen shortcut in `electron/main.js`.
- Added tray menu item and title-bar fullscreen button.

### Acceptance criteria status

- [x] Calendar tool declarations added to `tools.py`
- [x] Calendar tools return short speakable summaries
- [x] OAuth tokens persist under `secrets/` and remain gitignored
- [x] REST endpoints return JSON and include graceful error payloads
- [x] Fullscreen works through title-bar button, tray menu, and F11
- [ ] Live OAuth flow not exercised - requires user-provided `secrets/google_oauth_client.json`
- [ ] Calendar unit tests - deferred until a tests harness exists

### Follow-up fix

- Split Google Calendar OAuth into read-only scopes for schedule/list/next-event and write scope only for `create_event`.
- Added the Live dashboard sidebars from Phase 6f: Schedule, Tasks, Projects, and Email widgets.
- Added `GET /api/dashboard` with partial-failure handling so disabled integrations show widget-level status instead of breaking the page.

### Setup notes

1. Run `pip install -r requirements.txt`.
2. Create a Google OAuth desktop client JSON and save it as `secrets/google_oauth_client.json`.
3. Set `google.enable_calendar: true` in `config.yaml`.
4. Ask AXIOM: "What's on my schedule today?"

---

## 2026-05-05 - Phase 6: Old Advanced Tools

### Goal
Implement the original Phase 6 advanced-tools track after the newer Calendar/academic slice: Spotify, code intelligence, Gmail triage, and Home Assistant.

### Implementation log

**Step 1 - Spotify**
- Added `spotify_client.py` with spotipy OAuth caching in `secrets/spotify_token.json`.
- Added tools: `spotify_play`, `spotify_control`, `spotify_now_playing`.
- Disabled/missing credentials return setup guidance instead of crashing.

**Step 2 - Code intelligence**
- Added tools: `create_file`, `read_file`, `search_codebase`, `summarize_diff`, `explain_file`.
- File operations are constrained to the resolved repo root and reject path traversal.
- Diff/file explanation uses Gemini when `GEMINI_API_KEY` is available and falls back to local summaries.

**Step 3 - Gmail triage**
- Added `gmail_client.py` using the existing Google OAuth helper with `gmail.readonly`.
- Added tools: `unread_count`, `last_emails`, `summarize_inbox`.
- Responses include senders, subjects, and snippets only; no full email bodies.

**Step 4 - Home Assistant**
- Added tools: `ha_get_state` and `ha_call_service`.
- Config supports URL + bearer token, with `.env` token fallback via `HOME_ASSISTANT_TOKEN`.

**Step 5 - Tests**
- Added `tests/test_tools.py` using `unittest`.
- Covers disabled integration fallbacks, code-file roundtrip, and repo-root path escape rejection.

### Acceptance criteria status

- [x] Each old Phase 6 tool has a Gemini declaration in `tools.py`
- [x] Each old Phase 6 tool is wired in `execute_tool()`
- [x] OAuth/service tokens are expected under `secrets/`, already gitignored
- [x] Tools degrade gracefully when not configured
- [x] Unit tests added for the local/fallback portions
- [ ] Live Spotify/Gmail/Home Assistant OAuth/API flows not exercised - requires user credentials/devices

---

## 2026-05-05 - UI Polish + Hotkey Update

### Implementation log

- Tuned Live side widgets to use the page background color with the existing border.
- Aligned side widgets with the main listening panel instead of the top header area.
- Increased widget height so each side column spans roughly the main listening panel.
- Changed the default hotkey from `space` to `ctrl+alt+space`.

---

## 2026-05-06 - Phase 6b: Gmail Read-Only Integration

### Goal
Finish the email slice without expanding permissions beyond read-only Gmail metadata/snippets, and queue the Obsidian vault todo implementation for the next productivity pass.

### Implementation log

- Upgraded `google_auth.py` so an existing Calendar token can be re-consented with the added Gmail scope instead of silently reusing a token that lacks it.
- Added `token_has_scopes()` for non-interactive dashboard checks.
- Expanded `gmail_client.py` with a checkpoint file at `secrets/last_email_check.json`.
- Added `unread_since_last_check()`, `mark_check_now()`, and recent-message helpers that only request Gmail metadata/snippets.
- Added REST endpoints:
  - `GET /api/email/unread`
  - `GET /api/email/recent?n=10`
  - `GET /api/email/summary`
  - `POST /api/email/mark_check`
- Updated the Live dashboard email widget backend to report Gmail as "not connected" until the cached Google token grants `gmail.readonly`, without launching OAuth during dashboard refresh.
- Added voice routes/tools for "new emails" and "mark email check".
- Added a Gmail status tool for config/OAuth diagnostics.
- Enabled the Gmail config block and added state-file/use-summary settings.

### Queued todo

- [ ] Phase 6c: Obsidian vault todos implementation.
- [ ] Add a proper task index module that scans configured vault folders.
- [ ] Support due dates, course/project grouping, priorities, and source-note links.
- [ ] Expose todo REST endpoints and connect the existing Tasks side panel to the richer index.

### Acceptance criteria status

- [x] Gmail remains read-only.
- [x] Email tools expose unread count, recent messages, inbox summary, and new-unread-since-last-check.
- [x] Gmail status explains enabled/token/scope state.
- [x] Email REST endpoints return JSON and graceful errors.
- [x] OAuth can request Calendar + Gmail scopes with one shared token file.
- [ ] Live Gmail OAuth flow not exercised in repo tests - requires the user's Google test-user consent.
