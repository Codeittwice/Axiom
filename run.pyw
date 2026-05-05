"""
AXIOM — silent launcher (no console window).
Run with:  pythonw run.pyw
The system tray icon appears in the taskbar; double-click to open the UI.
"""
import os
import sys

# Ensure working directory is this file's directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Delegate entirely to server.py
import server  # noqa: F401 — runs __main__ block via import side-effect

# server.py's __main__ block only runs when invoked directly, so call it:
if __name__ != "__main__":
    # This file was imported — boot the server manually
    import threading, webbrowser, yaml
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    t = threading.Thread(target=server.assistant_loop, daemon=True)
    t.start()
    if cfg["server"]["open_browser"]:
        threading.Timer(1.5, lambda: webbrowser.open(
            f"http://{cfg['server']['host']}:{cfg['server']['port']}"
        )).start()
    tray = threading.Thread(target=server._make_tray_icon, daemon=True)
    tray.start()
    server.socketio.run(
        server.app,
        host=cfg["server"]["host"],
        port=cfg["server"]["port"],
        debug=False,
        use_reloader=False,
    )
