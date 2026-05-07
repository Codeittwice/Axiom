# AXIOM University Obsidian Vault Plan

## Purpose

This plan is for a separate Obsidian vault on the E drive dedicated to university studying.

The vault should support:

- Course notes.
- Lecture notes.
- Assignments, labs, readings, and exam prep.
- Daily study planning.
- A clean task system that AXIOM can scan.
- A future AXIOM task UI that shows university tasks separately from dev/app tasks.

Recommended vault path:

```text
E:/University Vault
```

If you choose a different folder, keep the structure below the same.

## Codex Handoff

When Codex is run inside the new vault folder, it should:

1. Create the folder structure in this plan.
2. Create the starter markdown notes and templates.
3. Avoid overwriting existing notes unless explicitly asked.
4. Use plain Obsidian markdown. No Obsidian plugin is required.
5. Keep all generated files inside the current vault folder.
6. Use ASCII filenames where practical.

## Vault Structure

```text
University Vault/
  00_Inbox/
    Task Inbox.md
    Quick Notes.md

  01_Daily/
    README.md

  02_Courses/
    README.md
    _Course Template/
      Course Home.md
      Lectures/
      Assignments/
      Labs/
      Readings/
      Exam Prep/
      Resources/

  03_Assignments/
    README.md

  04_Exams/
    README.md

  05_Knowledge/
    Concepts/
    Formulas/
    Methods/

  06_Projects/
    README.md

  07_Archive/
    Completed Tasks.md

  _attachments/

  _templates/
    Daily Note.md
    Course Home.md
    Lecture Note.md
    Reading Note.md
    Assignment.md
    Lab.md
    Exam Prep.md

  _system/
    Task Conventions.md
    Vault Guide.md

  Dashboard.md
  Semester Plan.md
  Courses Index.md
```

## Course Folder Pattern

Each real course should be copied from `02_Courses/_Course Template/` and renamed:

```text
02_Courses/32SPH - Statistical Physics/
  Course Home.md
  Lectures/
  Assignments/
  Labs/
  Readings/
  Exam Prep/
  Resources/
```

Recommended course naming:

```text
<COURSE_CODE> - <Course Name>
```

Examples:

```text
32SPH - Statistical Physics
34SPH - Subatomic Physics
MATH201 - Linear Algebra
```

## Metadata Standard

Every important note should use frontmatter.

Course home:

```markdown
---
type: course
course: 32SPH
course_name: Statistical Physics
semester: Spring 2026
status: active
area: university
---
```

Lecture note:

```markdown
---
type: lecture
course: 32SPH
course_name: Statistical Physics
date: 2026-05-06
area: university
---
```

Assignment:

```markdown
---
type: assignment
course: 32SPH
due: 2026-05-12
status: open
priority: high
area: university
---
```

## Task Syntax

AXIOM should scan plain markdown tasks:

```markdown
- [ ] Finish statistical physics problem set due:: 2026-05-12 priority:: high course:: 32SPH area:: university
- [ ] Review lecture 08 notes due:: 2026-05-07 priority:: medium course:: 32SPH area:: university
- [x] Submit lab report due:: 2026-05-01 priority:: high course:: 34SPH area:: university
```

Required task fields:

- `area:: university`
- `course:: <COURSE_CODE>` when course-related
- `due:: YYYY-MM-DD` when there is a deadline
- `priority:: low|medium|high`

Optional fields:

- `type:: reading|assignment|lab|exam|admin`
- `estimate:: 30m`
- `status:: blocked`

Use tags only for broad grouping:

```markdown
#exam
#reading
#lab
#admin
```

## Starter Notes

### Dashboard.md

Should contain links to:

- `Semester Plan.md`
- `Courses Index.md`
- `00_Inbox/Task Inbox.md`
- `04_Exams/README.md`
- Active course home notes

Suggested sections:

```markdown
# University Dashboard

## Today

- [ ] Review today's lectures area:: university priority:: medium

## Active Courses

- [[32SPH - Statistical Physics/Course Home]]

## Upcoming Deadlines

Tasks with `due::` dates will be surfaced by AXIOM.
```

### 00_Inbox/Task Inbox.md

```markdown
# Task Inbox

Use this for fast capture before sorting tasks into course notes.

- [ ] Example captured task area:: university priority:: medium
```

### _system/Task Conventions.md

Should explain the task syntax and say:

- AXIOM reads open tasks from this vault.
- Use `area:: university` for study tasks.
- Add `course::` and `due::` when possible.
- Keep full explanations in the note body; keep task lines concise.

## AXIOM Multi-Source Task Plan

AXIOM should eventually scan two task sources:

1. University vault
   - Root: `E:/University Vault`
   - Label: `University`
   - Area value: `university`

2. Dev apps folder
   - Root: `E:/_DEV`
   - Label: `Dev Apps`
   - Area value: `dev`

Proposed AXIOM config shape:

```yaml
obsidian:
  task_sources:
    - id: university
      label: "University"
      root: "E:/University Vault"
      scan_paths:
        - "00_Inbox"
        - "01_Daily"
        - "02_Courses"
        - "03_Assignments"
        - "04_Exams"
      area: "university"
      summary_limit: 3

    - id: dev
      label: "Dev Apps"
      root: "E:/_DEV"
      scan_paths:
        - "Personal Voice Assistant"
      area: "dev"
      summary_limit: 3
```

Backward compatibility:

- Keep supporting `obsidian.vault_path`.
- If `task_sources` exists, use it.
- If it does not exist, fall back to the old single-vault scan.

## Tasks Side Panel Design

The side panel should not show every task in full. It should show a compact summary grouped by source.

Example:

```text
TASKS

UNIVERSITY
3 due today
2 high priority
- Statistical physics problem set
- Subatomic physics reading

DEV APPS
4 open
1 blocked
- Implement obsidian_tasks.py
- Fix Spotify response fallback
```

Rules:

- Show source headers: `University`, `Dev Apps`.
- Show counts first.
- Show only the top 2 or 3 urgent tasks per source.
- Prioritize overdue, due today, high priority, then recently captured.
- Do not show long task descriptions in the side panel.
- Each row should include a source note or course/project label in muted text.

## Full Tasks View

Add either a dedicated `Tasks` tab or a modal opened from the side panel.

Preferred: a dedicated `Tasks` tab, because it gives room for filters and full text.

Required views:

- All open tasks.
- Today.
- This week.
- University.
- Dev Apps.
- High priority.
- Blocked.

Each full task row should show:

- Checkbox.
- Full task text.
- Source group.
- Course or project.
- Due date.
- Priority.
- Source note path.
- Actions: complete, reschedule, open note.

## AXIOM Voice Commands

University:

- "What are my university tasks?"
- "What do I have due today for university?"
- "What is due this week for statistical physics?"
- "Add university task: finish the statistical physics problem set by Friday."
- "Mark the statistical physics problem set done."

Dev:

- "What are my dev tasks?"
- "What AXIOM tasks are open?"
- "Add dev task: implement the Obsidian task parser."

Mixed:

- "What tasks are at hand?"
- "Show all high priority tasks."
- "Open my full task list."

## AXIOM Implementation Steps

1. Extend config support
   - Add `obsidian.task_sources`.
   - Preserve single-vault fallback.

2. Build `obsidian_tasks.py`
   - Parse task lines.
   - Parse inline fields.
   - Infer area/source from configured task source.
   - Return normalized task objects.

3. Update dashboard backend
   - Return grouped task summaries.
   - Keep side panel data compact.

4. Add full tasks API
   - `GET /api/tasks`
   - `GET /api/tasks/summary`
   - `POST /api/tasks/capture`
   - `POST /api/tasks/<id>/complete`
   - `POST /api/tasks/<id>/reschedule`

5. Update UI
   - Side panel summary grouped by source.
   - Dedicated Tasks tab or modal for full descriptions.

6. Add voice tools
   - `list_tasks`
   - `capture_task`
   - `complete_task`
   - `reschedule_task`
   - `open_tasks_view`

7. Tests
   - Multi-root scan.
   - Path safety.
   - Inline field parsing.
   - Grouped summary ordering.
   - Line update safety.

## Acceptance Criteria

- [ ] A new E-drive university vault can be generated from this plan.
- [ ] University and dev tasks are scanned from separate roots.
- [ ] Side panel shows grouped summaries, not full descriptions.
- [ ] Full task view shows complete task text and actions.
- [ ] AXIOM voice commands can list and capture tasks by area.
- [ ] No task scan or edit can escape its configured root.
