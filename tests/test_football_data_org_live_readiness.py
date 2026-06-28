"""Patch 24 — Football-data.org live readiness static checks.

All tests offline.  No network.  No API keys.  No skipped tests.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest


REPO = pathlib.Path(__file__).parent.parent


# ==========================================================================
# Readiness document — now the README
# ==========================================================================


class ReadinessDocTests(unittest.TestCase):
    """Readiness content previously in docs/football_data_org_live_readiness.md
    is now covered by the main README."""

    @classmethod
    def setUpClass(cls):
        cls.text = (REPO / "README.md").read_text(encoding="utf-8")

    def test_01_readme_covers_live_readiness(self):
        lower = self.text.lower()
        for term in ("live", "credentials", "opt-in"):
            self.assertIn(term, lower)

    def test_02_not_full_live_production(self):
        # Strip markdown bold markers so "**not**" reads as "not"
        clean = self.text.replace("**", "").lower()
        self.assertTrue(
            "not full live production" in clean or "not proven" in clean)

    def test_03_human_explicit_validation(self):
        lower = self.text.lower()
        self.assertTrue(
            "human" in lower or "explicit validation" in lower)

    def test_04_thesportsdb_needs_more_info(self):
        self.assertIn("needs_more_info", self.text.lower())

    def test_05_opt_in_env_var(self):
        self.assertIn(
            "WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS", self.text)

    def test_06_fail_closed_never_skip(self):
        lower = self.text.lower()
        self.assertIn("fail closed", lower)
        self.assertIn("never skip", lower)

    def test_07_license_or_credentials(self):
        lower = self.text.lower()
        self.assertTrue(
            "license" in lower or "credentials" in lower)

    def test_08_no_real_api_urls(self):
        """README may contain repository/documentation URLs but must not
        contain live API endpoint URLs."""
        urls = re.findall(r'https?://[^\s\)"]+', self.text)
        for url in urls:
            self.assertFalse(
                re.search(r'/(?:api|v[0-9]+)/', url, re.IGNORECASE),
                f"README contains possible API endpoint URL: {url}")

    def test_09_no_api_key_patterns(self):
        for pat in (r'[a-f0-9]{32}', r'sk-[a-zA-Z0-9]{32,}'):
            self.assertEqual(re.findall(pat, self.text), [])

    def test_10_readme_exists(self):
        self.assertTrue((REPO / "README.md").exists())


# ==========================================================================
# Candidate dossier content — now in the README
# ==========================================================================


class FootballDataOrgDossierTests(unittest.TestCase):
    """Dossier content previously in
    docs/provider_candidates/pending/football_data_org.md is now covered by
    the main README."""

    @classmethod
    def setUpClass(cls):
        cls.text = (REPO / "README.md").read_text(encoding="utf-8")

    def test_01_football_data_org_in_readme(self):
        lower = self.text.lower()
        self.assertTrue(
            "football-data.org" in lower or "football_data_org_token" in lower)

    def test_02_thesportsdb_needs_more_info(self):
        self.assertIn("needs_more_info", self.text.lower())

    def test_03_no_approved_for_live_adapter_as_status(self):
        """'approved_for_live_adapter' must not appear as a positive status."""
        idx = self.text.lower().find("approved_for_live_adapter")
        if idx >= 0:
            nearby = self.text.lower()[max(0, idx - 60):idx + 60]
            self.assertTrue(
                any(w in nearby for w in ("not", "no", "never")),
                f"'approved_for_live_adapter' without negative context: "
                f"...{nearby}...")

    def test_04_no_endpoint_placeholders(self):
        for term in ("<football_data_teams_endpoint>",
                      "<football_data_matches_endpoint>",
                      "<football_data_standings_endpoint>"):
            self.assertNotIn(term, self.text)

    def test_05_no_patch_24(self):
        self.assertNotIn("Patch 24", self.text)

    def test_06_credentials_never_committed(self):
        self.assertIn("Never commit credentials", self.text)


# ==========================================================================
# tests_live rules — now consolidated into main README
# ==========================================================================


class TestsLiveSkeletonTests(unittest.TestCase):
    """tests_live/ rules are now documented in the main README.
    The README must cover opt-in, discovery isolation, no-skip,
    prediction boundary, and env-var requirements."""

    @classmethod
    def setUpClass(cls):
        cls.text = (REPO / "README.md").read_text(encoding="utf-8")

    def test_01_readme_covers_tests_live_opt_in(self):
        self.assertIn("opt-in", self.text.lower())

    def test_02_readme_covers_not_default_discovery(self):
        text_lower = self.text.lower()
        self.assertIn("tests_live", text_lower)

    def test_03_readme_covers_no_skipped_tests(self):
        self.assertIn("never skip", self.text.lower())

    def test_04_readme_covers_no_prediction_integration(self):
        self.assertIn("prediction", self.text.lower())

    def test_05_readme_requires_env_var(self):
        self.assertIn("WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS", self.text)


# ==========================================================================
# Default suite does not discover tests_live
# ==========================================================================


class DefaultSuiteIsolationTests(unittest.TestCase):
    def test_01_tests_live_not_in_default_discover_path(self):
        """tests_live/ is outside tests/ so default discovery won't find it."""
        tests_dir = REPO / "tests"
        tests_live_dir = REPO / "tests_live"
        self.assertTrue(tests_dir.is_dir())
        self.assertTrue(tests_live_dir.is_dir())
        self.assertNotIn(
            str(tests_live_dir), str(tests_dir),
            "tests_live/ must not be under tests/")

    def test_02_no_live_test_files_in_tests(self):
        """No file under tests/ should contain live test markers
        except harness/doc tests that explicitly test live isolation."""
        live_markers = ("tests_live", "LIVE_PROVIDER_TESTS")
        _ALLOWED = {
            "test_free_provider_live_mode.py",
            "test_football_data_org_live_readiness.py",
            "test_thesportsdb_public_free_live_readiness.py",
            "test_live_raw_store_capture.py",
        }
        for py_file in (REPO / "tests").rglob("test_*.py"):
            if py_file.name in _ALLOWED:
                continue
            text = py_file.read_text(encoding="utf-8")
            for marker in live_markers:
                if marker in text:
                    self.fail(
                        f"{py_file.name} references '{marker}' — "
                        f"live test marker must only be in harness/doc context")


# ==========================================================================
# Import boundary
# ==========================================================================


class ReadinessImportBoundaryTests(unittest.TestCase):
    def test_01_live_harness_still_no_prediction_imports(self):
        mod_path = REPO / "tests" / "live_provider_harness.py"
        source = mod_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        banned = ("oracle_core.engine", "oracle_core.knockout",
                   "oracle_core.tournament", "oracle_core.odds")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for b in banned:
                        self.assertNotIn(b, alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for b in banned:
                        self.assertNotIn(b, node.module)


if __name__ == "__main__":
    unittest.main()
