import unittest

import reflection


class ReflectionDedupingTest(unittest.TestCase):
    def test_duplicate_title_and_proposal_are_suppressed(self):
        existing = [
            {
                "type": "new_skill",
                "title": "Create Spotify setup flow",
                "proposal": {"description": "Add status and connect endpoints for Spotify OAuth."},
            }
        ]
        fingerprints = reflection._suggestion_fingerprints(existing, {})

        candidate = {
            "type": "new_skill",
            "title": "Create Spotify setup flow",
            "proposal": {"description": "Add status and connect endpoints for Spotify OAuth."},
        }

        self.assertTrue(reflection._is_duplicate_suggestion(candidate, fingerprints))

    def test_seen_fingerprints_from_user_model_are_suppressed(self):
        seen = {
            "seen_suggestion_fingerprints": [
                {
                    "fingerprint": "preference | add task priority indicators | group tasks by priority with colored indicators",
                    "title": "Add task priority indicators",
                }
            ]
        }
        fingerprints = reflection._suggestion_fingerprints([], seen)

        candidate = {
            "type": "preference",
            "title": "Add task priority indicators",
            "proposal": {"description": "Group tasks by priority with colored indicators."},
        }

        self.assertTrue(reflection._is_duplicate_suggestion(candidate, fingerprints))

    def test_seen_titles_include_all_statuses(self):
        titles = reflection._blocked_suggestion_titles(
            {"seen_suggestion_fingerprints": [{"title": "Old seen idea"}]},
            [
                {"title": "Pending idea", "status": "pending"},
                {"title": "Approved idea", "status": "approved"},
                {"title": "Rejected idea", "status": "rejected"},
                {"title": "Implemented idea", "status": "implemented"},
            ],
        )

        self.assertIn("Pending idea", titles)
        self.assertIn("Approved idea", titles)
        self.assertIn("Rejected idea", titles)
        self.assertIn("Implemented idea", titles)
        self.assertIn("Old seen idea", titles)


if __name__ == "__main__":
    unittest.main()
