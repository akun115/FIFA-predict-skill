"""README-based provider candidate rule tests.

Verifies the repo-level README.md covers provider candidate rules,
replacing the deleted docs/provider_candidates/ dossiers.
"""

from __future__ import annotations

import pathlib
import re
import unittest


README_PATH = pathlib.Path(__file__).parent.parent / "README.md"


class ReadmeProviderRulesTests(unittest.TestCase):
    """README.md must encode all provider-candidate rules formerly in dossiers."""

    @classmethod
    def setUpClass(cls):
        cls.text = README_PATH.read_text(encoding="utf-8")
        cls.text_lower = cls.text.lower()

    def test_01_readme_exists(self):
        self.assertTrue(README_PATH.exists())

    def test_02_provider_status_rules(self):
        """Covers needs_more_info and not approved_for_live_adapter statuses."""
        self.assertIn("needs_more_info", self.text_lower)
        self.assertIn("not approved for live adapter", self.text_lower)

    def test_03_free_first_strategy(self):
        """Mentions free providers (TheSportsDB, API-Football, football-data.org)."""
        self.assertIn("free sources", self.text_lower)
        self.assertIn("football-data.org", self.text)

    def test_04_paid_providers_reserved(self):
        """Mentions 'paid reserved' or equivalent for premium providers."""
        self.assertIn("paid reserved", self.text_lower)

    def test_05_web_scout_report_only(self):
        """Web scout data is report-only — no xG adjustment."""
        self.assertIn("report-only", self.text_lower)
        self.assertIn("xg adjustment", self.text_lower)

    def test_06_no_odds_blending(self):
        """Odds are never blended into model probabilities."""
        self.assertIn("never blended", self.text_lower)

    def test_07_no_api_keys_in_readme(self):
        """README must not contain embedded API keys or secrets."""
        self.assertNotRegex(self.text, r'[a-f0-9]{32}')
        self.assertNotIn("sk-", self.text)

    def test_08_no_approval_gate_bypass(self):
        """TheSportsDB must remain needs_more_info — no bypass."""
        self.assertIn("needs_more_info", self.text_lower)
        self.assertIn("thesportsdb", self.text_lower)

    def test_09_template_approval_concepts(self):
        """README mentions approval/fail-closed concepts."""
        self.assertIn("fail-closed", self.text_lower)
        self.assertIn("not approved", self.text_lower)

    def test_10_no_forbidden_prediction_keys(self):
        """Forbidden prediction keys must not appear as positive claims."""
        forbidden = ("result_probabilities", "expected_goals",
                     "advancement_probabilities")
        for key in forbidden:
            self.assertNotIn(key, self.text_lower,
                             f"'{key}' must not appear as positive claim in README")

    def test_11_thesportsdb_not_approved(self):
        """TheSportsDB is explicitly NOT approved for live adapter use."""
        self.assertIn("not approved for live adapter", self.text_lower)
        self.assertIn("thesportsdb", self.text_lower)


if __name__ == "__main__":
    unittest.main()
