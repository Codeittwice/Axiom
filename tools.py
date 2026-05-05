"""
AXIOM Tool Use — all tool implementations.

To add a new tool:
  1. Add its declaration to GEMINI_TOOLS (function_declarations list)
  2. Add its handler in execute_tool()
  3. Implement the function below
"""

import io
import json
import os
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

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
        # Calendar (Phase 6a)
        {
            "name": "today_schedule",
            "description": "Read today's Google Calendar schedule. Use for 'what's on my schedule today' or 'what do I have today'.",
            "parameters": {"type": "object", "properties": {}}
        },
        {
            "name": "next_event",
            "description": "Read the next upcoming Google Calendar event. Use for 'what's my next meeting' or 'what's next on my calendar'.",
            "parameters": {"type": "object", "properties": {}}
        },
        {
            "name": "list_events",
            "description": "List Google Calendar events between two dates or datetimes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "Start date/time, ISO or natural language"},
                    "end": {"type": "string", "description": "End date/time, ISO or natural language"}
                },
                "required": ["start", "end"]
            }
        },
        {
            "name": "create_event",
            "description": "Create a Google Calendar event from a title, natural language time, and optional duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "when": {"type": "string", "description": "When the event starts, e.g. 'tomorrow at 2pm'"},
                    "duration_minutes": {"type": "integer", "description": "Duration in minutes; defaults to 60"}
                },
                "required": ["title", "when"]
            }
        },

        # Spotify (Phase 6 old advanced tools)
        {
            "name": "spotify_play",
            "description": "Search Spotify and play a track. Use for 'play lo-fi on Spotify' or 'play {song}'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Song, artist, album, or search phrase"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "spotify_control",
            "description": "Control Spotify playback. Actions: play, pause, next, previous, volume_up, volume_down.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "play, pause, next, previous, volume_up, volume_down"}
                },
                "required": ["action"]
            }
        },
        {
            "name": "spotify_now_playing",
            "description": "Tell the user what Spotify is currently playing.",
            "parameters": {"type": "object", "properties": {}}
        },

        # Code intelligence (Phase 6 old advanced tools)
        {
            "name": "create_file",
            "description": "Create a new file inside a configured project repository. Does not overwrite existing files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path inside the repo"},
                    "content": {"type": "string", "description": "File contents"},
                    "repo_name": {"type": "string", "description": "Optional project/repo name; defaults to active project or current repo"}
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "read_file",
            "description": "Read a file from a configured project repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path inside the repo"},
                    "repo_name": {"type": "string", "description": "Optional project/repo name; defaults to active project or current repo"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "search_codebase",
            "description": "Search code/text files inside a configured project repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for"},
                    "repo_name": {"type": "string", "description": "Optional project/repo name; defaults to active project or current repo"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "summarize_diff",
            "description": "Summarize the current git diff in a configured project repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string", "description": "Optional project/repo name; defaults to active project or current repo"}
                }
            }
        },
        {
            "name": "explain_file",
            "description": "Explain a source file from a configured project repository using Gemini when available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path inside the repo"},
                    "repo_name": {"type": "string", "description": "Optional project/repo name; defaults to active project or current repo"}
                },
                "required": ["path"]
            }
        },

        # Email triage (Phase 6 old advanced tools)
        {
            "name": "unread_count",
            "description": "Read the number of unread Gmail messages.",
            "parameters": {"type": "object", "properties": {}}
        },
        {
            "name": "last_emails",
            "description": "Read senders, subjects, and short snippets for the latest Gmail messages. Never returns full bodies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Number of recent emails, default 5"}
                }
            }
        },
        {
            "name": "summarize_inbox",
            "description": "Summarize Gmail unread count and the latest few email subjects/snippets.",
            "parameters": {"type": "object", "properties": {}}
        },

        # Smart home (Phase 6 old advanced tools)
        {
            "name": "ha_get_state",
            "description": "Get a Home Assistant entity state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "Entity id, e.g. light.office"}
                },
                "required": ["entity_id"]
            }
        },
        {
            "name": "ha_call_service",
            "description": "Call a Home Assistant service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Service domain, e.g. light"},
                    "service": {"type": "string", "description": "Service name, e.g. turn_on"},
                    "data": {"type": "object", "description": "Service data JSON"}
                },
                "required": ["domain", "service"]
            }
        },

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


def _calendar_enabled() -> bool:
    return bool((_CFG.get("google", {}) or {}).get("enable_calendar", False))


def _event_time_label(value: str) -> str:
    if not value:
        return ""
    try:
        raw = value.replace("Z", "+00:00")
        if "T" not in raw:
            return raw
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%a %b %d, %I:%M %p").replace(" 0", " ")
    except Exception:
        return value


def _event_line(event: dict) -> str:
    title = event.get("title") or "Untitled event"
    start = _event_time_label(event.get("start", ""))
    location = event.get("location") or ""
    bits = [title]
    if start:
        bits.append(start)
    if location:
        bits.append(location)
    return " - ".join(bits)


def today_schedule() -> str:
    if not _calendar_enabled():
        return "Google Calendar is disabled. Enable google.enable_calendar in config.yaml."
    try:
        import google_calendar
        events = google_calendar.today_events(_CFG)
    except Exception as e:
        return f"Could not read today's schedule: {e}"
    if not events:
        return "No calendar events today."
    lines = [_event_line(event) for event in events[:8]]
    if len(events) > 8:
        lines.append(f"and {len(events) - 8} more")
    return "Today's schedule:\n" + "\n".join(f"- {line}" for line in lines)


def next_event() -> str:
    if not _calendar_enabled():
        return "Google Calendar is disabled. Enable google.enable_calendar in config.yaml."
    try:
        import google_calendar
        event = google_calendar.next_event(_CFG)
    except Exception as e:
        return f"Could not read the next event: {e}"
    if not event:
        return "No upcoming calendar events found."
    return f"Next event: {_event_line(event)}."


def list_events(start: str, end: str) -> str:
    if not _calendar_enabled():
        return "Google Calendar is disabled. Enable google.enable_calendar in config.yaml."
    try:
        import google_calendar
        events = google_calendar.list_events(start, end, _CFG, max_results=12)
    except Exception as e:
        return f"Could not list calendar events: {e}"
    if not events:
        return "No calendar events found in that range."
    lines = [_event_line(event) for event in events[:8]]
    if len(events) > 8:
        lines.append(f"and {len(events) - 8} more")
    return "Calendar events:\n" + "\n".join(f"- {line}" for line in lines)


def create_event(title: str, when: str, duration_minutes: int = 60) -> str:
    if not _calendar_enabled():
        return "Google Calendar is disabled. Enable google.enable_calendar in config.yaml."
    try:
        import google_calendar
        event = google_calendar.create_event(title, when, duration_minutes, _CFG)
    except Exception as e:
        return f"Could not create calendar event: {e}"
    if not event:
        return "Calendar event could not be created."
    return f"Created calendar event: {_event_line(event)}."


def spotify_play(query: str) -> str:
    try:
        import spotify_client
        return spotify_client.play(query, _CFG)
    except Exception as e:
        return f"Spotify play failed: {e}"


def spotify_control(action: str) -> str:
    try:
        import spotify_client
        return spotify_client.control(action, _CFG)
    except Exception as e:
        return f"Spotify control failed: {e}"


def spotify_now_playing() -> str:
    try:
        import spotify_client
        return spotify_client.now_playing(_CFG)
    except Exception as e:
        return f"Spotify status failed: {e}"


def _repo_root(repo_name: str = "") -> Path:
    repo_name = (repo_name or "").strip()
    if _project_registry is not None:
        project = _project_registry.resolve(repo_name) if repo_name else _project_registry.get_active()
        if project and project.get("repo_path"):
            return Path(project["repo_path"]).resolve()

    if repo_name:
        path = _REPOS.get(repo_name.lower())
        if not path:
            raise ValueError(f"Repo '{repo_name}' not found.")
        return Path(path).resolve()

    return Path(".").resolve()


def _safe_repo_path(path: str, repo_name: str = "") -> tuple[Path, Path]:
    root = _repo_root(repo_name)
    requested = Path(path)
    target = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes the repository root.")
    return root, target


def _is_probably_text(path: Path) -> bool:
    if path.stat().st_size > 512_000:
        return False
    try:
        path.read_text(encoding="utf-8")
        return True
    except UnicodeDecodeError:
        return False
    except Exception:
        return False


def create_file(path: str, content: str, repo_name: str = "") -> str:
    try:
        root, target = _safe_repo_path(path, repo_name)
        if target.exists():
            return f"File already exists: {target.relative_to(root)}."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Created file: {target.relative_to(root)}."
    except Exception as e:
        return f"Could not create file: {e}"


def read_file(path: str, repo_name: str = "") -> str:
    try:
        root, target = _safe_repo_path(path, repo_name)
        if not target.exists() or not target.is_file():
            return f"File not found: {path}."
        if not _is_probably_text(target):
            return f"File is too large or not plain text: {target.relative_to(root)}."
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > 4000:
            text = text[:4000] + "\n...truncated..."
        return f"{target.relative_to(root)}:\n{text}"
    except Exception as e:
        return f"Could not read file: {e}"


def search_codebase(query: str, repo_name: str = "") -> str:
    try:
        root = _repo_root(repo_name)
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
        matches = []
        needle = query.lower()
        for path in root.rglob("*"):
            if len(matches) >= 20:
                break
            if any(part in skip_dirs for part in path.relative_to(root).parts):
                continue
            if not path.is_file() or not _is_probably_text(path):
                continue
            try:
                for idx, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if needle in line.lower():
                        rel = path.relative_to(root)
                        matches.append(f"{rel}:{idx}: {line.strip()[:160]}")
                        break
            except Exception:
                continue
        if not matches:
            return f"No codebase matches for '{query}'."
        return "\n".join(matches)
    except Exception as e:
        return f"Code search failed: {e}"


def _gemini_summarize(prompt: str, body: str, fallback: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return fallback
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(_CFG["gemini"]["model"])
        response = model.generate_content(f"{prompt}\n\n{body[:12000]}")
        return (response.text or "").strip()[:1200] or fallback
    except Exception:
        return fallback


def summarize_diff(repo_name: str = "") -> str:
    try:
        root = _repo_root(repo_name)
        stat = subprocess.run(
            "git diff --stat", shell=True, capture_output=True, text=True, cwd=root
        ).stdout.strip()
        diff = subprocess.run(
            "git diff --unified=2", shell=True, capture_output=True, text=True, cwd=root
        ).stdout.strip()
        if not diff and not stat:
            return "No git diff in this repo."
        fallback = f"Git diff summary:\n{stat or diff[:900]}"
        return _gemini_summarize(
            "Summarize this git diff for a developer in 5 concise bullets.",
            f"{stat}\n\n{diff}",
            fallback,
        )
    except Exception as e:
        return f"Could not summarize diff: {e}"


def explain_file(path: str, repo_name: str = "") -> str:
    try:
        root, target = _safe_repo_path(path, repo_name)
        if not target.exists() or not target.is_file():
            return f"File not found: {path}."
        if not _is_probably_text(target):
            return f"File is too large or not plain text: {target.relative_to(root)}."
        text = target.read_text(encoding="utf-8", errors="replace")
        fallback = f"{target.relative_to(root)} appears to be a text file with {len(text.splitlines())} lines."
        return _gemini_summarize(
            f"Explain the purpose and key behavior of {target.relative_to(root)}.",
            text,
            fallback,
        )
    except Exception as e:
        return f"Could not explain file: {e}"


def unread_count() -> str:
    try:
        import gmail_client
        count = gmail_client.unread_count(_CFG)
        return f"You have {count} unread email{'s' if count != 1 else ''}."
    except Exception as e:
        return f"Could not read Gmail unread count: {e}"


def last_emails(n: int = 5) -> str:
    try:
        import gmail_client
        items = gmail_client.last_emails(n, _CFG)
    except Exception as e:
        return f"Could not read recent emails: {e}"
    if not items:
        return "No recent emails found."
    lines = []
    for item in items:
        sender = item.get("sender", "unknown sender")
        subject = item.get("subject", "(no subject)")
        snippet = item.get("snippet", "")
        lines.append(f"- {sender}: {subject}. {snippet}")
    return "Recent emails:\n" + "\n".join(lines)


def summarize_inbox() -> str:
    try:
        import gmail_client
        summary = gmail_client.summarize_inbox(_CFG)
    except Exception as e:
        return f"Could not summarize Gmail inbox: {e}"
    count = summary.get("unread_count", 0)
    recent = summary.get("recent", [])
    lines = [f"Unread emails: {count}."]
    if recent:
        lines.append("Latest:")
        for item in recent:
            lines.append(f"- {item.get('sender', 'unknown')}: {item.get('subject', '(no subject)')}")
    return "\n".join(lines)


def _home_assistant_config() -> dict:
    return _CFG.get("home_assistant", {}) or {}


def _home_assistant_request(method: str, path: str, payload: dict | None = None) -> dict:
    cfg = _home_assistant_config()
    if not cfg.get("enabled", False):
        raise RuntimeError("Home Assistant is disabled. Set home_assistant.enabled to true in config.yaml.")
    url = (cfg.get("url") or "").rstrip("/")
    token = cfg.get("token") or os.getenv("HOME_ASSISTANT_TOKEN")
    if not url or not token:
        raise RuntimeError("Home Assistant is not configured. Add home_assistant.url and token.")
    import requests
    response = requests.request(
        method,
        f"{url}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=8,
    )
    response.raise_for_status()
    if not response.text:
        return {}
    return response.json()


def ha_get_state(entity_id: str) -> str:
    try:
        data = _home_assistant_request("GET", f"/api/states/{entity_id}")
        return f"{entity_id} is {data.get('state', 'unknown')}."
    except Exception as e:
        return f"Could not get Home Assistant state: {e}"


def ha_call_service(domain: str, service: str, data: dict | None = None) -> str:
    try:
        payload = data if isinstance(data, dict) else {}
        result = _home_assistant_request("POST", f"/api/services/{domain}/{service}", payload)
        changed = len(result) if isinstance(result, list) else 0
        return f"Called Home Assistant service {domain}.{service}" + (f" ({changed} entities changed)." if changed else ".")
    except Exception as e:
        return f"Could not call Home Assistant service: {e}"


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
        "today_schedule":   lambda i: today_schedule(),
        "next_event":       lambda i: next_event(),
        "list_events":      lambda i: list_events(i["start"], i["end"]),
        "create_event":     lambda i: create_event(i["title"], i["when"], int(i.get("duration_minutes", 60))),
        "spotify_play":     lambda i: spotify_play(i["query"]),
        "spotify_control":  lambda i: spotify_control(i["action"]),
        "spotify_now_playing": lambda i: spotify_now_playing(),
        "create_file":      lambda i: create_file(i["path"], i["content"], i.get("repo_name", "")),
        "read_file":        lambda i: read_file(i["path"], i.get("repo_name", "")),
        "search_codebase":  lambda i: search_codebase(i["query"], i.get("repo_name", "")),
        "summarize_diff":   lambda i: summarize_diff(i.get("repo_name", "")),
        "explain_file":     lambda i: explain_file(i["path"], i.get("repo_name", "")),
        "unread_count":     lambda i: unread_count(),
        "last_emails":      lambda i: last_emails(int(i.get("n", 5))),
        "summarize_inbox":  lambda i: summarize_inbox(),
        "ha_get_state":     lambda i: ha_get_state(i["entity_id"]),
        "ha_call_service":  lambda i: ha_call_service(i["domain"], i["service"], i.get("data", {})),
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
