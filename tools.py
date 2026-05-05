"""
AXIOM Tool Use — all tool implementations.

To add a new tool:
  1. Add its declaration to GEMINI_TOOLS (function_declarations list)
  2. Add its handler in execute_tool()
  3. Implement the function below
"""

import io
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

import yaml

# ─── Load config (tools need repos, websites, obsidian paths) ─────────────────
with open("config.yaml") as _f:
    _CFG = yaml.safe_load(_f)

_REPOS    = _CFG.get("repos",    {})
_WEBSITES = _CFG.get("websites", {})
_OBSIDIAN = _CFG.get("obsidian", {})

# ── Scenario engine handle (set by voice_assistant.init_scenario_engine) ──
_scenario_engine = None

def set_scenario_engine(engine) -> None:
    """Called once at startup by voice_assistant.py to wire the engine."""
    global _scenario_engine
    _scenario_engine = engine


# ── Project registry handle (Phase 2 — set by init_project_registry) ──────
_project_registry = None

def set_project_registry(registry) -> None:
    """Called once at startup by voice_assistant.py to wire the registry."""
    global _project_registry
    _project_registry = registry


def reload_config(config: dict) -> None:
    """Hot-reload cached config sections after the settings UI saves YAML."""
    global _CFG, _REPOS, _WEBSITES, _OBSIDIAN
    _CFG = config
    _REPOS    = _CFG.get("repos",    {})
    _WEBSITES = _CFG.get("websites", {})
    _OBSIDIAN = _CFG.get("obsidian", {})

# ─── Gemini tool declarations ─────────────────────────────────────────────────

GEMINI_TOOLS = [{
    "function_declarations": [

        # ── Web & Info ──────────────────────────────────────────────────────
        {
            "name": "search_web",
            "description": "Search the web for current information, news, facts, or live data not in training data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "get_datetime",
            "description": "Get the current local date and time.",
            "parameters": {"type": "object", "properties": {}}
        },
        {
            "name": "get_weather",
            "description": "Get current weather for a city or location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name, e.g. 'London' or 'New York'"}
                },
                "required": ["location"]
            }
        },
        {
            "name": "get_wikipedia",
            "description": "Get a concise Wikipedia summary about a person, place, concept, or event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to look up on Wikipedia"}
                },
                "required": ["topic"]
            }
        },

        # ── Apps & Websites ─────────────────────────────────────────────────
        {
            "name": "open_application",
            "description": "Open a Windows application by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "App to open, e.g. notepad, calculator, chrome, spotify, vscode"
                    }
                },
                "required": ["app_name"]
            }
        },
        {
            "name": "open_website",
            "description": "Open a website or named shortcut in the default browser. Use for 'open GitHub', 'open my email', or any URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "A named shortcut (github, email, youtube, claude, chatgpt, calendar) or a full URL"
                    }
                },
                "required": ["target"]
            }
        },
        {
            "name": "run_scenario",
            "description": (
                "Run a multi-step workflow scenario by name. "
                "Use for named workflows like 'start coding sequence', "
                "'run morning routine', 'wrap up'. "
                "Pass project_name when the scenario operates on a specific project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scenario_name": {
                        "type": "string",
                        "description": "Scenario key from config, e.g. 'coding_sequence', 'morning_routine'"
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Optional project key when scenario uses {project_name}, e.g. 'axiom'"
                    }
                },
                "required": ["scenario_name"]
            }
        },

        # ── Projects (Phase 2) ──────────────────────────────────────────────
        {
            "name": "list_projects",
            "description": "List all configured projects with names, paths, and descriptions. Use when the user asks 'what projects do I have' or 'show my projects'.",
            "parameters": {"type": "object", "properties": {}}
        },
        {
            "name": "project_status",
            "description": "Get the current status of a project: branch, uncommitted file count, description. Use for 'how is X doing', 'what's the state of X', or 'project status'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Name, alias, or fuzzy match of the project"
                    }
                },
                "required": ["project_name"]
            }
        },
        {
            "name": "switch_project",
            "description": "Set a project as the active one for this session. Future references to 'it', 'the project', or 'the repo' will resolve to this one. Use for 'switch to X' or 'work on X'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Name, alias, or fuzzy match of the project"
                    }
                },
                "required": ["project_name"]
            }
        },

        # ── Developer / Git ─────────────────────────────────────────────────
        {
            "name": "open_repo",
            "description": "Open a code repository in VS Code by its short name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "Short name of the repo as defined in config, e.g. 'axiom'"
                    }
                },
                "required": ["repo_name"]
            }
        },
        {
            "name": "run_git",
            "description": "Run a git command in a named repo. Use for status, pull, push, commit, log.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The git subcommand and args, e.g. 'status', 'pull', 'log --oneline -5', 'commit -m \"fix bug\"'"
                    },
                    "repo_name": {
                        "type": "string",
                        "description": "Short repo name from config. Leave blank to use current directory."
                    }
                },
                "required": ["command"]
            }
        },
        {
            "name": "run_terminal",
            "description": "Run a terminal/shell command in a named repo directory. Use for builds, tests, npm, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run, e.g. 'npm install', 'pytest', 'python -m build'"
                    },
                    "repo_name": {
                        "type": "string",
                        "description": "Short repo name to run in. Leave blank for current directory."
                    }
                },
                "required": ["command"]
            }
        },
        {
            "name": "describe_screen",
            "description": "Take a screenshot and describe what is on the screen using vision AI. Use when asked 'what's on my screen', 'explain this error', or 'what does this code do'.",
            "parameters": {"type": "object", "properties": {}}
        },

        # ── Obsidian Notes ──────────────────────────────────────────────────
        {
            "name": "create_note",
            "description": "Create a new note in the Obsidian vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Note title (becomes the filename)"},
                    "content": {"type": "string", "description": "Note body in plain text or markdown"}
                },
                "required": ["title", "content"]
            }
        },
        {
            "name": "read_note",
            "description": "Read an existing note from the Obsidian vault by title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The note title to read"}
                },
                "required": ["title"]
            }
        },
        {
            "name": "append_daily_note",
            "description": "Add a bullet point to today's daily note in Obsidian. Use for quick logging: 'add to today's note', 'log this idea'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Text to append as a bullet point"}
                },
                "required": ["content"]
            }
        },
        {
            "name": "search_notes",
            "description": "Search all notes in the Obsidian vault for a keyword or phrase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword or phrase to search for"}
                },
                "required": ["query"]
            }
        },

        # ── System ──────────────────────────────────────────────────────────
        {
            "name": "set_volume",
            "description": "Set the system audio volume. Use for 'set volume to 50', 'mute', 'turn it up'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "Volume level 0–100. Use 0 for mute."
                    }
                },
                "required": ["level"]
            }
        },
        {
            "name": "set_timer",
            "description": "Set a countdown timer. Shows a Windows notification and speaks when done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {
                        "type": "number",
                        "description": "Duration in minutes, e.g. 25 for a Pomodoro"
                    },
                    "label": {
                        "type": "string",
                        "description": "Optional label for the timer, e.g. 'Pomodoro', 'Lunch break'"
                    }
                },
                "required": ["minutes"]
            }
        },

        # ── Clipboard ───────────────────────────────────────────────────────
        {
            "name": "read_clipboard",
            "description": "Read the current text content of the clipboard.",
            "parameters": {"type": "object", "properties": {}}
        },
        {
            "name": "write_clipboard",
            "description": "Write text to the clipboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to copy to clipboard"}
                },
                "required": ["text"]
            }
        },
    ]
}]

# ─── App name map ─────────────────────────────────────────────────────────────

_APP_MAP = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "chrome": "chrome",
    "google chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "spotify": "spotify",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "explorer": "explorer",
    "file explorer": "explorer",
    "cmd": "cmd.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "discord": "discord",
    "slack": "slack",
    "teams": "msteams",
    "zoom": "zoom",
    "obs": "obs64",
}

# ─── Tool implementations ─────────────────────────────────────────────────────

def search_web(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results:
            return "No results found."
        return "\n\n---\n\n".join(f"{r['title']}\n{r['body']}" for r in results)
    except Exception as e:
        return f"Search failed: {e}"


def get_datetime() -> str:
    return datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")


def get_weather(location: str) -> str:
    try:
        import urllib.request
        url = f"https://wttr.in/{location.replace(' ', '+')}?format=3"
        req = urllib.request.Request(url, headers={"User-Agent": "AXIOM/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.read().decode().strip()
    except Exception as e:
        return f"Could not fetch weather: {e}"


def get_wikipedia(topic: str) -> str:
    try:
        import wikipedia
        wikipedia.set_lang("en")
        summary = wikipedia.summary(topic, sentences=3, auto_suggest=True)
        return summary
    except Exception as e:
        return f"Wikipedia lookup failed: {e}"


def open_application(app_name: str) -> str:
    try:
        cmd = _APP_MAP.get(app_name.lower().strip(), app_name)
        subprocess.Popen(cmd, shell=True)
        return f"Opened {app_name}."
    except Exception as e:
        return f"Could not open '{app_name}': {e}"


def open_website(target: str) -> str:
    url = _WEBSITES.get(target.lower().strip(), target)
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {target}."


def run_scenario(scenario_name: str, project_name: str = "") -> str:
    """
    Run a multi-step scenario via the ScenarioEngine.
    Falls back to a basic open_website loop if the engine isn't initialized.
    """
    key = scenario_name.lower().strip().replace(" ", "_")

    if _scenario_engine is not None:
        context = {"project_name": project_name} if project_name else {}
        return _scenario_engine.run(key, context)

    # Fallback if engine not yet wired (e.g. early startup)
    scenarios = _CFG.get("scenarios", {})
    scenario  = scenarios.get(key)
    if not scenario:
        available = ", ".join(scenarios.keys()) or "none"
        return f"Scenario '{scenario_name}' not found. Available: {available}"
    for tab in scenario.get("tabs", []):
        open_website(tab)
    return f"Opened scenario: {scenario.get('description', scenario_name)}"


def open_repo(repo_name: str) -> str:
    """Open a repo in VS Code. Uses ProjectRegistry when available (fuzzy match)."""
    if _project_registry is not None:
        project = _project_registry.resolve(repo_name)
        if project and project.get("repo_path"):
            subprocess.Popen(f'code "{project["repo_path"]}"', shell=True)
            return f"Opened {project['name']} in VS Code."

    # Legacy fallback
    key  = repo_name.lower().strip()
    path = _REPOS.get(key)
    if not path:
        available = ", ".join(_REPOS.keys()) if _REPOS else "none configured"
        return f"Repo '{repo_name}' not found. Configured repos: {available}"
    subprocess.Popen(f'code "{path}"', shell=True)
    return f"Opened {repo_name} in VS Code."


# ── Project tools (Phase 2) ───────────────────────────────────────────────────

def list_projects() -> str:
    if _project_registry is None:
        return "Project registry not initialized."
    projects = _project_registry.list_projects()
    if not projects:
        return "No projects configured."
    lines = []
    for p in projects:
        line = f"- {p['name']}"
        if p.get("description"):
            line += f": {p['description']}"
        lines.append(line)
    return "\n".join(lines)


def project_status(project_name: str) -> str:
    if _project_registry is None:
        return "Project registry not initialized."
    project = _project_registry.resolve(project_name)
    if not project:
        available = ", ".join(p["name"] for p in _project_registry.list_projects())
        return f"Project '{project_name}' not found. Known: {available}"
    return _project_registry.status(project)


def switch_project(project_name: str) -> str:
    if _project_registry is None:
        return "Project registry not initialized."
    project = _project_registry.set_active(project_name)
    if not project:
        return f"Could not resolve project '{project_name}'."
    return f"Active project: {project['name']}."


def run_git(command: str, repo_name: str = "") -> str:
    cwd = _resolve_repo_path(repo_name)
    if isinstance(cwd, str) and cwd.startswith("Error"):
        return cwd
    result = subprocess.run(
        f"git {command}", shell=True,
        capture_output=True, text=True, cwd=cwd
    )
    output = (result.stdout + result.stderr).strip()
    return (output[:600] + "…") if len(output) > 600 else output or "Done."


def run_terminal(command: str, repo_name: str = "") -> str:
    cwd = _resolve_repo_path(repo_name)
    if isinstance(cwd, str) and cwd.startswith("Error"):
        return cwd
    result = subprocess.run(
        command, shell=True,
        capture_output=True, text=True, cwd=cwd
    )
    output = (result.stdout + result.stderr).strip()
    return (output[:600] + "…") if len(output) > 600 else output or "Done."


def _resolve_repo_path(repo_name: str):
    if not repo_name:
        return "."
    path = _REPOS.get(repo_name.lower().strip())
    if not path:
        available = ", ".join(_REPOS.keys()) if _REPOS else "none configured"
        return f"Error: repo '{repo_name}' not found. Configured: {available}"
    return path


def describe_screen() -> str:
    try:
        import google.generativeai as genai
        from PIL import ImageGrab
        screenshot = ImageGrab.grab()
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        buf.seek(0)
        model    = genai.GenerativeModel(_CFG["gemini"]["model"])
        response = model.generate_content([
            "Describe what is on this screen concisely and clearly. "
            "Focus on the most important content visible.",
            {"mime_type": "image/png", "data": buf.read()}
        ])
        return response.text.strip()
    except Exception as e:
        return f"Screen description failed: {e}"


# ── Obsidian ──────────────────────────────────────────────────────────────────

def _vault_path() -> Path | None:
    vp = _OBSIDIAN.get("vault_path", "").strip()
    return Path(vp) if vp else None


def create_note(title: str, content: str) -> str:
    vault = _vault_path()
    if not vault:
        return "Obsidian vault not configured. Set obsidian.vault_path in config.yaml."
    path = vault / f"{title}.md"
    path.write_text(f"# {title}\n\n{content}", encoding="utf-8")
    return f"Note '{title}' created in Obsidian vault."


def read_note(title: str) -> str:
    vault = _vault_path()
    if not vault:
        return "Obsidian vault not configured."
    matches = list(vault.rglob(f"{title}.md"))
    if not matches:
        return f"No note found with title '{title}'."
    return matches[0].read_text(encoding="utf-8")[:1500]


def append_daily_note(content: str) -> str:
    vault = _vault_path()
    if not vault:
        return "Obsidian vault not configured."
    folder = _OBSIDIAN.get("daily_notes_folder", "").strip()
    today  = datetime.now().strftime("%Y-%m-%d")
    base   = vault / folder if folder else vault
    base.mkdir(parents=True, exist_ok=True)
    path   = base / f"{today}.md"
    ts     = datetime.now().strftime("%H:%M")
    with open(path, "a", encoding="utf-8") as f:
        if not path.exists() or path.stat().st_size == 0:
            f.write(f"# {today}\n\n")
        f.write(f"- {ts} {content}\n")
    return f"Added to daily note {today}."


def search_notes(query: str) -> str:
    vault = _vault_path()
    if not vault:
        return "Obsidian vault not configured."
    results = []
    for md in vault.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
            if query.lower() in text.lower():
                for line in text.splitlines():
                    if query.lower() in line.lower():
                        results.append(f"**{md.stem}**: {line.strip()[:100]}")
                        break
        except Exception:
            continue
    if not results:
        return f"No notes found containing '{query}'."
    return "\n".join(results[:8])


# ── System ────────────────────────────────────────────────────────────────────

def set_volume(level: int) -> str:
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices   = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume    = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(max(0, min(100, level)) / 100.0, None)
        return "Muted." if level == 0 else f"Volume set to {level}%."
    except Exception as e:
        return f"Volume control failed: {e}"


# Active timers — kept in memory so they can be cancelled later
_active_timers: dict = {}


def set_timer(minutes: float, label: str = "Timer") -> str:
    import threading
    label = label or "Timer"

    def fire():
        try:
            from plyer import notification
            notification.notify(
                title="AXIOM",
                message=f"{label} — time's up!",
                app_name="AXIOM",
                timeout=15,
            )
        except Exception:
            pass
        _active_timers.pop(label, None)

    t = threading.Timer(minutes * 60, fire)
    t.daemon = True
    t.start()
    _active_timers[label] = t
    mins_str = f"{int(minutes)}m" if minutes == int(minutes) else f"{minutes}m"
    return f"Timer '{label}' set for {mins_str}."


# ── Clipboard ─────────────────────────────────────────────────────────────────

def read_clipboard() -> str:
    try:
        import pyperclip
        text = pyperclip.paste()
        return text[:800] if text else "Clipboard is empty."
    except Exception as e:
        return f"Could not read clipboard: {e}"


def write_clipboard(text: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(text)
        return "Copied to clipboard."
    except Exception as e:
        return f"Could not write to clipboard: {e}"


# ─── Dispatcher ───────────────────────────────────────────────────────────────

def execute_tool(name: str, inputs: dict) -> str:
    dispatch = {
        "search_web":       lambda i: search_web(i["query"]),
        "get_datetime":     lambda i: get_datetime(),
        "get_weather":      lambda i: get_weather(i["location"]),
        "get_wikipedia":    lambda i: get_wikipedia(i["topic"]),
        "open_application": lambda i: open_application(i["app_name"]),
        "open_website":     lambda i: open_website(i["target"]),
        "run_scenario":     lambda i: run_scenario(i["scenario_name"], i.get("project_name", "")),
        "open_repo":        lambda i: open_repo(i["repo_name"]),
        "list_projects":    lambda i: list_projects(),
        "project_status":   lambda i: project_status(i["project_name"]),
        "switch_project":   lambda i: switch_project(i["project_name"]),
        "run_git":          lambda i: run_git(i["command"], i.get("repo_name", "")),
        "run_terminal":     lambda i: run_terminal(i["command"], i.get("repo_name", "")),
        "describe_screen":  lambda i: describe_screen(),
        "create_note":      lambda i: create_note(i["title"], i["content"]),
        "read_note":        lambda i: read_note(i["title"]),
        "append_daily_note":lambda i: append_daily_note(i["content"]),
        "search_notes":     lambda i: search_notes(i["query"]),
        "set_volume":       lambda i: set_volume(int(i["level"])),
        "set_timer":        lambda i: set_timer(float(i["minutes"]), i.get("label", "Timer")),
        "read_clipboard":   lambda i: read_clipboard(),
        "write_clipboard":  lambda i: write_clipboard(i["text"]),
    }
    handler = dispatch.get(name)
    if not handler:
        return f"Unknown tool: {name}"
    try:
        return handler(inputs)
    except Exception as e:
        return f"Tool '{name}' error: {e}"
