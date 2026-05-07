"""Obsidian markdown task indexing and safe line updates for AXIOM."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


TASK_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(?P<text>.+?)\s*$")
DUE_RE = re.compile(r"(?:due::|due:)\s*(\d{4}-\d{2}-\d{2})|\U0001f4c5\s*(\d{4}-\d{2}-\d{2})", re.I)
PRIORITY_RE = re.compile(r"priority::\s*(high|medium|low)", re.I)
PROJECT_RE = re.compile(r"project::\s*([^\s#]+)", re.I)
COURSE_RE = re.compile(r"course::\s*([^\s#]+)", re.I)
TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_/-]+)")


class ObsidianTaskError(Exception):
    pass


def vault_path(config: dict[str, Any]) -> Path:
    raw = str((config.get("obsidian") or {}).get("vault_path") or "").strip()
    if not raw:
        raise ObsidianTaskError("Obsidian vault not configured.")
    vault = Path(raw).expanduser().resolve()
    if not vault.exists():
        raise ObsidianTaskError("Obsidian vault path does not exist.")
    if not vault.is_dir():
        raise ObsidianTaskError("Obsidian vault path is not a folder.")
    return vault


def _inside_vault(path: Path, vault: Path) -> bool:
    try:
        path.resolve().relative_to(vault)
        return True
    except ValueError:
        return False


def _scan_roots(config: dict[str, Any], vault: Path) -> list[Path]:
    obsidian = config.get("obsidian") or {}
    configured = obsidian.get("task_sources") or obsidian.get("tasks_scan_paths") or []
    roots = []
    for item in configured:
        candidate = (vault / str(item)).resolve()
        if candidate.exists() and candidate.is_dir() and _inside_vault(candidate, vault):
            roots.append(candidate)
    return roots or [vault]


def _stable_id(source: str, line: int, raw: str) -> str:
    digest = hashlib.sha1(f"{source}:{line}:{raw}".encode("utf-8")).hexdigest()
    return digest[:16]


def _metadata_folder_value(parts: tuple[str, ...], folder: str) -> str:
    if not folder:
        return ""
    lowered = [p.lower() for p in parts]
    try:
        idx = lowered.index(folder.lower())
    except ValueError:
        return ""
    if idx + 1 < len(parts):
        return parts[idx + 1]
    return ""


def parse_task_line(raw: str, source: str, line: int, config: dict[str, Any]) -> dict[str, Any] | None:
    match = TASK_RE.match(raw)
    if not match:
        return None

    obsidian = config.get("obsidian") or {}
    text = match.group("text").strip()
    due_match = DUE_RE.search(text)
    due = ""
    if due_match:
        due = next((g for g in due_match.groups() if g), "")

    priority_match = PRIORITY_RE.search(text)
    priority = priority_match.group(1).lower() if priority_match else ""
    if not priority:
        bangs = re.search(r"(^|\s)(!{1,3})(\s|$)", text)
        if bangs:
            priority = {"!": "low", "!!": "medium", "!!!": "high"}[bangs.group(2)]

    parts = Path(source).parts
    project_match = PROJECT_RE.search(text)
    course_match = COURSE_RE.search(text)
    project = project_match.group(1) if project_match else _metadata_folder_value(parts, obsidian.get("projects_folder", "Projects"))
    course = course_match.group(1) if course_match else _metadata_folder_value(parts, obsidian.get("courses_folder", "Courses"))
    if not project and not course and obsidian.get("default_project"):
        project = str(obsidian.get("default_project"))

    return {
        "id": _stable_id(source, line, raw),
        "text": text,
        "status": "done" if match.group(1).lower() == "x" else "open",
        "source": source,
        "line": line,
        "project": project,
        "course": course,
        "due": due,
        "priority": priority,
        "tags": TAG_RE.findall(text),
        "raw": raw.rstrip("\n"),
    }


def scan_tasks(config: dict[str, Any], status: str = "open", limit: int | None = None) -> list[dict[str, Any]]:
    vault = vault_path(config)
    wanted = (status or "open").lower()
    tasks: list[dict[str, Any]] = []

    for root in _scan_roots(config, vault):
        for md in root.rglob("*.md"):
            if not _inside_vault(md, vault):
                continue
            try:
                rel = md.relative_to(vault).as_posix()
                lines = md.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            for index, raw in enumerate(lines, start=1):
                task = parse_task_line(raw, rel, index, config)
                if not task:
                    continue
                if wanted != "all" and task["status"] != wanted:
                    continue
                tasks.append(task)
                if limit and len(tasks) >= limit:
                    return _sort_tasks(tasks)
    return _sort_tasks(tasks)


def _sort_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_rank = {"high": 0, "medium": 1, "low": 2, "": 3}
    return sorted(
        tasks,
        key=lambda t: (
            priority_rank.get(t.get("priority", ""), 3),
            t.get("due") or "9999-12-31",
            t.get("source", ""),
            t.get("line", 0),
        ),
    )


def today_tasks(config: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    return [t for t in scan_tasks(config, "open") if t.get("due") == today][:limit]


def upcoming_tasks(config: dict[str, Any], days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
    start = date.today()
    end = start + timedelta(days=max(0, days))
    items = []
    for task in scan_tasks(config, "open"):
        due = _parse_date(task.get("due", ""))
        if due and start <= due <= end:
            items.append(task)
    return items[:limit]


def capture_task(
    config: dict[str, Any],
    text: str,
    due: str = "",
    priority: str = "",
    project: str = "",
    course: str = "",
) -> dict[str, Any]:
    vault = vault_path(config)
    obsidian = config.get("obsidian") or {}
    inbox = str(obsidian.get("inbox_note") or "AXIOM Inbox.md")
    path = (vault / inbox).resolve()
    if not _inside_vault(path, vault):
        raise ObsidianTaskError("Inbox note would be outside the configured vault.")

    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [f"- [ ] {text.strip()}"]
    due = due.strip()
    if due:
        _require_date(due)
        parts.append(f"due:: {due}")
    priority = priority.strip().lower()
    if priority:
        if priority not in {"low", "medium", "high"}:
            raise ObsidianTaskError("Priority must be low, medium, or high.")
        parts.append(f"priority:: {priority}")
    if project.strip():
        parts.append(f"project:: {project.strip()}")
    if course.strip():
        parts.append(f"course:: {course.strip()}")

    with open(path, "a", encoding="utf-8") as f:
        if path.stat().st_size == 0:
            f.write("# AXIOM Inbox\n\n")
        f.write(" ".join(parts).rstrip() + "\n")

    rel = path.relative_to(vault).as_posix()
    line = len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    raw = " ".join(parts).rstrip()
    return parse_task_line(raw, rel, line, config) or {"source": rel, "line": line, "text": text}


def complete_task(config: dict[str, Any], task_id: str) -> dict[str, Any]:
    task, path, lines = _find_task(config, task_id)
    raw = lines[task["line"] - 1]
    lines[task["line"] - 1] = re.sub(r"\[ \]", "[x]", raw, count=1)
    _write_lines(path, lines)
    _archive_change(config, f"Completed: {task['text']} ({task['source']}:{task['line']})")
    return {**task, "status": "done"}


def reschedule_task(config: dict[str, Any], task_id: str, due: str) -> dict[str, Any]:
    _require_date(due)
    task, path, lines = _find_task(config, task_id)
    raw = lines[task["line"] - 1]
    if DUE_RE.search(raw):
        updated = DUE_RE.sub(f"due:: {due}", raw, count=1)
    else:
        updated = raw.rstrip() + f" due:: {due}"
    lines[task["line"] - 1] = updated
    _write_lines(path, lines)
    _archive_change(config, f"Rescheduled: {task['text']} to {due} ({task['source']}:{task['line']})")
    updated_task = parse_task_line(updated, task["source"], task["line"], config) or task
    return updated_task


def find_task_by_query(config: dict[str, Any], query: str) -> dict[str, Any]:
    query = query.strip().lower()
    if not query:
        raise ObsidianTaskError("Task query is required.")
    for task in scan_tasks(config, "open"):
        if task["id"] == query or query in task["text"].lower():
            return task
    raise ObsidianTaskError(f"No open task matched '{query}'.")


def status(config: dict[str, Any]) -> dict[str, Any]:
    vault = vault_path(config)
    tasks = scan_tasks(config, "open")
    due_today = len([t for t in tasks if t.get("due") == date.today().isoformat()])
    return {"vault": str(vault), "open": len(tasks), "due_today": due_today}


def _find_task(config: dict[str, Any], task_id: str) -> tuple[dict[str, Any], Path, list[str]]:
    vault = vault_path(config)
    for task in scan_tasks(config, "all"):
        if task["id"] != task_id:
            continue
        path = (vault / task["source"]).resolve()
        if not _inside_vault(path, vault):
            raise ObsidianTaskError("Task source is outside the configured vault.")
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if task["line"] < 1 or task["line"] > len(lines):
            raise ObsidianTaskError("Task line no longer exists.")
        return task, path, lines
    raise ObsidianTaskError("Task not found.")


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _archive_change(config: dict[str, Any], text: str) -> None:
    try:
        vault = vault_path(config)
        archive = str((config.get("obsidian") or {}).get("task_archive_note") or "AXIOM Done.md")
        path = (vault / archive).resolve()
        if not _inside_vault(path, vault):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="minutes")
        with open(path, "a", encoding="utf-8") as f:
            if path.stat().st_size == 0:
                f.write("# AXIOM Done\n\n")
            f.write(f"- {timestamp} {text}\n")
    except Exception:
        return


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def _require_date(value: str) -> None:
    if not _parse_date(value):
        raise ObsidianTaskError("Date must use YYYY-MM-DD.")
