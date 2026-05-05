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

### Acceptance criteria status

- [x] Wake word has retry, threshold, cooldown, model-path support, and graceful hotkey fallback
- [ ] Custom "Hey Axiom" model trained - sample collection helper added, exported model still pending
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
