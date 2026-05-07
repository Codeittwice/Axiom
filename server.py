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


def _email_connection_error() -> str:
    gmail = CFG.get("gmail", {}) or {}
    if not gmail.get("enabled", False):
        return "Gmail disabled"
    try:
        import gmail_client
        if gmail_client.has_connection(CFG):
            return ""
    except Exception as e:
        return str(e)
    return "Gmail not connected"


@app.route("/api/email/connect", methods=["POST"])
def api_email_connect():
    try:
        import gmail_client
        profile = gmail_client.connect(CFG)
        return jsonify({"ok": True, **profile})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/email/unread", methods=["GET"])
def api_email_unread():
    try:
        error = _email_connection_error()
        if error:
            return jsonify({"count": 0, "items": [], "error": error})
        import gmail_client
        return jsonify(gmail_client.unread_since_last_check(CFG))
    except Exception as e:
        return jsonify({"count": 0, "items": [], "error": str(e)})


@app.route("/api/email/recent", methods=["GET"])
def api_email_recent():
    try:
        error = _email_connection_error()
        if error:
            return jsonify({"items": [], "error": error})
        n = int(request.args.get("n", 10))
        import gmail_client
        return jsonify({"items": gmail_client.last_emails(n, CFG)})
    except Exception as e:
        return jsonify({"items": [], "error": str(e)})


@app.route("/api/email/summary", methods=["GET"])
def api_email_summary():
    try:
        error = _email_connection_error()
        if error:
            return jsonify({"unread_count": None, "recent": [], "error": error})
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


@app.route("/api/spotify/status", methods=["GET"])
def api_spotify_status():
    try:
        import spotify_client
        return jsonify(spotify_client.status(CFG))
    except Exception as e:
        return jsonify({"enabled": False, "connected": False, "error": str(e)})


@app.route("/api/spotify/connect", methods=["POST"])
def api_spotify_connect():
    try:
        import spotify_client
        return jsonify({"ok": True, **spotify_client.connect(CFG)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


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
    try:
        import obsidian_tasks
        return {"items": obsidian_tasks.scan_tasks(CFG, status="open", limit=5)}
    except Exception as e:
        return {"items": [], "error": str(e)}


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
        return {
            "unread_count": gmail_client.unread_count(CFG),
            "recent": gmail_client.last_emails(4, CFG),
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


@app.route("/api/obsidian/tasks", methods=["GET"])
def api_obsidian_tasks():
    try:
        import obsidian_tasks
        status = request.args.get("status", "open")
        limit = int(request.args.get("limit", 20))
        return jsonify({"items": obsidian_tasks.scan_tasks(CFG, status=status, limit=limit)})
    except Exception as e:
        return jsonify({"items": [], "error": str(e)})


@app.route("/api/obsidian/today", methods=["GET"])
def api_obsidian_today():
    try:
        import obsidian_tasks
        limit = int(request.args.get("limit", 20))
        return jsonify({"items": obsidian_tasks.today_tasks(CFG, limit=limit)})
    except Exception as e:
        return jsonify({"items": [], "error": str(e)})


@app.route("/api/obsidian/capture", methods=["POST"])
def api_obsidian_capture():
    try:
        import obsidian_tasks
        payload = request.get_json(force=True)
        task = obsidian_tasks.capture_task(
            CFG,
            str(payload.get("text", "")),
            str(payload.get("due", "")),
            str(payload.get("priority", "")),
            str(payload.get("project", "")),
            str(payload.get("course", "")),
        )
        return jsonify({"ok": True, "task": task})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/obsidian/tasks/<task_id>/complete", methods=["POST"])
def api_obsidian_complete(task_id: str):
    try:
        import obsidian_tasks
        return jsonify({"ok": True, "task": obsidian_tasks.complete_task(CFG, task_id)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/obsidian/tasks/<task_id>/reschedule", methods=["POST"])
def api_obsidian_reschedule(task_id: str):
    try:
        import obsidian_tasks
        payload = request.get_json(force=True)
        due = str(payload.get("due", ""))
        return jsonify({"ok": True, "task": obsidian_tasks.reschedule_task(CFG, task_id, due)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def _speak_preview(text: str) -> None:
    try:
        from voice_assistant import speak
        speak(text)
    except Exception as e:
        emit("error", {"message": f"Voice preview failed: {e}"})


# ─── Learning API endpoints ────────────────────────────────────────────────────

@app.route("/api/suggestions", methods=["GET"])
def api_suggestions():
    import json
    p = Path("data/suggestions.json")
    if not p.exists():
        return jsonify({"items": []})
    with open(p, encoding="utf-8") as f:
        items = json.load(f)
    if isinstance(items, dict):
        items = items.get("items", [])
    status_filter = request.args.get("status")
    if status_filter:
        items = [s for s in items if s.get("status") == status_filter]
    return jsonify({"items": items})


@app.route("/api/suggestions/<suggestion_id>/approve", methods=["POST"])
def api_approve_suggestion(suggestion_id: str):
    import json
    p = Path("data/suggestions.json")
    if not p.exists():
        return jsonify({"error": "No suggestions file"}), 404
    with open(p, encoding="utf-8") as f:
        items = json.load(f)
    if isinstance(items, dict):
        items = items.get("items", [])
    for s in items:
        if s.get("id") == suggestion_id:
            s["status"] = "approved"
            s["user_notes"] = (request.get_json(silent=True) or {}).get("notes", "")
            break
    else:
        return jsonify({"error": "Not found"}), 404
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    _update_user_model_approval(suggestion_id, approved=True)
    socketio.emit("suggestion_approved", {"id": suggestion_id})
    return jsonify({"ok": True})


@app.route("/api/suggestions/<suggestion_id>/reject", methods=["POST"])
def api_reject_suggestion(suggestion_id: str):
    import json
    p = Path("data/suggestions.json")
    if not p.exists():
        return jsonify({"error": "No suggestions file"}), 404
    with open(p, encoding="utf-8") as f:
        items = json.load(f)
    if isinstance(items, dict):
        items = items.get("items", [])
    for s in items:
        if s.get("id") == suggestion_id:
            s["status"] = "rejected"
            break
    else:
        return jsonify({"error": "Not found"}), 404
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    _update_user_model_approval(suggestion_id, approved=False)
    return jsonify({"ok": True})


@app.route("/api/user-model", methods=["GET"])
def api_user_model():
    import json
    p = Path("data/user_model.json")
    if not p.exists():
        return jsonify({})
    with open(p, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/reflect", methods=["POST"])
def api_reflect():
    threading.Thread(target=_run_reflection_bg, daemon=True).start()
    return jsonify({"ok": True, "message": "Reflection started in background."})


@app.route("/api/skill-registry", methods=["GET"])
def api_skill_registry():
    from reflection import build_skill_registry
    return jsonify(build_skill_registry(CFG))


@socketio.on("connect")
def on_connect():
    emit("state", {"state": "idle"})
    emit("log",   {"level": "system", "text": f"AXIOM online - press {CFG['assistant']['hotkey'].upper()} to speak."})


# ─── Self-learning helpers ────────────────────────────────────────────────────

_sessions_since_reflect = 0


def _check_auto_reflect(cfg: dict) -> None:
    global _sessions_since_reflect
    learning = cfg.get("learning", {}) or {}
    if not learning.get("reflection_enabled", True):
        return
    threshold = int(learning.get("auto_reflect_after_sessions", 10))
    _sessions_since_reflect += 1
    if _sessions_since_reflect >= threshold:
        _sessions_since_reflect = 0
        threading.Thread(target=_run_reflection_bg, daemon=True).start()


def _run_reflection_bg() -> None:
    try:
        from reflection import run_reflection
        suggestions = run_reflection(CFG)
        if suggestions:
            emit("log", {"level": "system", "text": f"Reflection complete: {len(suggestions)} new suggestion(s)."})
            socketio.emit("suggestions_updated", {"count": len(suggestions)})
    except Exception as e:
        print(f"[AXIOM] Reflection error: {e}")


def _update_user_model_approval(suggestion_id: str, approved: bool) -> None:
    import json
    p = Path("data/user_model.json")
    model: dict = {}
    if p.exists():
        with open(p, encoding="utf-8") as f:
            model = json.load(f)
    key = "approved_suggestions" if approved else "rejected_suggestions"
    lst = model.setdefault(key, [])
    if suggestion_id not in lst:
        lst.append(suggestion_id)
    model["last_updated"] = datetime.now().isoformat()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, ensure_ascii=False)


# ─── Assistant loop ───────────────────────────────────────────────────────────

def assistant_loop():
    from voice_assistant import (
        ASSISTANT_NAME,
        ask_ai,
        expects_follow_up,
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
    conversation_open_until = 0.0

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
        conversation_cfg = CFG.get("conversation", {}) or {}
        follow_up_enabled = bool(conversation_cfg.get("follow_up_listening", True))
        follow_up_timeout = float(conversation_cfg.get("follow_up_timeout_seconds", 120) or 120)
        conversation_open = follow_up_enabled and time.monotonic() < conversation_open_until

        # Wait for hotkey or wake word
        if pending_activation:
            pending_activation = False
        elif conversation_open:
            pass
        elif hotkey_registered or wake_started:
            _wake_event.clear()
            _wake_event.wait()
        else:
            keyboard.wait(hotkey)
        time.sleep(0.05)

        # --- Record ---
        session_start = time.time()
        wait_for_speech = None
        if conversation_open:
            wait_for_speech = max(1, conversation_open_until - time.monotonic())
            emit("log", {"level": "system", "text": "Listening for your reply."})
        audio_path = record_audio(wait_for_speech_seconds=wait_for_speech)
        if not audio_path:
            if conversation_open:
                conversation_open_until = 0.0
                emit("log", {"level": "system", "text": "Follow-up window closed. Wake word or hotkey required again."})
                emit("state", {"state": "idle"})
                continue
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
            result = ask_ai(text, history, speak_response=True)
            reply = result.reply
            history = result.history
            tools_called = result.tools_called
            save_history(history)
            emit("response", {"text": reply})
        except Exception as e:
            msg = f"Error communicating with Gemini: {e}"
            print(f"[AXIOM] {msg}")
            emit("log",   {"level": "error", "text": msg})
            emit("state", {"state": "idle"})
            continue

        # --- Speak ---
        pending_activation = result.interrupted if result.spoke else speak(reply)
        if pending_activation:
            emit("log", {"level": "system", "text": "Listening again after interruption."})
            conversation_open_until = 0.0
        elif follow_up_enabled and expects_follow_up(reply):
            conversation_open_until = time.monotonic() + follow_up_timeout
            emit("log", {"level": "system", "text": f"Follow-up listening open for {int(follow_up_timeout)} seconds."})
        else:
            conversation_open_until = 0.0

        # --- Log session ---
        try:
            from session_logger import log_session
            _duration = round(time.time() - session_start, 2)
            log_session(text, reply, tools_called, _duration)
            _check_auto_reflect(CFG)
        except Exception as e:
            emit("log", {"level": "warn", "text": f"Session log failed: {e}"})

        # --- Crystallise brain memory ---
        try:
            from brain import crystallise
            crystallise(text, reply, tools_called, CFG, _duration)
        except Exception as e:
            emit("log", {"level": "warn", "text": f"Brain crystallise failed: {e}"})

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

    try:
        from brain import init_brain
        init_brain(CFG)
    except Exception as _brain_err:
        print(f"[AXIOM] Brain init skipped: {_brain_err}")

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
