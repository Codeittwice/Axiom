# AXIOM — Step 2: Architecture Plan
> Decision document for evolving from Flask+browser to a proper standalone app.
> Do not build until option is chosen.

---

## Current Architecture (v0.2)

```
server.py (Flask + SocketIO)
  ├── Serves voice_assistant_ui.html over HTTP
  ├── voice_assistant.py runs in a background thread
  └── Browser opens localhost:5000 — user must keep it open
```

**Pain points:**
- Requires a terminal window + a browser window
- Not a "real" desktop app — feels like a dev tool
- Browser can be accidentally closed
- No OS-level integration (notifications, auto-start, taskbar)

---

## Option A — Electron (Recommended)

**What it is:** Package the existing HTML/CSS/JS UI into a native desktop window using Node.js + Chromium under the hood.

```
AXIOM.exe
  ├── Electron main process (Node.js)
  │     ├── Creates native window → loads UI
  │     ├── System tray icon
  │     ├── Auto-start with Windows
  │     └── Spawns server.py as a child process
  └── Python backend (server.py unchanged)
        └── Communicates via WebSocket on localhost
```

**Pros:**
- ✅ Zero UI rewrite — existing HTML/CSS/JS works as-is
- ✅ Feels like a real desktop app (taskbar, tray, no browser needed)
- ✅ Can be packaged into a single AXIOM Setup.exe installer
- ✅ Native OS notifications, window management, auto-start
- ✅ Chromium renderer = full CSS/JS support, same as browser
- ✅ Large ecosystem (electron-builder, auto-updater)

**Cons:**
- ❌ Requires Node.js installed during development
- ❌ Large bundle (~150–200MB) because it ships Chromium
- ❌ Two runtimes: Python + Node.js

**Stack additions:**
```
Node.js + npm
electron
electron-builder (for packaging to .exe)
```

**Key files to create:**
```
electron/
  main.js       — starts Python, creates window, tray icon
  preload.js    — bridge between Node and renderer
  package.json  — electron-builder config
```

**Effort estimate:** ~1–2 days of work

---

## Option B — Tauri (Lightweight Native)

**What it is:** Rust-based desktop framework using the OS's built-in WebView (Edge on Windows) instead of shipping Chromium.

```
AXIOM.exe (~10MB)
  ├── Tauri core (Rust)
  │     ├── Wraps system WebView (Edge/WebView2)
  │     └── Spawns Python backend
  └── Same HTML/CSS/JS UI
```

**Pros:**
- ✅ Tiny bundle — ~10MB vs Electron's 150MB
- ✅ Uses OS WebView2 (already on Windows 11) — no Chromium
- ✅ Zero UI rewrite
- ✅ Better performance and memory use than Electron
- ✅ Can be packaged as .exe or .msi installer

**Cons:**
- ❌ Requires Rust toolchain (complex setup)
- ❌ Smaller ecosystem than Electron
- ❌ WebView2 rendering can differ slightly from Chrome
- ❌ More complex build pipeline

**Effort estimate:** ~2–3 days (Rust setup adds friction)

---

## Option C — PyQt6 / PySide6 (Pure Python)

**What it is:** Rewrite the UI as a native Python GUI using Qt widgets.

```
server.py (unchanged Python backend)
  └── PyQt6 window
        ├── Custom dark-theme widgets
        ├── System tray
        └── Replaces the HTML UI entirely
```

**Pros:**
- ✅ Single language — pure Python
- ✅ True native Windows widgets
- ✅ No browser or Node.js required
- ✅ Can be packaged with PyInstaller into .exe

**Cons:**
- ❌ Complete UI rewrite — the existing HTML/CSS/JS is thrown away
- ❌ Qt UI code is verbose; matching the current futuristic aesthetic is hard
- ❌ PyQt6 licensing (GPL / commercial)
- ❌ Harder to achieve the animated sci-fi look vs CSS

**Effort estimate:** ~3–5 days (UI rewrite is significant)

---

## Option D — Full JS / Node.js

**What it is:** Rewrite the Python backend in Node.js, keep the HTML frontend.

```
Node.js app
  ├── Express + socket.io (replaces Flask + flask-socketio)
  ├── Spawns Python only for Whisper transcription (hard to replace)
  └── Calls Gemini API directly from JS
```

**Pros:**
- ✅ Single language for backend + frontend
- ✅ Rich npm ecosystem

**Cons:**
- ❌ Whisper has no good Node.js equivalent — Python still needed for STT
- ❌ Large rewrite with no real gain
- ❌ Not recommended

---

## Recommendation: Electron

| Criterion | Electron | Tauri | PyQt6 |
|---|---|---|---|
| UI rewrite needed | ❌ None | ❌ None | ✅ Full rewrite |
| Bundle size | ~150MB | ~10MB | ~50MB |
| Setup complexity | 🟡 Medium | 🔴 High (Rust) | 🟢 Easy |
| Native feel | ✅ Good | ✅ Best | ✅ Best |
| Packaging to .exe | ✅ electron-builder | ✅ cargo build | ✅ PyInstaller |
| Effort | 1–2 days | 2–3 days | 3–5 days |

**Go with Electron.** No UI rewrite, familiar web stack, packages cleanly to .exe.

---

## Electron Implementation Plan (when ready to build)

### Phase 1 — Basic Electron shell
1. `npm init` in project root
2. Install `electron` + `electron-builder`
3. `electron/main.js`:
   - Spawn `python server.py` as child process
   - Wait for server to be ready (poll localhost:5000)
   - Create `BrowserWindow` → load `http://localhost:5000`
   - Add system tray with open/quit menu
4. Test: `npm start`

### Phase 2 — Polish
5. Custom window title bar (frameless + draggable)
6. Auto-start with Windows (via `app.setLoginItemSettings`)
7. Kill Python process on app quit
8. Handle server crash → restart Python automatically

### Phase 3 — Packaging
9. Configure `electron-builder` in `package.json`
10. `npm run build` → `dist/AXIOM Setup.exe`
11. Optional: code signing for Windows SmartScreen bypass

### File structure
```
Personal Voice Assistant/
  ├── electron/
  │     ├── main.js
  │     ├── preload.js
  │     └── package.json
  ├── server.py
  ├── voice_assistant.py
  ├── voice_assistant_ui.html   ← unchanged
  └── ...
```

---

## Decision
> Fill this in when ready to proceed:

- [x] Chosen option: Electron
- [ ] Node.js installed
- [ ] Ready to build
