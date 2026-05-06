import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools


class Phase6AdvancedToolsTest(unittest.TestCase):
    def test_disabled_integrations_degrade_gracefully(self):
        disabled_cfg = copy.deepcopy(tools._CFG)
        disabled_cfg.setdefault("gmail", {})["enabled"] = False
        self.assertIn("Spotify", tools.spotify_now_playing())
        with patch.object(tools, "_refresh_config_from_disk", return_value=disabled_cfg):
            self.assertIn("Gmail", tools.unread_count())
            self.assertIn("Gmail", tools.new_emails())
            self.assertIn("gmail.enabled is false", tools.gmail_status())
        self.assertIn("Home Assistant", tools.ha_get_state("light.office"))

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


if __name__ == "__main__":
    unittest.main()
