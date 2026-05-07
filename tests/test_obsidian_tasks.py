import tempfile
import unittest
from pathlib import Path

import obsidian_tasks


def cfg(vault: str) -> dict:
    return {
        "obsidian": {
            "vault_path": vault,
            "tasks_scan_paths": ["Projects", "Courses"],
            "inbox_note": "AXIOM Inbox.md",
            "task_archive_note": "AXIOM Done.md",
            "default_project": "AXIOM",
            "projects_folder": "Projects",
            "courses_folder": "Courses",
        }
    }


class ObsidianTasksTest(unittest.TestCase):
    def test_scan_parses_metadata_and_folder_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "Courses" / "Physics" / "Week.md"
            note.parent.mkdir(parents=True)
            note.write_text(
                "- [ ] Finish lab report due:: 2026-05-08 priority:: high #school\n"
                "- [x] Old task due:: 2026-05-01\n",
                encoding="utf-8",
            )

            tasks = obsidian_tasks.scan_tasks(cfg(tmp), status="open")

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["course"], "Physics")
            self.assertEqual(tasks[0]["due"], "2026-05-08")
            self.assertEqual(tasks[0]["priority"], "high")
            self.assertIn("school", tasks[0]["tags"])

    def test_capture_complete_and_reschedule_stay_inside_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = cfg(tmp)
            task = obsidian_tasks.capture_task(config, "Write methods section", "2026-05-09", "medium")

            updated = obsidian_tasks.reschedule_task(config, task["id"], "2026-05-10")
            self.assertEqual(updated["due"], "2026-05-10")

            done = obsidian_tasks.complete_task(config, updated["id"])
            self.assertEqual(done["status"], "done")

            inbox = Path(tmp) / "AXIOM Inbox.md"
            self.assertIn("- [x] Write methods section", inbox.read_text(encoding="utf-8"))
            self.assertTrue((Path(tmp) / "AXIOM Done.md").exists())

    def test_rejects_inbox_outside_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = cfg(tmp)
            config["obsidian"]["inbox_note"] = "../outside.md"
            with self.assertRaises(obsidian_tasks.ObsidianTaskError):
                obsidian_tasks.capture_task(config, "No escape")


if __name__ == "__main__":
    unittest.main()
