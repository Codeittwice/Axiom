"""
AXIOM Server — entry point.
Starts the Flask + SocketIO UI server, runs the voice assistant loop
in a background thread, and optionally creates a system tray icon.

Usage:
    python server.py          # normal run (console visible)
    pythonw run.pyw           # silent, system tray only
"""

import os
import sys
import threading
import time
import webbrowser

import keyboard
import yaml
from flask import Flask, send_file
from flask_socketio import SocketIO

# ─── Config ───────────────────────────────────────────────────────────────────
with open("config.yaml") as _f:
    CFG = yaml.safe_load(_f)

HOST = CFG["server"]["host"]
PORT = CFG["server"]["port"]

# ─── Flask + SocketIO ─────────────────────────────────────────────────────────
app      = Flask(__name__)
app.config["SECRET_KEY"] = "axiom-local-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


def emit(event: str, data: dict):
    socketio.emit(event, data)


@app.route("/")
def index():
    return send_file("voice_assistant_ui.html")


@socketio.on("connect")
def on_connect():
    emit("state", {"state": "idle"})
    emit("log",   {"level": "system", "text": "AXIOM online — press SPACE to speak."})


# ─── Assistant loop ───────────────────────────────────────────────────────────

def assistant_loop():
    from voice_assistant import (
        ASSISTANT_NAME,
        ask_ai,
        init_scenario_engine,
        load_history,
        record_audio,
        save_history,
        set_emit,
        speak,
        start_wake_word_listener,
        transcribe,
        _wake_event,
    )

    set_emit(emit)
    init_scenario_engine()

    history = load_history()
    hotkey  = CFG["assistant"]["hotkey"]
    wake_started = start_wake_word_listener()
    hotkey_registered = False

    def activate_from_hotkey():
        emit("log", {"level": "system", "text": f"Hotkey {hotkey.upper()} pressed."})
        _wake_event.set()

    try:
        keyboard.add_hotkey(hotkey, activate_from_hotkey)
        keyboard.add_hotkey("esc", lambda: os._exit(0))
        hotkey_registered = True
    except Exception as e:
        emit("log", {"level": "warn", "text": f"Hotkey registration failed: {e}"})

    print(f"\n[AXIOM] Ready — press {hotkey.upper()} to speak, ESC to quit.\n")
    emit("log", {"level": "system", "text": f"Ready - press {hotkey.upper()} or say the wake word."})
    emit("state", {"state": "idle"})

    while True:
        # Wait for hotkey or wake word
        if hotkey_registered or wake_started:
            _wake_event.clear()
            _wake_event.wait()
        else:
            keyboard.wait(hotkey)
        time.sleep(0.05)

        # --- Record ---
        audio_path = record_audio()
        if not audio_path:
            emit("log", {"level": "warn", "text": "No audio detected — try again."})
            emit("state", {"state": "idle"})
            continue

        # --- Transcribe ---
        text = transcribe(audio_path)
        if not text:
            emit("log",   {"level": "warn", "text": "Could not understand audio."})
            emit("state", {"state": "idle"})
            continue

        emit("transcript", {"text": text})

        # --- Exit intent ---
        if any(w in text.lower() for w in ("exit", "quit", "goodbye", "bye")):
            speak(f"Goodbye! Have a great day.")
            save_history(history)
            emit("log", {"level": "system", "text": "Session ended."})
            os._exit(0)

        # --- Ask Claude ---
        try:
            reply, history = ask_ai(text, history)
            save_history(history)
            emit("response", {"text": reply})
        except Exception as e:
            msg = f"Error communicating with Gemini: {e}"
            print(f"[AXIOM] {msg}")
            emit("log",   {"level": "error", "text": msg})
            emit("state", {"state": "idle"})
            continue

        # --- Speak ---
        speak(reply)

# ─── System tray (optional) ───────────────────────────────────────────────────

def _make_tray_icon():
    try:
        import pystray
        from PIL import Image, ImageDraw

        size = 64
        img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d    = ImageDraw.Draw(img)
        d.ellipse([4, 4, size - 4, size - 4], fill="#00d4ff")
        d.ellipse([18, 18, size - 18, size - 18], fill="#03050e")

        def open_ui(icon, item):
            webbrowser.open(f"http://{HOST}:{PORT}")

        def quit_app(icon, item):
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Open AXIOM", open_ui, default=True),
            pystray.MenuItem("Quit",       quit_app),
        )
        icon = pystray.Icon("AXIOM", img, "AXIOM Voice Assistant", menu)
        icon.run()
    except ImportError:
        pass  # pystray not installed — skip tray


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Import engine here (not at top) so Flask starts before Whisper loads
    print("[AXIOM] Starting…")

    # Assistant runs in a background thread
    t = threading.Thread(target=assistant_loop, daemon=True)
    t.start()

    # Open browser after server is up
    if CFG["server"]["open_browser"]:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()

    # System tray runs in another thread (if pystray available)
    tray_thread = threading.Thread(target=_make_tray_icon, daemon=True)
    tray_thread.start()

    print(f"[AXIOM] UI at http://{HOST}:{PORT}")
    socketio.run(app, host=HOST, port=PORT, debug=False, use_reloader=False)
