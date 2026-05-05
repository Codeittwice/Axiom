# AXIOM — Development Plan
> Master specification for evolving AXIOM from a working prototype into a polished personal voice assistant.
> This document is the single source of truth for AI coding agents (Claude Code, Codex) implementing the roadmap.
> Read [AXIOM_plan.md](AXIOM_plan.md) first for current state, then this for forward direction.

---

## Table of Contents
1. [Vision & Target State](#1-vision--target-state)
2. [Current State Snapshot](#2-current-state-snapshot)
3. [Core Concepts](#3-core-concepts)
4. [Phase 1: Scenario Engine](#4-phase-1-scenario-engine) ⭐ Killer feature
5. [Phase 2: Project Workspaces](#5-phase-2-project-workspaces)
6. [Phase 3: Voice UX Polish](#6-phase-3-voice-ux-polish)
7. [Phase 4: Settings UI & Config Editor](#7-phase-4-settings-ui--config-editor)
8. [Phase 5: Electron Desktop App](#8-phase-5-electron-desktop-app)
9. [Phase 6: Advanced Tools](#9-phase-6-advanced-tools)
10. [Phase 7: Reliability & Polish](#10-phase-7-reliability--polish)
11. [Full Configuration Reference](#11-full-configuration-reference)
12. [Voice Command Patterns](#12-voice-command-patterns)
13. [Testing & Acceptance](#13-testing--acceptance)
14. [Target File Structure](#14-target-file-structure)
15. [Coding Conventions](#15-coding-conventions)

---

## 1. Vision & Target State

**AXIOM is a polished local Windows voice assistant** that feels like a native desktop app and acts as a personal coding/productivity copilot.

### Killer use case
> "Hey Axiom — start coding sequence for AXIOM."

→ AXIOM resolves the project, opens the repo in VS Code, opens Claude.ai + ChatGPT + GitHub in the browser, runs `git status`, speaks back the branch + uncommitted changes, and waits.

### Quality bar
- Always-on wake word ("Hey Axiom")
- Sub-2-second latency from end-of-speech to first audio response
- Zero UI rewrite when packaged — same HTML stays
- One-click `.exe` installer
- Survives restarts: persistent memory, autostart with Windows
- Graceful degradation: every tool fails to a spoken error, never a crash

### Non-goals (out of scope)
- Mobile app
- Multi-user / cloud sync
- Replacing Claude.ai chat — AXIOM is the **launcher and orchestrator**, not the IDE

---

## 2. Current State Snapshot

| Component | Status |
|---|---|
| STT — Whisper local | ✅ Working |
| LLM — Gemini 2.5 Flash with tool use | ✅ Working |
| TTS — edge-tts (male voice: AndrewNeural) | ✅ Working |
| Hotkey activation (SPACE) | ✅ Working |
| Wake word (openwakeword, hey_jarvis) | 🟡 Wired but model download fragile |
| Tools (~19) — search, weather, Wikipedia, Obsidian, git, terminal, volume, timer, clipboard, vision | ✅ Implemented |
| `repos`, `websites`, `scenarios` config | 🟡 Defined in YAML but **scenarios are NOT executed by an engine** |
| Browser UI with live SocketIO | ✅ Working |
| Persistent memory across sessions | ✅ Working |
| Electron / native packaging | ❌ Not started |
| Settings UI in browser | ❌ Not started |

**The biggest gap right now:** `config.yaml` defines `scenarios:` with steps, but `tools.py:open_scenario()` only calls `open_website()` for each tab. There is no engine that interprets multi-step actions. **Phase 1 fixes this.**

---

## 3. Core Concepts

These are the abstractions AXIOM uses internally. AI agents implementing features must respect these boundaries.

### 3.1 Tool
A single atomic action callable by Gemini via function calling. Already implemented (see [tools.py](tools.py)). Tools take a dict of inputs and return a string result.

### 3.2 Scenario
A **named, ordered list of steps** that performs a multi-action workflow. Each step is itself a tool call or a primitive (speak, wait, ask). Lives in `config.yaml` under `scenarios:`.

### 3.3 Project
A **named workspace** binding together: a repo path, related URLs, default scenario, Obsidian folder, and metadata. Lives in `config.yaml` under `projects:`. Replaces and supersedes the current `repos:` map.

### 3.4 Context
A dict passed through scenario execution carrying variables like `{project_name}`, `{project_path}`, `{date}`, user-provided slots. Used for variable substitution in step text.

### 3.5 Conversation
The user/AI exchange. Already persisted to `memory.json`. Will be extended with **per-project conversation lanes** in Phase 2.

---

## 4. Phase 1: Scenario Engine ⭐

**Goal:** Make `config.yaml` scenarios actually execute multi-step workflows.

### 4.1 Why this is first
Everything else (projects, voice routing, settings UI) depends on a working engine.

### 4.2 New file: `scenarios.py`

```python
"""
AXIOM Scenario Engine — executes multi-step workflows defined in config.yaml.

A scenario is a named ordered list of steps. Each step has an `action` and
parameters. Steps support variable substitution from a context dict.
"""

from typing import Callable, Optional

class ScenarioEngine:
    def __init__(self, config: dict, tool_executor: Callable, speak_fn: Callable, emit_fn: Callable):
        ...

    def list_scenarios(self) -> list[str]: ...

    def run(self, name: str, context: dict | None = None) -> str:
        """Run a scenario. Returns a summary string suitable for speaking."""
        ...

    def _execute_step(self, step: dict, context: dict) -> str: ...

    def _substitute(self, text: str, context: dict) -> str:
        """Replace {var} placeholders from context."""
        ...
```

### 4.3 Step actions to support

| `action` | Required keys | Optional keys | Behavior |
|---|---|---|---|
| `speak` | `text` | — | Speak the (substituted) text aloud |
| `open_app` | `app` | — | Calls `open_application` tool |
| `open_website` | `target` | — | Calls `open_website` tool (resolves shortcuts) |
| `open_repo` | `repo` | — | Calls `open_repo` tool |
| `run_git` | `command` | `repo` | Calls `run_git` tool |
| `run_terminal` | `command` | `repo`, `wait_for_exit` (bool) | Calls `run_terminal` tool |
| `tool` | `name`, `inputs` | — | Generic call to any tool in `execute_tool()` |
| `wait` | `seconds` | — | Sleep N seconds before next step |
| `ask` | `prompt`, `slot` | — | Speak prompt, record user answer, store in `context[slot]` |
| `branch` | `if`, `then`, `else` | — | Conditional execution (e.g., `if: "{has_changes} == true"`) |
| `notify` | `title`, `message` | — | Windows notification via `plyer` |

### 4.4 Variable substitution

Substitute `{var}` anywhere in step strings. Built-in context variables:
- `{project_name}` — name from voice command
- `{project_path}` — resolved repo path
- `{project_description}` — project description
- `{date}` — `2026-05-05`
- `{time}` — `14:32`
- `{day}` — `Tuesday`
- `{user_name}` — from config
- Any custom slot filled by `ask` action

### 4.5 Example scenarios (final config.yaml)

```yaml
scenarios:
  coding_sequence:
    description: "Start a coding session for a project"
    requires_project: true
    steps:
      - action: speak
        text: "Starting coding sequence for {project_name}."
      - action: open_repo
        repo: "{project_name}"
      - action: wait
        seconds: 1
      - action: open_website
        target: claude
      - action: open_website
        target: chatgpt
      - action: open_website
        target: github
      - action: run_git
        command: "status --short"
        repo: "{project_name}"
      - action: speak
        text: "{project_name} is ready. Anything specific you want to tackle?"

  morning_routine:
    description: "Daily startup workflow"
    steps:
      - action: speak
        text: "Good morning. Today is {day}, {date}."
      - action: tool
        name: get_weather
        inputs:
          location: "Sofia"
      - action: open_website
        target: email
      - action: open_website
        target: calendar
      - action: tool
        name: append_daily_note
        inputs:
          content: "Started the day at {time}."

  deep_work:
    description: "Enter focus mode"
    steps:
      - action: tool
        name: set_volume
        inputs:
          level: 30
      - action: open_website
        target: "https://www.youtube.com/watch?v=jfKfPfyJRdk"  # lofi
      - action: notify
        title: "AXIOM"
        message: "Deep work mode active. 90 minute timer set."
      - action: tool
        name: set_timer
        inputs:
          minutes: 90
          label: "Deep Work"
      - action: speak
        text: "Deep work mode. Ninety minutes. Go."

  wrap_up:
    description: "End of day shutdown"
    steps:
      - action: ask
        prompt: "What did you accomplish today?"
        slot: accomplishments
      - action: tool
        name: append_daily_note
        inputs:
          content: "End of day: {accomplishments}"
      - action: run_git
        command: "status"
      - action: speak
        text: "Logged. See you tomorrow."
```

### 4.6 Voice routing changes

Add a new tool `run_scenario` (replaces / extends current `open_scenario`):

```python
{
    "name": "run_scenario",
    "description": "Run a multi-step workflow scenario by name. Examples: 'start coding sequence', 'run morning routine', 'wrap up'.",
    "parameters": {
        "type": "object",
        "properties": {
            "scenario_name": {"type": "string"},
            "project_name":  {"type": "string", "description": "Optional project name if scenario requires it"}
        },
        "required": ["scenario_name"]
    }
}
```

Gemini will pick this when the user says any phrase mapping to a scenario.

### 4.7 Acceptance criteria for Phase 1

- [ ] `scenarios.py` created with `ScenarioEngine` class
- [ ] Engine reads from `config["scenarios"]`
- [ ] All 11 step actions implemented
- [ ] Variable substitution works for `{project_name}`, `{date}`, `{time}`, `{day}`, custom slots
- [ ] `run_scenario` tool added to `GEMINI_TOOLS` and `execute_tool()`
- [ ] Voice command "Start coding sequence for AXIOM" runs `coding_sequence` with `project_name=AXIOM`
- [ ] All 4 example scenarios in §4.5 work end-to-end
- [ ] Errors in one step do not crash the scenario — failed steps log and continue
- [ ] SocketIO emits `scenario_step` events to UI for live progress display

---

## 5. Phase 2: Project Workspaces

**Goal:** First-class projects with bound resources, replacing the flat `repos:` map.

### 5.1 New schema

```yaml
projects:
  axiom:
    name: "AXIOM"
    aliases: ["axiom voice assistant", "voice assistant", "the assistant"]
    repo_path: "E:/_DEV/Personal Voice Assistant"
    description: "Local Windows voice assistant"
    default_scenario: coding_sequence
    obsidian_folder: "Projects/AXIOM"
    websites:
      - https://github.com/USERNAME/axiom
      - claude
    tags: [voice, ai, python]

  myapp:
    name: "MyApp"
    aliases: ["my app", "the app"]
    repo_path: "E:/_DEV/MyApp"
    default_scenario: coding_sequence
```

### 5.2 New file: `projects.py`

```python
"""
AXIOM Projects — workspace registry and voice resolution.
"""

class ProjectRegistry:
    def __init__(self, config: dict): ...

    def list_projects(self) -> list[dict]: ...

    def resolve(self, voice_input: str) -> dict | None:
        """
        Match voice input to a project using:
          1. Exact key match (case-insensitive)
          2. Alias match
          3. Fuzzy match on name (rapidfuzz, threshold 80)
        Returns the project dict or None.
        """
        ...

    def context_for(self, project: dict) -> dict:
        """Build a substitution context dict from a project."""
        ...
```

### 5.3 Backwards compatibility

Keep `repos:` working for one release:
- If a project key isn't found in `projects:`, fall back to `repos:`
- Log a deprecation warning
- Document migration in plan

### 5.4 New tools

| Tool | Purpose |
|---|---|
| `list_projects` | "What projects do I have?" |
| `project_status` | "How's AXIOM doing?" — git status + last note + uncommitted files |
| `switch_project` | Sets active project for this session — affects pronouns ("it", "the repo") |

### 5.5 Acceptance criteria

- [ ] `projects.py` with `ProjectRegistry`
- [ ] Fuzzy resolution working (try misspellings, partial names)
- [ ] `coding_sequence` scenario receives `{project_name}` from voice
- [ ] `repos:` still works as fallback
- [ ] `list_projects`, `project_status`, `switch_project` tools implemented

---

## 6. Phase 3: Voice UX Polish

### 6.1 Wake word reliability

Issues to fix:
- Model download must succeed before first use
- Wake word listener must coexist with hotkey (not block it)
- False positives must be rare

Implementation:
1. On startup, run `openwakeword.utils.download_models()` in a background thread with retry
2. If download fails 3×, log and disable wake word, fall back to hotkey only
3. Add `wake_word.threshold` to config (default 0.5)
4. Add `wake_word.cooldown` — minimum seconds between activations (default 3)

### 6.2 Custom "Hey Axiom" model

The default `hey_jarvis` model is wrong for the brand. Options:
- **A:** Stick with `hey_mycroft` or `alexa` as a closer free option
- **B:** Train a custom "Hey Axiom" model

**Plan B — training script:** create `train_wake_word.py` that:
1. Records 30+ samples of user saying "Hey Axiom"
2. Records negative samples (silence, background)
3. Uses `openwakeword`'s training pipeline
4. Exports `hey_axiom.onnx` to a custom path
5. Config: `wake_word.model_path: "./custom_models/hey_axiom.onnx"`

### 6.3 Conversation enhancements

| Feature | Description |
|---|---|
| Interrupt-while-speaking | Detect user voice during TTS playback, cut off, listen |
| Streaming TTS | Play audio chunks as Gemini streams text (use `edge-tts.stream()`) |
| Conversation summaries | After 20 turns, summarize and replace history to control cost |
| Personality config | `personality.tone: professional/casual/snarky` |
| Acknowledgments | Brief "mhm", "got it" before slow tool calls |

### 6.4 Multi-turn slot filling

When info missing, AXIOM asks instead of guessing:
> User: "Set a timer."
> AXIOM: "How long?"
> User: "25 minutes."
> AXIOM: *sets timer*

Implementation: when Gemini responds with a clarifying question, mark conversation as "awaiting slot fill" — next utterance is routed back to the same tool call.

### 6.5 Acceptance criteria

- [ ] Wake word survives restarts and network blips
- [ ] Custom "Hey Axiom" trained or alternative chosen
- [ ] Interrupt-while-speaking works
- [ ] Streaming TTS reduces latency by ≥30%
- [ ] Conversation auto-summarizes past 20 turns

---

## 7. Phase 4: Settings UI & Config Editor

**Goal:** Edit projects, scenarios, and settings from the UI without touching `config.yaml`.

### 7.1 New routes in `server.py`

```python
@app.route("/api/config",       methods=["GET"])           # full config JSON
@app.route("/api/config",       methods=["POST"])          # save full config
@app.route("/api/projects",     methods=["GET", "POST"])
@app.route("/api/scenarios",    methods=["GET", "POST"])
@app.route("/api/scenarios/run/<name>", methods=["POST"])  # manual trigger
@app.route("/api/conversations", methods=["GET"])          # paginated history
@app.route("/api/test-voice",   methods=["POST"])          # speak({text})
```

### 7.2 New UI views

Add a tab navigation to `voice_assistant_ui.html`:

| Tab | Contents |
|---|---|
| **Live** (default) | Current viz panel + terminal log |
| **Projects** | List, add, edit, delete projects |
| **Scenarios** | Visual scenario editor (drag-drop steps) |
| **Settings** | Voice (TTS voice picker), wake word config, API keys, theme |
| **History** | Past conversations, searchable, exportable |

Keep the futuristic aesthetic (dark theme, monospace, grid). Use the same color palette as the current panel.

### 7.3 Config persistence

Round-trip safe: load → edit → save preserves comments and structure. Use `ruamel.yaml` instead of `pyyaml` to preserve formatting.

```python
from ruamel.yaml import YAML
yaml = YAML()
yaml.preserve_quotes = True
```

### 7.4 Live reload

After saving config, hot-reload the engine without restarting the server:

```python
def reload_config():
    global CFG, _project_registry, _scenario_engine
    with open("config.yaml") as f:
        CFG = yaml.safe_load(f)
    _project_registry = ProjectRegistry(CFG)
    _scenario_engine  = ScenarioEngine(CFG, ...)
    socketio.emit("config_reloaded", {})
```

### 7.5 Acceptance criteria

- [ ] All 4 new tabs render and are functional
- [ ] Save → reload preserves YAML formatting and comments
- [ ] Hot-reload works without losing conversation history
- [ ] Voice picker actually previews the voice
- [ ] Scenario editor can create a working scenario from scratch

---

## 8. Phase 5: Electron Desktop App

See [AXIOM_architecture_plan.md](AXIOM_architecture_plan.md) for the rationale. This phase implements it.

### 8.1 New directory: `electron/`

```
electron/
  main.js        ← main process: spawns Python, creates window, tray
  preload.js     ← IPC bridge
  package.json   ← npm + electron-builder config
  build/
    icon.ico     ← 256×256 AXIOM tray + window icon
```

### 8.2 `main.js` skeleton

```javascript
const { app, BrowserWindow, Tray, Menu, nativeImage } = require('electron');
const { spawn }  = require('child_process');
const path       = require('path');
const http       = require('http');

let pythonProc, mainWindow, tray;

function startPython() {
  pythonProc = spawn('python', ['server.py'], {
    cwd: path.join(__dirname, '..'),
    detached: false,
  });
  pythonProc.stdout.on('data', d => console.log(`[py] ${d}`));
  pythonProc.stderr.on('data', d => console.error(`[py-err] ${d}`));
}

function waitForServer(port, cb) {
  const ping = () => http.get(`http://127.0.0.1:${port}`, () => cb()).on('error', () => setTimeout(ping, 200));
  ping();
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 800, height: 1000,
    frame: false,                      // custom title bar
    backgroundColor: '#03050e',
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
    icon: path.join(__dirname, 'build', 'icon.ico'),
  });
  mainWindow.loadURL('http://127.0.0.1:5000');
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(path.join(__dirname, 'build', 'icon.ico')));
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open AXIOM', click: () => mainWindow.show() },
    { label: 'Quit', click: () => app.quit() },
  ]));
  tray.on('double-click', () => mainWindow.show());
}

app.whenReady().then(() => {
  startPython();
  waitForServer(5000, () => { createWindow(); createTray(); });
});

app.on('before-quit', () => { if (pythonProc) pythonProc.kill(); });
```

### 8.3 `package.json` excerpt

```json
{
  "name": "axiom",
  "version": "1.0.0",
  "main": "electron/main.js",
  "scripts": {
    "start": "electron .",
    "build": "electron-builder"
  },
  "build": {
    "appId": "com.axiom.assistant",
    "productName": "AXIOM",
    "win": { "target": "nsis", "icon": "electron/build/icon.ico" },
    "extraResources": [
      { "from": ".", "to": ".", "filter": ["*.py", "*.yaml", "*.html", "*.md"] }
    ]
  }
}
```

### 8.4 Frameless window + custom title bar

Add to `voice_assistant_ui.html`:

```html
<div class="title-bar" id="titleBar">
  <span class="title-bar-label">AXIOM</span>
  <div class="title-bar-controls">
    <button id="minBtn">—</button>
    <button id="closeBtn">×</button>
  </div>
</div>
```

CSS: `-webkit-app-region: drag` on title bar, `no-drag` on buttons.

### 8.5 Auto-start with Windows

```javascript
app.setLoginItemSettings({ openAtLogin: true, args: ['--minimized'] });
```

### 8.6 Bundling Python

Two options:
- **A (preferred):** Use PyInstaller to bundle Python + deps as `axiom_backend.exe`. Electron spawns the .exe instead of `python server.py`. End user does NOT need Python installed.
- **B:** Require user to install Python. Smaller installer but worse UX.

Go with A. Build script:
```bash
pyinstaller --onefile --noconsole server.py --name axiom_backend --add-data "config.yaml;." --add-data "voice_assistant_ui.html;."
```

### 8.7 Acceptance criteria

- [ ] `npm start` launches AXIOM as a frameless desktop window
- [ ] System tray icon with right-click menu
- [ ] Closing window minimizes to tray (does not quit)
- [ ] Auto-starts with Windows
- [ ] `npm run build` produces `dist/AXIOM Setup 1.0.0.exe`
- [ ] Installer works on a clean Windows machine without Python
- [ ] Killing the app cleanly shuts down the Python backend

---

## 9. Phase 6: Advanced Tools

Implement in priority order:

### 9.1 Spotify control (priority 1)

```yaml
spotify:
  client_id: ""       # from developer.spotify.com (free)
  client_secret: ""
  redirect_uri: "http://127.0.0.1:8888/callback"
```

New tools:
- `spotify_play(query)` — searches and plays
- `spotify_control(action)` — `play|pause|next|previous|volume_up|volume_down`
- `spotify_now_playing()`

Lib: `spotipy`. OAuth handled once at first use.

### 9.2 Calendar (priority 2)

Free Google Calendar API:
- `list_events(date_range)`
- `create_event(title, datetime, duration)`
- `next_event()`

Lib: `google-api-python-client`. OAuth client secrets stored in `secrets/google.json`.

### 9.3 Code intelligence (priority 3)

Tools that act on the active repo:
- `create_file(path, content)`
- `read_file(path)`
- `search_codebase(query, repo)`
- `summarize_diff(repo)` — runs `git diff` and asks Gemini to summarize
- `explain_file(path)` — reads file, asks Gemini to explain

### 9.4 Email triage (priority 4)

- `unread_count()`
- `last_emails(n)` — subjects + senders, no bodies for privacy
- `summarize_inbox()`

### 9.5 Smart home (priority 5)

If user has Home Assistant:
- `ha_call_service(domain, service, data)`
- `ha_get_state(entity_id)`

### 9.6 Acceptance criteria

- [ ] Each tool has a Gemini declaration in `tools.py`
- [ ] Each tool has a unit test in `tests/test_tools.py`
- [ ] OAuth tokens persisted in `secrets/` (gitignored)
- [ ] Tools degrade gracefully when not configured

---

## 10. Phase 7: Reliability & Polish

### 10.1 Error handling

Standardize: every tool returns a string. On failure:
```python
return f"Could not {action}: {short_reason}"
```
Never raise. Wrap with try/except in `execute_tool`.

### 10.2 Logging

Replace `print()` with `logging`:
```python
import logging
log = logging.getLogger("axiom")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("axiom.log"),
        logging.StreamHandler(),
    ]
)
```
Rotate the log file at 10MB.

### 10.3 Health checks

Add `/api/health` endpoint:
```json
{
  "whisper": true,
  "gemini": true,
  "tts": true,
  "wake_word": false,
  "version": "1.0.0",
  "uptime_seconds": 3600
}
```

### 10.4 Graceful degradation

| Failure | Fallback |
|---|---|
| Gemini quota exhausted | Speak "I'm rate limited. Try again in a minute." |
| Internet down | Disable web search, weather, edge-tts → switch to pyttsx3 |
| Mic disconnected | UI shows red MIC indicator + spoken alert |
| Whisper fails | Fall back to Windows Speech Recognition (sapi5) |

### 10.5 Performance

- Pre-warm Whisper model on startup ✅ (already done)
- Pre-warm pygame mixer ✅ (already done)
- Cache Gemini system prompt token count (use `count_tokens` once)
- Stream Gemini responses, start TTS before full response received
- Debounce wake word detections (300ms)

### 10.6 Privacy

- Add `privacy.log_voice: false` to config (default false)
- Never persist raw audio
- Memory file uses local file only — no cloud sync
- API keys in `.env` only, never logged

### 10.7 Acceptance criteria

- [ ] No `print()` statements in production code
- [ ] All tools wrapped in try/except
- [ ] `/api/health` returns true component status
- [ ] App runs continuously for 24h without memory leak (test with `psutil`)
- [ ] Offline mode works (disable internet, app still hotkey + pyttsx3)

---

## 11. Full Configuration Reference

Final `config.yaml` schema after all phases:

```yaml
# ── Identity ─────────────────────────────────────────────────────────────
assistant:
  name: Axiom
  user_name: ""              # for personalization, e.g. "Hristian"
  hotkey: space
  personality:
    tone: professional       # professional | casual | snarky
    verbosity: concise       # concise | normal | verbose

# ── Audio ────────────────────────────────────────────────────────────────
audio:
  sample_rate: 16000
  max_record_seconds: 12
  vad_energy_threshold: 50
  vad_silence_duration: 1.5
  input_device: ""           # blank = system default

# ── STT ──────────────────────────────────────────────────────────────────
whisper:
  model: base                # tiny | base | small | medium | large
  language: en

# ── TTS ──────────────────────────────────────────────────────────────────
tts:
  engine: edge               # edge | pyttsx3
  edge_voice: en-US-AndrewNeural
  speed: 1.0
  pyttsx3_rate: 175
  pyttsx3_volume: 0.9
  fallback_offline: true

# ── LLM ──────────────────────────────────────────────────────────────────
gemini:
  model: gemini-2.5-flash
  max_tokens: 400
  temperature: 0.7
  streaming: true            # stream responses for lower latency

# ── Memory ───────────────────────────────────────────────────────────────
memory:
  file: memory.json
  max_history: 50
  auto_summarize_after: 20

# ── Server ───────────────────────────────────────────────────────────────
server:
  host: 127.0.0.1
  port: 5000
  open_browser: true

# ── Wake word ────────────────────────────────────────────────────────────
wake_word:
  enabled: true
  model: hey_jarvis          # built-in: alexa, hey_jarvis, hey_mycroft
  model_path: ""             # custom .onnx path (overrides model name)
  threshold: 0.5
  cooldown_seconds: 3

# ── Privacy ──────────────────────────────────────────────────────────────
privacy:
  log_voice: false
  log_transcripts: true
  share_telemetry: false

# ── Projects (Phase 2) ───────────────────────────────────────────────────
projects:
  axiom:
    name: "AXIOM"
    aliases: ["axiom voice assistant", "voice assistant"]
    repo_path: "E:/_DEV/Personal Voice Assistant"
    description: "Local Windows voice assistant"
    default_scenario: coding_sequence
    obsidian_folder: "Projects/AXIOM"
    websites: [github, claude]
    tags: [voice, ai, python]

# ── Websites (named shortcuts) ───────────────────────────────────────────
websites:
  github:   "https://github.com"
  email:    "https://mail.google.com"
  calendar: "https://calendar.google.com"
  youtube:  "https://youtube.com"
  chatgpt:  "https://chat.openai.com"
  claude:   "https://claude.ai"
  codex:    "https://chatgpt.com/codex"

# ── Scenarios (Phase 1) ──────────────────────────────────────────────────
scenarios:
  coding_sequence:
    description: "Start a coding session"
    requires_project: true
    steps: [...]   # see §4.5

# ── Obsidian ─────────────────────────────────────────────────────────────
obsidian:
  vault_path: ""
  daily_notes_folder: ""
  log_sessions: true         # auto-log conversations to today's daily note

# ── Integrations (Phase 6) ───────────────────────────────────────────────
spotify:
  client_id: ""
  client_secret: ""

google:
  oauth_credentials_file: "secrets/google.json"
  enable_calendar: false
  enable_gmail: false

home_assistant:
  url: ""
  token: ""
```

---

## 12. Voice Command Patterns

Maintain this list. Each entry maps a voice phrase to expected behavior. Used as test cases.

| Phrase pattern | Expected tool | Notes |
|---|---|---|
| "what time is it" | `get_datetime` | |
| "weather in {city}" | `get_weather` | |
| "search the web for {query}" | `search_web` | |
| "who is {name}" | `get_wikipedia` | |
| "open {app}" | `open_application` | |
| "open {website}" | `open_website` | |
| "open the {project} repo" | `open_repo` | |
| "git status on {project}" | `run_git` | |
| "what's on my screen" | `describe_screen` | |
| "save a note about {topic}" | `create_note` | |
| "add to today's note: {content}" | `append_daily_note` | |
| "search my notes for {query}" | `search_notes` | |
| "set a {N} minute timer" | `set_timer` | |
| "set volume to {N}" | `set_volume` | |
| "mute" | `set_volume(0)` | |
| "what's in my clipboard" | `read_clipboard` | |
| "start coding sequence for {project}" | `run_scenario` | scenario=coding_sequence, project_name={project} |
| "run morning routine" | `run_scenario` | scenario=morning_routine |
| "what projects do I have" | `list_projects` | Phase 2 |
| "how's {project} doing" | `project_status` | Phase 2 |
| "play {song} on Spotify" | `spotify_play` | Phase 6 |
| "what's next on my calendar" | `next_event` | Phase 6 |
| "exit" / "quit" / "goodbye" | shutdown | |

---

## 13. Testing & Acceptance

### 13.1 Test layout

```
tests/
  test_scenarios.py    # ScenarioEngine unit tests
  test_projects.py     # ProjectRegistry resolution
  test_tools.py        # tool dispatch, error handling
  test_config.py       # YAML round-trip, validation
  fixtures/
    test_config.yaml
```

Use `pytest`.

### 13.2 Voice end-to-end test harness

`test_voice_e2e.py`: takes a list of `.wav` test phrases and asserts the expected tool was called.

```python
PHRASES = [
    ("what_time.wav", "get_datetime"),
    ("open_axiom_repo.wav", "open_repo"),
    ("coding_sequence_axiom.wav", "run_scenario"),
]
```

### 13.3 Acceptance gates per phase

Before merging a phase:
- [ ] All tests in §13.1 pass
- [ ] Voice E2E harness passes for that phase's commands
- [ ] Manual test: record 5 voice commands, all behave as expected
- [ ] No new linter warnings (`ruff check`)
- [ ] [AXIOM_plan.md](AXIOM_plan.md) updated with new state

---

## 14. Target File Structure

After all phases complete:

```
Personal Voice Assistant/
├── AXIOM_plan.md                 ← project state (kept current)
├── AXIOM_roadmap.md              ← tool ideas backlog
├── AXIOM_architecture_plan.md    ← Electron rationale
├── AXIOM_development_plan.md     ← THIS FILE
├── README.md                     ← user-facing intro (Phase 5)
├── .env / .env.example           ← API keys
├── config.yaml                   ← master config
├── memory.json                   ← persistent conversation
├── axiom.log                     ← rotating log file
├── requirements.txt
├── package.json                  ← Phase 5 (Electron)
├── server.py                     ← Flask + SocketIO entry point
├── voice_assistant.py            ← STT → LLM → TTS pipeline
├── scenarios.py                  ← Phase 1
├── projects.py                   ← Phase 2
├── tools.py                      ← all tool implementations
├── voice_assistant_ui.html       ← UI (kept; tabs added in Phase 4)
├── run.pyw                       ← silent launcher
├── train_wake_word.py            ← Phase 3
├── electron/                     ← Phase 5
│   ├── main.js
│   ├── preload.js
│   ├── package.json
│   └── build/icon.ico
├── secrets/                      ← Phase 6 (gitignored)
│   └── google.json
├── tests/
│   ├── test_scenarios.py
│   ├── test_projects.py
│   ├── test_tools.py
│   └── fixtures/
└── custom_models/                ← Phase 3 (optional)
    └── hey_axiom.onnx
```

---

## 15. Coding Conventions

Rules for AI agents implementing this plan. Read these before writing code.

### 15.1 Style
- Python 3.13+, type hints everywhere
- Functions ≤ 40 lines; split if longer
- f-strings for formatting; no `%` or `.format()`
- `from __future__ import annotations` on every module
- Explicit imports, no `*`

### 15.2 Naming
- Tools: snake_case verbs (`open_repo`, `run_scenario`)
- Classes: PascalCase nouns (`ScenarioEngine`, `ProjectRegistry`)
- Constants: SCREAMING_SNAKE
- Private helpers: leading underscore (`_resolve_repo_path`)

### 15.3 Tool implementation rules
1. Every tool has a Gemini declaration in `GEMINI_TOOLS`
2. Every tool has an entry in the `execute_tool()` dispatch map
3. Every tool returns a string (≤ 800 chars; truncate longer outputs)
4. Every tool catches its own exceptions and returns a friendly error string
5. Tools that take long > 2s must emit a `_send("state", {...})` so UI updates

### 15.4 Config access
- Always read config via the singleton loaded at startup
- Never `open("config.yaml")` from inside a tool — use the cached `_CFG`
- Reload via `reload_config()` only — never module-level state outside that

### 15.5 Threading
- `asyncio` only for `edge-tts`; everything else uses `threading.Thread`
- All threads daemon=True so they die with the main process
- Wake word listener and scenario steps must NOT block the SocketIO event loop

### 15.6 SocketIO event names
Use only these event names (canonical):

| Event | Direction | Payload |
|---|---|---|
| `state` | server → client | `{state: idle\|listening\|transcribing\|thinking\|tool\|speaking}` |
| `transcript` | server → client | `{text}` |
| `response` | server → client | `{text}` |
| `tool` | server → client | `{name, input}` |
| `scenario_step` | server → client | `{scenario, step, index, total}` |
| `log` | server → client | `{level, text}` |
| `config_reloaded` | server → client | `{}` |
| `error` | server → client | `{message}` |

### 15.7 Commit messages
Format: `phase{N}: {area} — {short description}`
Examples:
- `phase1: scenarios — add ScenarioEngine with 11 actions`
- `phase2: projects — fuzzy resolution with rapidfuzz`

### 15.8 Don't do
- ❌ Add new top-level Python files without updating `AXIOM_plan.md`
- ❌ Change `voice_assistant_ui.html` aesthetic (color, font, grid bg)
- ❌ Persist raw audio to disk
- ❌ Hardcode user names, paths, or API keys
- ❌ Skip error handling because "it'll never fail"

---

## Phase Order Cheat Sheet

```
Phase 1: Scenario Engine          ★★★★★ blocks everything else
Phase 2: Project Workspaces       ★★★★☆
Phase 3: Voice UX Polish          ★★★★☆ user-facing quality jump
Phase 4: Settings UI              ★★★☆☆ quality of life
Phase 5: Electron Desktop App     ★★★★★ shipping milestone
Phase 6: Advanced Tools           ★★★☆☆ expand capability
Phase 7: Reliability & Polish     ★★★★☆ pre-1.0 stabilization
```

When in doubt, do them in order.
