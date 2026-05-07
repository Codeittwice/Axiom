# AXIOM Obsidian Implementation Plan

## Goal

Turn the Obsidian vault into AXIOM's local task and context system:

- Capture tasks, ideas, and daily notes by voice.
- Scan the vault for open tasks without requiring a paid service.
- Group work by project, course, due date, and priority.
- Show useful tasks in the Live side panel.
- Let AXIOM explain, add, update, and summarize the workflow by voice.

For the university-specific vault structure and the future multi-source task panel, see
`AXIOM_university_vault_plan.md`.

## Current State

AXIOM already has basic Obsidian note tools in `tools.py`:

- `create_note(title, content)`
- `read_note(title)`
- `append_daily_note(content)`
- `search_notes(query)`

The Live dashboard has a simple task widget that scans for the first few `- [ ]` markdown tasks, but it does not yet understand due dates, priorities, projects, courses, or source-line updates.

## Proposed Config

Add these optional keys under `obsidian:`:

```yaml
obsidian:
  vault_path: ""
  daily_notes_folder: ""
  tasks_scan_paths: []
  inbox_note: "AXIOM Inbox.md"
  task_archive_note: "AXIOM Done.md"
  default_project: "AXIOM"
  courses_folder: "Courses"
  projects_folder: "Projects"
  objectives_folder: "Objectives"
```

## Data Model

The task index should return normalized items:

```python
{
    "id": "stable hash of vault path + line number + task text",
    "text": "Finish physics lab report",
    "status": "open",
    "source": "Courses/Physics.md",
    "line": 42,
    "project": "Physics",
    "course": "32SPH",
    "due": "2026-05-08",
    "priority": "high",
    "tags": ["school"],
    "raw": "- [ ] Finish physics lab report #school due:: 2026-05-08 priority:: high",
}
```

Supported lightweight syntax:

- Markdown tasks: `- [ ] task text`
- Done tasks: `- [x] task text`
- Due date: `due:: YYYY-MM-DD` or `📅 YYYY-MM-DD`
- Priority: `priority:: high` or `!`, `!!`, `!!!`
- Tags: normal Obsidian tags such as `#school`
- Project/course inference from folder path and note properties.

## Phase 6c Deliverables

1. `obsidian_tasks.py`
   - Scan configured vault folders for markdown tasks.
   - Parse task text, source path, line number, due date, priority, tags, project, and course.
   - Return stable task IDs for later updates.
   - Never write outside the configured vault.

2. REST API
   - `GET /api/obsidian/tasks?status=open&limit=20`
   - `GET /api/obsidian/today`
   - `POST /api/obsidian/capture`
   - `POST /api/obsidian/tasks/<id>/complete`
   - `POST /api/obsidian/tasks/<id>/reschedule`

3. Voice Tools
   - `capture_task`
   - `today_tasks`
   - `upcoming_tasks`
   - `complete_task`
   - `reschedule_task`
   - `obsidian_status`
   - `explain_obsidian_workflow`

4. UI
   - Replace the basic Tasks widget with normalized task rows.
   - Show source note, due date, and priority.
   - Keep the current dark grid visual style and side-panel layout.

5. Safety
   - Read-only scans by default.
   - For edits, update only exact task lines by stable ID.
   - Keep backups or append a reversible entry when completing/rescheduling.
   - Degrade gracefully when `obsidian.vault_path` is missing.

## Voice Workflow

User commands should sound natural:

- "Add task: finish the physics assignment by Friday."
- "What tasks are due today?"
- "What are my school tasks this week?"
- "Mark the physics lab report done."
- "Explain the Obsidian workflow."

AXIOM should answer briefly by voice, while the side panel carries the detailed list.

## Acceptance Criteria

- [ ] Works with plain Obsidian markdown, no plugin required.
- [ ] Task scans stay inside `obsidian.vault_path`.
- [ ] Dashboard Tasks widget shows normalized open tasks.
- [ ] Voice can capture, list, complete, and reschedule tasks.
- [ ] AXIOM can explain the workflow with `explain_obsidian_workflow`.
- [ ] Unit tests cover parsing, path safety, and line updates.
