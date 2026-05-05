# AXIOM — Implementation Plan & Project State
> Living reference document. Update this as features are completed or changed.

---

## Project Goal
Local AI voice assistant named **AXIOM** running on Windows PC.
Aesthetic: futuristic / scientific (dark theme, monospace, grid UI).
Budget: **free tier only** — no paid APIs beyond Anthropic Claude.

---

## Architecture Overview

Phase 5 adds an Electron desktop shell. Electron starts `server.py`, waits for the Flask/SocketIO backend, opens the existing HTML UI in a frameless native window, and owns the tray/startup lifecycle.

```
run.pyw  (no-console launcher, system tray)
  └── server.py  (Flask + SocketIO — single entry point)
        ├── voice_assistant.py  (core engine: VAD → Whisper → Claude → TTS)
        │     └── tools.py  (Claude tool use: search, weather, open apps)
        └── voice_assistant_ui.html  (browser UI, connects via WebSocket)

Config:
  .env          ← API keys only (gitignored)
  config.yaml   ← all settings
  memory.json   ← persistent conversation history (auto-created)
```

**How to run:**
```bash
python server.py        # with console (recommended while developing)
pythonw run.pyw         # silent, system tray only
npm start               # Electron desktop shell (Phase 5)
```
Then open http://127.0.0.1:5000 (auto-opens on start).

---

## Stack

| Layer | Tool | Cost | Notes |
|---|---|---|---|
| STT | OpenAI Whisper (local) | Free | `whisper-base` (~140MB, runs offline) |
| AI Brain | Google Gemini API | **Free tier** | `gemini-2.0-flash` via Google AI Studio |
| TTS | edge-tts | Free | Uses Microsoft Edge voices online |
| TTS fallback | pyttsx3 | Free | Fully offline |
| Audio I/O | sounddevice + scipy | Free | 16kHz WAV |
| VAD | Energy-based (custom) | Free | No extra deps; stops on silence |
| Wake word | keyboard hotkey (`ctrl+alt+space`) | Free | Default; openwakeword optional |
| Tool: search | duckduckgo-search | Free | No API key needed |
| Tool: weather | wttr.in (HTTP) | Free | No API key needed |
| Tool: apps | subprocess | Free | Windows shell |
| UI bridge | Flask + flask-socketio | Free | WebSocket real-time state |
| System tray | pystray + Pillow | Free | Optional, `run.pyw` |
| Desktop shell | Electron | Free | Phase 5 native window + tray |

---

## File Inventory

| File | Status | Purpose |
|---|---|---|
| `AXIOM_plan.md` | ✅ Done | This file — plan + state reference |
| `requirements.txt` | ✅ Done | All pip dependencies |
| `.env.example` | ✅ Done | API key template |
| `config.yaml` | ✅ Done | All settings |
| `voice_assistant.py` | ✅ Done | Core engine (rewritten) |
| `tools.py` | ✅ Done | Tool use implementations |
| `server.py` | ✅ Done | Flask + SocketIO entry point |
| `voice_assistant_ui.html` | ✅ Phase 5 | Browser UI with live WebSocket, config tabs, and Electron title bar |
| `package.json` | ✅ Phase 5 | Electron scripts + electron-builder config |
| `electron/` | ✅ Phase 5 | Main process, preload bridge, tray/window icon |
| `google_auth.py` | ✅ Phase 6a | Shared Google OAuth token/service helper |
| `google_calendar.py` | ✅ Phase 6a | Google Calendar events + creation wrapper |
| `gmail_client.py` | ✅ Phase 6 | Read-only Gmail triage helper |
| `spotify_client.py` | ✅ Phase 6 | Spotify OAuth/playback helper |
| `tests/test_tools.py` | ✅ Phase 6 | Unit tests for old advanced tools |
| `run.pyw` | ✅ Done | No-console system tray launcher |
| `scenarios.py` | ✅ Phase 1 | ScenarioEngine — multi-step workflows |
| `projects.py` | ✅ Phase 2 | ProjectRegistry — fuzzy voice resolution + status |
| `train_wake_word.py` | Phase 3 | Collects custom "Hey Axiom" wake-word samples |
| `AXIOM_development_plan.md` | ✅ Done | Master spec for AI coding agents |
| `AXIOM_progress.md` | ✅ Done | Running implementation log per phase |
| `AXIOM_roadmap.md` | ✅ Done | Tool ideas backlog |
| `AXIOM_architecture_plan.md` | ✅ Done | Electron rationale (Phase 5) |
| `memory.json` | Auto-created | Persistent conversation history |
| `.env` | **You create** | Copy `.env.example`, add your key |

---

## Prerequisites (one-time setup)

### 1. Python 3.9+
Verify: `python --version`

### 2. FFmpeg (required by Whisper)
```powershell
# Option A — winget (Windows 11)
winget install Gyan.FFmpeg

# Option B — Chocolatey
choco install ffmpeg

# Option C — manual
# Download from https://ffmpeg.org/download.html, extract, add bin/ to PATH
```
Verify: `ffmpeg -version`

### 3. Install Python packages
```bash
pip install -r requirements.txt
```
First run downloads Whisper base model (~140MB) automatically.

### 4. Set your API key
```bash
copy .env.example .env
# Edit .env — paste your key from https://aistudio.google.com (free, no card)
```

---

## Running AXIOM

```bash
python server.py
```
- Browser opens automatically at http://127.0.0.1:5000
- Press **CTRL+ALT+SPACE** to start speaking (hotkey configurable in `config.yaml`)
- Say **"exit"** or **"goodbye"** to quit cleanly
- Press **ESC** to force-quit the terminal

**First run note:** Whisper will download `whisper-base` (~140MB). Subsequent starts are instant.

---

## Configuration Reference (`config.yaml`)

| Key | Default | Notes |
|---|---|---|
| `assistant.name` | `Axiom` | Spoken name + system prompt identity |
| `assistant.hotkey` | `ctrl+alt+space` | Any key name or combo from the `keyboard` library |
| `audio.vad_energy_threshold` | `500` | Raise if mic picks up background noise |
| `audio.vad_silence_duration` | `1.5` | Seconds of silence before stopping recording |
| `audio.max_record_seconds` | `12` | Hard cap on recording duration |
| `whisper.model` | `base` | `tiny` (fastest) → `large` (most accurate) |
| `tts.engine` | `edge` | `edge` (online, great quality) or `pyttsx3` (offline) |
| `tts.edge_voice` | `en-US-AriaNeural` | See edge-tts voice list below |
| `gemini.model` | `gemini-2.0-flash` | Any Gemini model — `gemini-1.5-flash` also free |
| `gemini.max_tokens` | `400` | Keep low for faster spoken responses |
| `memory.max_history` | `50` | Messages retained across sessions |
| `server.port` | `5000` | Change if port is in use |
| `wake_word.enabled` | `false` | Set `true` after installing openwakeword |

### Available edge-tts voices (selection)
```
en-US-AriaNeural       ← default, female, natural
en-US-GuyNeural        ← male
en-US-JennyNeural      ← female, conversational
en-GB-SoniaNeural      ← British female
en-AU-NatashaNeural    ← Australian female
```
Full list: `python -m edge_tts --list-voices`

---

## Claude Tool Use

AXIOM has four built-in tools Claude can invoke automatically:

| Tool | Trigger example | Notes |
|---|---|---|
| `search_web` | "What's in the news today?" | DuckDuckGo, no API key |
| `get_datetime` | "What time is it?" | Local system time |
| `open_application` | "Open Notepad" | Windows apps via subprocess |
| `get_weather` | "What's the weather in London?" | wttr.in, no API key |
| `open_website` | "Open GitHub" / "Open my email" | URL shortcuts in `config.yaml` `websites:` |
| `open_repo` | "Open the axiom repo" | Path mapping in `config.yaml` `repos:` |
| `list_repos` | "What repos do you know?" | Lists configured repo names |

### Adding repos and websites
Edit `config.yaml`:
```yaml
repos:
  axiom: "E:/_DEV/Personal Voice Assistant"
  myproject: "C:/path/to/myproject"

websites:
  github: "https://github.com"
  email: "https://mail.google.com"
```
Then say *"open my project repo"* or *"open my email"*.

### Composite commands
Gemini can chain multiple tools in one turn. Try:
*"Start my coding setup — open VS Code, the AXIOM repo, and GitHub."*
AXIOM will call `open_application`, `open_repo`, and `open_website` in sequence.

To add more tools: edit `tools.py` — add to `TOOLS` list and `execute_tool()`.

---

## Optional: Wake Word ("Hey Axiom")

Instead of pressing the configured hotkey, AXIOM can listen for a spoken wake word.

### Setup
```bash
pip install openwakeword
python -c "import openwakeword; openwakeword.utils.download_models()"
```

### Enable
In `config.yaml`:
```yaml
wake_word:
  enabled: true
  model: hey_mycroft   # free built-in model; custom training possible
```

### Custom wake word
Train a custom "Hey Axiom" model at https://github.com/dscripka/openWakeWord

---

## Optional: Better Offline TTS (Coqui TTS)

For a high-quality offline voice (no internet needed):
```bash
pip install TTS
```
In `config.yaml`:
```yaml
tts:
  engine: coqui
  coqui_model: tts_models/en/ljspeech/tacotron2-DDC
```
First run downloads the model (~200MB).
> Note: Add Coqui support to `voice_assistant.py` `speak()` function when ready.

---

## Future Ideas

- [x] Spotify control via `spotipy` — "play lo-fi music"
- [x] Read/write/search/explain files inside configured repos
- [x] Google Calendar integration - Phase 6a voice tools + REST endpoints
- [x] Screenshot + vision — describe what's on screen
- [ ] Multi-language support (Whisper supports 99 languages)
- [ ] Package as `.exe` via PyInstaller
- [ ] Custom "Hey Axiom" wake word training (openwakeword)
- [ ] Coqui TTS for fully offline high-quality voice

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `keyboard` requires admin | Run terminal as Administrator, or switch to `pynput` |
| No audio / wrong mic | Check `sounddevice` device list: `python -c "import sounddevice; print(sounddevice.query_devices())"` |
| Whisper very slow | Switch to `whisper.model: tiny` in config |
| TTS not working | Set `tts.engine: pyttsx3` for offline fallback |
| Port 5000 in use | Change `server.port` in config.yaml |
| VAD too sensitive | Raise `audio.vad_energy_threshold` (try 1000–2000) |
| edge-tts no sound | Ensure `pygame` installed: `pip install pygame` |
