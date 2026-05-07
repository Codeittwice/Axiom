# AXIOM Voice Assistant — Project Summary
> Handoff from Claude.ai chat · Continue in Claude Code

---

## Project Goal
Build a personal AI voice assistant called **AXIOM** running locally on PC.
Design aesthetic: **futuristic / scientific** (dark theme, monospace fonts, grid UI).

---

## Current Stack
| Layer | Tool | Notes |
|---|---|---|
| Speech → Text | OpenAI Whisper (local) | `whisper-base` model, runs offline |
| AI Brain | Anthropic Claude API | `claude-sonnet-4-20250514` |
| Text → Speech | pyttsx3 | Offline, cross-platform |
| Activation | `keyboard` hotkey | Press SPACE to record |
| Audio recording | `sounddevice` + `scipy` | 16kHz WAV, 5s default |

---

## Files Created
- `voice_assistant.py` — Main Python script (fully working starter)
- `voice_assistant_ui.html` — Visual dashboard UI (futuristic sci-fi design)

---

## Key Config (in voice_assistant.py)
```python
ANTHROPIC_API_KEY = "your_api_key_here"   # → console.anthropic.com
SAMPLE_RATE       = 16000
RECORD_SECONDS    = 5
HOTKEY            = "space"
ASSISTANT_NAME    = "Axiom"
```

---

## Install Command
```bash
pip install openai-whisper anthropic pyttsx3 sounddevice scipy numpy keyboard
```

---

## How It Works (flow)
1. User presses SPACE → records audio for 5s
2. Whisper transcribes audio locally to text
3. Text + conversation history sent to Claude API
4. Claude responds; response appended to history (multi-turn memory)
5. pyttsx3 speaks the response aloud
6. Loop repeats until user says "exit" / "goodbye" / presses ESC

---

## Next Steps / Ideas
- [ ] Add a wake word ("Hey Axiom") using **Porcupine** (Picovoice free tier)
- [ ] Build a proper GUI with **tkinter** or **PyQt** (replace HTML dashboard)
- [ ] Add tool use: open apps, search the web, control Spotify
- [ ] Switch TTS to **Coqui TTS** or **ElevenLabs** for better voice quality
- [ ] Add a config file (`config.yaml`) instead of hardcoded constants
- [ ] Package as a background system tray app
- [ ] Add voice activity detection (VAD) instead of fixed recording duration

---

## Notes
- Windows users may need: `pip install pipwin && pipwin install pyaudio`
- Whisper first run downloads the model (~140MB for base)
- The HTML UI is purely visual/demo — not connected to the Python backend yet
