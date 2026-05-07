# AXIOM Repo Notes for Codex

Last studied: 2026-05-05

## Repo Snapshot

AXIOM is a local Windows personal voice assistant. The current working code is Python-first:

- `server.py`: entry point; starts Flask + Flask-SocketIO, launches the assistant loop in a background thread, serves `voice_assistant_ui.html`, optionally opens the browser and tray icon.
- `voice_assistant.py`: core voice pipeline; loads config, loads local Whisper, records mic audio with energy VAD, transcribes, sends text to Gemini with tools, saves memory, speaks via edge-tts or pyttsx3.
- `tools.py`: Gemini tool declarations and implementations for web search, weather, Wikipedia, app/website/repo opening, git/terminal commands, screen description, Obsidian notes, volume, timers, clipboard.
- `voice_assistant_ui.html`: browser-based futuristic UI connected over Socket.IO.
- `config.yaml`: runtime config, including Gemini model, Whisper model, TTS, server, wake word, repos, websites, Obsidian, scenarios.
- `.env.example`: API key template.
- `requirements.txt`: Python dependencies.
- `memory.json`: persisted conversation history.
- `AXIOM_*.md`: planning and roadmap docs, some of which are stale.

Important mismatch: older docs still mention Claude or Anthropic, but live code uses Gemini via `google-generativeai`. Treat code as source of truth.

## Current Pipeline

Hotkey or wake word -> energy VAD recording -> local Whisper STT -> Gemini chat with function calling -> local tool execution if needed -> TTS -> Socket.IO UI updates.

The current app is not purely offline:

- Whisper is local after model download.
- edge-tts is online.
- Gemini is online/API-based.
- Web search/weather/Wikipedia are online.
- pyttsx3 fallback is offline.

## OpenAI API Instead of Gemini

Short answer: OpenAI API is not a Gemini-like free-tier replacement for this app today.

Official sources checked:

- OpenAI pricing: https://platform.openai.com/docs/pricing
- OpenAI prepaid billing: https://help.openai.com/en/articles/8264778-what-is-prepaid-billing
- OpenAI prepaid setup: https://help.openai.com/en/articles/8264644-how-can-i-set-up-prepaid-billing
- OpenAI JavaScript quickstart: https://platform.openai.com/docs/quickstart/using-the-api
- OpenAI API reference / auth: https://platform.openai.com/docs/api-reference
- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini API rate limits: https://ai.google.dev/gemini-api/docs/rate-limits

Findings:

- OpenAI API pricing is usage-based. Text models list per-token prices, e.g. `gpt-5-nano` is very cheap but still paid usage.
- OpenAI says new API accounts are enrolled in prepaid billing. Minimum credit purchase is documented as $5. Free credits, if any, are consumed before paid credits, but the docs do not present a standing always-free API tier equivalent to Gemini's free tier.
- OpenAI moderation models are listed as free, but that does not help replace the assistant brain.
- The OpenAI quickstart mentions a free test API request and then tells users to add credits for real building.
- Gemini Developer API explicitly advertises a Free tier with free input/output tokens for eligible users and limited model access. The repo is aligned with that constraint.

Recommendation:

- Keep Gemini if the hard requirement is "free tier only".
- Add OpenAI as an optional paid provider if quality, tool support, or model selection matters more than zero cost.
- If adding OpenAI, use a provider abstraction rather than replacing Gemini inline.

## OpenAI Migration Shape

If adding OpenAI to the Python app:

- Add `openai` to `requirements.txt`.
- Add `OPENAI_API_KEY` to `.env.example`.
- Add config keys like:
  - `llm.provider: gemini | openai`
  - `openai.model: gpt-5-nano` or another selected model
  - `openai.max_output_tokens`
- Refactor `ask_ai()` into provider-specific adapters:
  - `ask_gemini(user_text, history)`
  - `ask_openai(user_text, history)`
- Keep shared history format as `{"role": "user"|"model", "text": "..."}` and convert per provider.
- Convert `tools.py` into provider-neutral tool specs plus provider-specific schema rendering. Current `GEMINI_TOOLS` is Gemini-shaped.
- OpenAI Responses API supports function calling and server-side tools, but this app should keep local tools as explicit custom function calls for safety and cost control.

Potential simple OpenAI JS call, server-side only:

```js
import OpenAI from "openai";

const client = new OpenAI();

const response = await client.responses.create({
  model: "gpt-5-nano",
  instructions: "You are Axiom, a concise spoken personal assistant.",
  input: "What time is it?"
});

console.log(response.output_text);
```

Never expose `OPENAI_API_KEY` in browser JavaScript. Keep it in Python, Node main process, or another server-side process.

## JavaScript vs Python

Best use of JavaScript here: Electron/Tauri-style shell and UI, not a full backend rewrite.

Reasoning:

- Existing frontend is already HTML/CSS/JS and can be wrapped in Electron with little UI rewrite.
- Node.js can call Gemini or OpenAI APIs cleanly.
- Socket.IO maps cleanly from Flask-SocketIO to Node `socket.io` if the server is rewritten later.
- Python is still better for the current local capabilities: Whisper, `sounddevice`, `keyboard`, `openwakeword`, pycaw volume control, pystray, Windows scripting, and the current working implementation.

Preferred architecture:

```text
Electron app
  - native desktop window
  - tray/autostart/window lifecycle
  - loads existing UI
  - spawns Python backend

Python backend
  - audio capture
  - VAD
  - Whisper
  - tools
  - provider adapter for Gemini/OpenAI
  - Socket.IO events
```

Second-best architecture:

```text
Node backend
  - Express + socket.io
  - API provider calls
  - static UI serving

Python helper
  - transcription/audio/wake-word/Windows controls
```

This is more moving parts for little benefit, unless the goal is specifically to learn Node.

Full JS rewrite risks:

- Local Whisper from Node is less straightforward than Python `openai-whisper`.
- Windows hotkey, mic VAD, tray, volume control, and wake-word packages are less proven in this repo.
- API calls are easy in JS, but the hard parts of this assistant are local audio and OS integration.

## Practical Next Steps

1. Fix docs drift:
   - Replace Claude/Anthropic wording in `AXIOM_plan.md`, `AXIOM_project_summary.md`, and comments with Gemini/current provider wording.
   - Fix `.env.example` comment; it points to Anthropic even though it defines `GEMINI_API_KEY`.
2. Add `.gitignore` before any future git init:
   - `.env`
   - `__pycache__/`
   - `*.pyc`
   - local build/package folders
3. Add an LLM provider interface:
   - Keep Gemini default.
   - Make OpenAI optional.
4. For JavaScript, start with Electron wrapper:
   - `package.json`
   - `electron/main.js`
   - spawn `python server.py`
   - open `http://127.0.0.1:5000`
   - close Python process on quit.
5. Only rewrite backend to Node after Electron wrapper works and the Python/JS boundary feels like a real problem.

## Product Direction From User

The desired final product is a real desktop app: a personal assistant that can control the user's PC by voice.

Core app goals:

- Open any installed desktop application by name.
- Open any website by URL or friendly alias.
- Perform web searches.
- Open groups of apps/websites/files as named scenarios.
- Understand project-focused commands like: "Start coding sequence for project X."
- For a coding scenario, open the project repository in an IDE plus relevant AI/research tools such as Claude, Codex, Google, ChatGPT, docs, GitHub, or other configured tabs.

Implication:

- Keep developing toward an Electron/Tauri-style desktop app with a tray icon and native window.
- Make `config.yaml` or a future GUI settings screen the central place for apps, websites, repositories, and scenarios.
- Scenarios should become first-class data, not hardcoded logic. A scenario should support:
  - apps to launch
  - websites/tabs to open
  - repos/folders to open
  - terminal commands to run
  - optional project-specific variables
- The assistant should eventually resolve "project X" against configured repositories/projects and apply the selected scenario to that project.

## Things to Remember

- `run.pyw` imports `server` and manually starts the same components because `server.py` only runs its main block when directly invoked.
- `wake_word.enabled` is currently true in `config.yaml`; this can make startup heavier because openwakeword model setup runs.
- `config.yaml` says `gemini-2.5-flash`; docs mention older `gemini-2.0-flash`. Code uses config.
- Many comments and docs show mojibake characters, likely encoding drift from copied Unicode symbols. New edits should prefer ASCII unless preserving existing style is necessary.
- This folder is not currently a git repository.
- I attempted to install the OpenAI docs MCP with `codex mcp add openaiDeveloperDocs --url https://developers.openai.com/mcp`, but Windows returned Access denied.
