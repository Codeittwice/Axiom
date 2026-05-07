import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools
import gmail_client
from text_safety import clean_text


class Phase6AdvancedToolsTest(unittest.TestCase):
    def test_disabled_integrations_degrade_gracefully(self):
        disabled_cfg = copy.deepcopy(tools._CFG)
        disabled_cfg.setdefault("gmail", {})["enabled"] = False
        disabled_cfg.setdefault("spotify", {})["enabled"] = False
        disabled_cfg.setdefault("home_assistant", {})["enabled"] = False
        with (
            patch.object(tools, "_CFG", disabled_cfg),
            patch.object(tools, "_refresh_config_from_disk", return_value=disabled_cfg),
        ):
            self.assertIn("Spotify", tools.spotify_now_playing())
            self.assertIn("Spotify status", tools.spotify_status())
            self.assertIn("Gmail", tools.unread_count())
            self.assertIn("Gmail", tools.new_emails())
            self.assertIn("gmail.enabled is false", tools.gmail_status())
            self.assertIn("Home Assistant", tools.ha_get_state("light.office"))

    def test_gmail_requires_explicit_connection(self):
        enabled_cfg = copy.deepcopy(tools._CFG)
        enabled_cfg.setdefault("gmail", {})["enabled"] = True
        with (
            patch.object(tools, "_refresh_config_from_disk", return_value=enabled_cfg),
            patch("gmail_client.has_connection", return_value=False),
        ):
            self.assertIn("Say 'connect Gmail'", tools.new_emails())

    def test_gmail_sender_labels_are_speakable(self):
        self.assertEqual(gmail_client.sender_label("Uber Eats <uber@uber.com>"), "Uber Eats")
        self.assertEqual(gmail_client.sender_label("team@email.remarkable.com"), "team")

    def test_text_cleanup_removes_invisible_combining_joiner(self):
        self.assertEqual(clean_text("Hello\u034f world", collapse_whitespace=True), "Hello world")

    def test_obsidian_workflow_explanation_command(self):
        result = tools.execute_tool("explain_obsidian_workflow", {})
        self.assertIn("Obsidian workflow", result)
        self.assertIn("AXIOM_obsidian_plan.md", result)

    def test_code_intelligence_file_roundtrip(self):
        original_repos = tools._REPOS
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tools._REPOS = {"tmp": tmp}
                self.assertIn("Created file", tools.create_file("src/example.py", "print('axiom')", "tmp"))
                self.assertIn("print('axiom')", tools.read_file("src/example.py", "tmp"))
                self.assertIn("src", tools.search_codebase("axiom", "tmp"))
                self.assertIn("already exists", tools.create_file("src/example.py", "again", "tmp"))
        finally:
            tools._REPOS = original_repos

    def test_code_intelligence_rejects_path_escape(self):
        original_repos = tools._REPOS
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tools._REPOS = {"tmp": tmp}
                self.assertIn("escapes", tools.create_file("../outside.txt", "nope", "tmp"))
        finally:
            tools._REPOS = original_repos

    def test_website_alias_resolves_spoken_wizz_air(self):
        self.assertEqual(tools._resolve_website("with air")[1], "https://wizzair.com")
        self.assertEqual(tools._resolve_website("gmail")[1], tools._WEBSITES["email"])

    def test_axiom_self_improvement_tasks_default_high_priority(self):
        self.assertEqual(tools._default_task_priority("train the wake word model"), "high")
        self.assertEqual(tools._default_task_priority("buy milk"), "")


if __name__ == "__main__":
    unittest.main()
