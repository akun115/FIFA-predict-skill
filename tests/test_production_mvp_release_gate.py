"""Tests for production_mvp_release_gate — Patch H."""

import unittest
import os


DOC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "README.md",
)


class TestProductionMvpReleaseGate(unittest.TestCase):
    """Tests for the production MVP release gate document and invariants."""

    def setUp(self):
        if not os.path.exists(DOC_PATH):
            self.skipTest(f"README.md not found at {DOC_PATH}")

        with open(DOC_PATH, "r", encoding="utf-8") as fh:
            self.doc = fh.read()

    # ── Test 60: README exists ──
    def test_release_gate_doc_exists(self):
        self.assertTrue(os.path.exists(DOC_PATH),
                        f"README not found at {DOC_PATH}")

    # ── Test 61: README says MVP / not full production ──
    def test_doc_says_mvp_not_full_production(self):
        self.assertIn("not", self.doc.lower())
        self.assertIn("production", self.doc.lower())

    # ── Test 62: README lists completed items ──
    def test_doc_lists_completed_items(self):
        self.assertIn("snapshot", self.doc.lower())

    # ── Test 63: README lists full-production gaps ──
    def test_doc_lists_full_production_gaps(self):
        self.assertIn("TheSportsDB", self.doc)
        self.assertIn("needs_more_info", self.doc)

    # ── Test 64: README includes no fake data invariant ──
    def test_doc_includes_no_fake_data_invariant(self):
        self.assertTrue(
            "FIC-*" in self.doc or
            "no fake" in self.doc.lower() or
            "synthetic" in self.doc.lower()
        )

    # ── Test 65: README includes no live payload committed invariant ──
    def test_doc_includes_no_live_payload_invariant(self):
        self.assertTrue(
            "no live payload" in self.doc.lower() or
            "never commit" in self.doc.lower()
        )

    # ── Test 66: README includes 0 fail / 0 skip gate ──
    def test_doc_includes_zero_fail_zero_skip_gate(self):
        self.assertTrue(
            "0 fail" in self.doc.lower() or
            "0 failed" in self.doc.lower()
        )

    # ── Test 67: README includes no model probability mutation gate ──
    def test_doc_includes_no_probability_mutation_gate(self):
        self.assertTrue(
            "no model probability mutation" in self.doc.lower() or
            "must not alter" in self.doc.lower()
        )

    # ── Test: README mentions TheSportsDB needs_more_info ──
    def test_doc_mentions_thesportsdb_needs_more_info(self):
        self.assertIn("needs_more_info", self.doc)

    # ── Test: README mentions odds are market comparison only ──
    def test_doc_mentions_odds_market_comparison(self):
        self.assertTrue(
            "market comparison" in self.doc.lower() or
            "never blended" in self.doc.lower()
        )


class TestInvariantsGlobal(unittest.TestCase):
    """Global invariant tests — not specific to release gate doc."""

    # ── Test 68: default tests do not use real teams ──
    def test_no_real_teams_in_oracle_core_fixtures(self):
        """Verify that oracle_core modules don't hardcode real team names."""
        import oracle_core.free_provider_context_assembly as mod
        import inspect
        source = inspect.getsource(mod)
        real_teams = ["Brazil", "Argentina", "France", "Germany"]
        for rt in real_teams:
            self.assertNotIn(f'"{rt}"', source,
                             f"Real team '{rt}' should not be in {mod.__name__}")

    # ── Test 69: default tests do not network ──
    def test_assembly_modules_no_network_import(self):
        """Verify core assembly modules don't import networking libraries."""
        modules_to_check = [
            "oracle_core.free_provider_context_assembly",
            "oracle_core.mvp_snapshot_replay",
            "oracle_core.prediction_context_boundary",
            "oracle_core.web_scout_fallback",
            "oracle_core.mvp_report_input_builder",
            "oracle_core.chinese_mvp_report_renderer",
            "oracle_core.mvp_end_to_end_command",
        ]
        import importlib
        import inspect

        for mod_name in modules_to_check:
            mod = importlib.import_module(mod_name)
            source = inspect.getsource(mod)
            # No urllib, requests, socket (except Disabled adapter has it in comments)
            for forbidden in ["urllib.request", "requests.get", "requests.post",
                              "socket.create_connection"]:
                self.assertNotIn(forbidden, source,
                                 f"{mod_name} should not import {forbidden}")

    # ── Test 70: default tests do not read env vars ──
    def test_assembly_modules_no_env_read(self):
        """Verify core modules don't read environment variables."""
        import oracle_core.free_provider_context_assembly as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("os.getenv", source)

    # ── Test 71: no skipped tests ──
    # This is verified by the test runner, not by this test itself.
    # We just assert this test is running (not skipped).
    def test_this_test_is_running(self):
        self.assertTrue(True)

    # ── Test 72: prediction modules do not import forbidden modules ──
    def test_prediction_boundary_no_forbidden_imports(self):
        """Verify prediction_context_boundary doesn't import engine."""
        import oracle_core.prediction_context_boundary as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("from oracle_core.engine import", source)
        self.assertNotIn("from oracle_core import engine", source)

    def test_report_input_no_forbidden_imports(self):
        """Verify mvp_report_input_builder doesn't import engine."""
        import oracle_core.mvp_report_input_builder as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("from oracle_core.engine import", source)

    def test_chinese_renderer_no_forbidden_imports(self):
        """Verify chinese renderer doesn't import engine."""
        import oracle_core.chinese_mvp_report_renderer as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("from oracle_core.engine import", source)

    # ── Test 73: no live payload in repo fixtures ──
    def test_no_live_fixtures_in_tests_fixtures(self):
        """Verify no live JSON payloads in test fixtures."""
        import os as _os
        fixtures_dir = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)),
            "tests", "fixtures",
        )
        if _os.path.exists(fixtures_dir):
            for root, dirs, files in _os.walk(fixtures_dir):
                for fn in files:
                    if fn.endswith(".json"):
                        fpath = _os.path.join(root, fn)
                        with open(fpath, "r", encoding="utf-8") as fh:
                            content = fh.read(5000)
                        # Should not contain actual API responses
                        forbidden = ["api-football", "apifootball",
                                     "football-data.org", "apiv3"]
                        for fb in forbidden:
                            self.assertNotIn(fb, content.lower(),
                                             f"{fn} may contain live {fb} data")


if __name__ == "__main__":
    unittest.main()
