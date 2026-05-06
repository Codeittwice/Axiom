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
from datetime import datetime
from pathlib import Path

import keyboard
import yaml
from flask import Flask, jsonify, request, send_file
from flask_socketio import SocketIO

# ─── Config ───────────────────────────────────────────────────────────────────
with open("config.yaml") as _f:
    CFG = yaml.safe_load(_f)

HOST = CFG["server"]["host"]
PORT = int(os.environ.get("AXIOM_PORT", CFG["server"]["port"]))

# ─── Flask + SocketIO ─────────────────────────────────────────────────────────
app      = Flask(__name__)
app.config["SECRET_KEY"] = "axiom-local-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
_config_lock = threading.Lock()


def emit(event: str, data: dict):
    socketio.emit(event, data)


def _load_config_file() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_config_file(config: dict) -> None:
    """
    Preserve YAML comments/shape when ruamel.yaml is installed. Fall back to
    PyYAML so the UI still works in minimal environments.
    """
    try:
        from ruamel.yaml import YAML
        yaml_rt = YAML()
        yaml_rt.preserve_quotes = True
        with open("config.yaml", encoding="utf-8") as f:
            doc = yaml_rt.load(f)
        _deep_update(doc, config)
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml_rt.dump(doc, f)
    except Exception:
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)


def _deep_update(target, source):
    if not isinstance(target, dict) or not isinstance(source, dict):
        return source
    stale = [k for k in target.keys() if k not in source]
    for key in stale:
        del target[key]
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
    return target


def _apply_config(config: dict) -> None:
    global CFG
    with _config_lock:
        _save_config_file(config)
        CFG = config
        try:
            from voice_assistant import reload_runtime_config
            reload_runtime_config(config)
        except Exception as e:
            emit("log", {"level": "warn", "text": f"Config saved; runtime reload failed: {e}"})
    emit("config_reloaded", {})


def _conversation_history() -> list:
    path = Path(CFG.get("memory", {}).get("file", "memory.json"))
    if not path.exists():
        return []
    try:
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


@app.route("/")
def index():
    return send_file("voice_assistant_ui.html")


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(_load_config_file())


@app.route("/api/config", methods=["POST"])
def api_save_config():
    config = request.get_json(force=True)
    if not isinstance(config, dict):
        return jsonify({"error": "Expected JSON object"}), 400
    _apply_config(config)
    return jsonify({"ok": True, "config": config})


@app.route("/api/projects", methods=["GET", "POST"])
def api_projects():
    config = _load_config_file()
    if request.method == "GET":
        return jsonify(config.get("projects", {}) or {})
    projects = request.get_json(force=True)
    if not isinstance(projects, dict):
        return jsonify({"error": "Expected projects object"}), 400
    config["projects"] = projects
    _apply_config(config)
    return jsonify({"ok": True, "projects": projects})


@app.route("/api/scenarios", methods=["GET", "POST"])
def api_scenarios():
    config = _load_config_file()
    if request.method == "GET":
        return jsonify(config.get("scenarios", {}) or {})
    scenarios = request.get_json(force=True)
    if not isinstance(scenarios, dict):
        return jsonify({"error": "Expected scenarios object"}), 400
    config["scenarios"] = scenarios
    _apply_config(config)
    return jsonify({"ok": True, "scenarios": scenarios})


@app.route("/api/scenarios/run/<name>", methods=["POST"])
def api_run_scenario(name: str):
    payload = request.get_json(silent=True) or {}
    from tools import run_scenario
    result = run_scenario(name, payload.get("project_name", ""))
    return jsonify({"ok": True, "result": result})


@app.route("/api/conversations", methods=["GET"])
def api_conversations():
    limit = int(request.args.get("limit", 100))
    history = _conversation_history()
    return jsonify({"items": history[-limit:], "total": len(history)})


@app.route("/api/test-voice", methods=["POST"])
def api_test_voice():
    payload = request.get_json(force=True)
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"error": "Text is required"}), 400
    threading.Thread(target=lambda: _speak_preview(text), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/calendar/today", methods=["GET"])
def api_calendar_today():
    try:
        from google_calendar import today_events
        return jsonify({"events": today_events(CFG)})
    except Exception as e:
        return jsonify({"events": [], "error": str(e)})


@app.route("/api/calendar/upcoming", methods=["GET"])
def api_calendar_upcoming():
    try:
        days = int(request.args.get("days", 7))
        from google_calendar import upcoming_events
        return jsonify({"events": upcoming_events(days=days, config=CFG)})
    except Exception as e:
        return jsonify({"events": [], "error": str(e)})


@app.route("/api/email/unread", methods=["GET"])
def api_email_unread():
    try:
        import gmail_client
        return jsonify(gmail_client.unread_since_last_check(CFG))
    except Exception as e:
        return jsonify({"count": 0, "items": [], "error": str(e)})


@app.route("/api/email/recent", methods=["GET"])
def api_email_recent():
    try:
        n = int(request.args.get("n", 10))
        import gmail_client
        return jsonify({"items": gmail_client.last_emails(n, CFG)})
    except Exception as e:
        return jsonify({"items": [], "error": str(e)})


@app.route("/api/email/summary", methods=["GET"])
def api_email_summary():
    try:
        import gmail_client
        return jsonify(gmail_client.summarize_inbox(CFG))
    except Exception as e:
        return jsonify({"unread_count": None, "recent": [], "error": str(e)})


@app.route("/api/email/mark_check", methods=["POST"])
def api_email_mark_check():
    try:
        import gmail_client
        state = gmail_client.mark_check_now(CFG)
        return jsonify({"ok": True, **state})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


def _dashboard_schedule() -> dict:
    try:
        google = CFG.get("google", {}) or {}
        if not google.get("enable_calendar", False):
            return {"items": [], "error": "Calendar disabled"}
        token = Path(google.get("token_file") or "secrets/google_token.json")
        if not token.exists():
            return {"items": [], "error": "Calendar not connected"}
        from google_calendar import upcoming_events
        return {"items": upcoming_events(days=3, config=CFG, max_results=3)}
    except Exception as e:
        return {"items": [], "error": str(e)}


def _dashboard_todos() -> dict:
    obsidian = CFG.get("obsidian", {}) or {}
    vault_raw = str(obsidian.get("vault_path") or "").strip()
    if not vault_raw:
        return {"items": [], "error": "Obsidian vault not configured"}
    vault = Path(vault_raw)
    if not vault.exists():
        return {"items": [], "error": "Obsidian vault not configured"}

    scan_paths = obsidian.get("tasks_scan_paths") or []
    roots = [vault / p for p in scan_paths] if scan_paths else [vault]
    items = []
    for root in roots:
        if len(items) >= 5 or not root.exists():
            continue
        for md in root.rglob("*.md"):
            if len(items) >= 5:
                break
            try:
                for line in md.read_text(encoding="utf-8", errors="ignore").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- [ ] "):
                        items.append({
                            "text": stripped[6:].strip(),
                            "source": str(md.relative_to(vault)),
                        })
                        break
            except Exception:
                continue
    return {"items": items}


def _dashboard_projects() -> dict:
    projects = CFG.get("projects", {}) or {}
    items = []
    for key, project in list(projects.items())[:5]:
        items.append({
            "key": key,
            "name": project.get("name") or key,
            "description": project.get("description", ""),
        })
    return {"items": items}


def _dashboard_email() -> dict:
    try:
        gmail = CFG.get("gmail", {}) or {}
        if not gmail.get("enabled", False):
            return {"unread_count": None, "error": "Gmail disabled"}
        import gmail_client
        from google_auth import token_has_scopes
        scopes = gmail.get("scopes") or gmail_client.GMAIL_SCOPES
        if not token_has_scopes(scopes, CFG):
            return {"unread_count": None, "error": "Gmail not connected"}
        summary = gmail_client.summarize_inbox(CFG)
        return {
            "unread_count": summary.get("unread_count"),
            "recent": summary.get("recent", []),
        }
    except Exception as e:
        return {"unread_count": None, "error": str(e)}


@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    return jsonify({
        "schedule": _dashboard_schedule(),
        "todos": _dashboard_todos(),
        "projects": _dashboard_projects(),
        "email": _dashboard_email(),
        "ts": datetime.now().isoformat(timespec="seconds"),
    })


def _speak_preview(text: str) -> None:
    try:
        from voice_assistant import speak
        speak(text)
    except Exception as e:
        emit("error", {"message": f"Voice preview failed: {e}"})


@socketio.on("connect")
def on_connect():
    emit("state", {"state": "idle"})
    emit("log",   {"level": "system", "text": f"AXIOM online - press {CFG['assistant']['hotkey'].upper()} to speak."})


# ─── Assistant loop ───────────────────────────────────────────────────────────

def assistant_loop():
    from voice_assistant import (
        ASSISTANT_NAME,
        ask_ai,
        init_scenario_engine,
        load_history,
        record_audio,
        request_activation,
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
    pending_activation = False

    def activate_from_hotkey():
        emit("log", {"level": "system", "text": f"Hotkey {hotkey.upper()} pressed."})
        request_activation("hotkey")

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
        if pending_activation:
            pending_activation = False
        elif hotkey_registered or wake_started:
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
        pending_activation = speak(reply)
        if pending_activation:
            emit("log", {"level": "system", "text": "Listening again after interruption."})

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
    electron_mode = os.environ.get("AXIOM_ELECTRON") == "1"

    # Assistant runs in a background thread
    t = threading.Thread(target=assistant_loop, daemon=True)
    t.start()

    # Open browser after server is up
    if CFG["server"]["open_browser"] and not electron_mode:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()

    # System tray runs in another thread (if pystray available)
    if not electron_mode:
        tray_thread = threading.Thread(target=_make_tray_icon, daemon=True)
        tray_thread.start()

    print(f"[AXIOM] UI at http://{HOST}:{PORT}")
    socketio.run(
        app,
        host=HOST,
        port=PORT,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
