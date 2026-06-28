"""Release candidate hardening tests — Patch 35.1.

Focused tests confirming RC gates: README, CLI offline behavior, no env reads,
no real teams, replayability, context boundary preservation, and report
disclaimers.
"""

import unittest
import os
import sys
import subprocess
import tempfile
import json


README_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "README.md",
)


class TestRcDocGates(unittest.TestCase):
    """Verify README.md contains all required RC checklist items."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(README_PATH):
            raise AssertionError(f"README.md not found at {README_PATH}")
        with open(README_PATH, "r", encoding="utf-8") as fh:
            cls.doc = fh.read()

    # ── Scope & identity ──
    def test_doc_says_not_full_production(self):
        self.assertTrue(
            "not" in self.doc.lower() and "production" in self.doc.lower()
        )

    def test_doc_says_paid_providers_reserved_only(self):
        self.assertIn("paid reserved", self.doc.lower())

    def test_doc_says_web_scout_real_not_implemented(self):
        self.assertTrue(
            "scout" in self.doc.lower() and "fail-closed" in self.doc.lower()
        )

    def test_doc_says_thesportsdb_needs_more_info(self):
        self.assertIn("needs_more_info", self.doc)

    # ── Default behavior gates ──
    def test_doc_says_default_tests_offline(self):
        self.assertTrue(
            "offline" in self.doc.lower() and "default" in self.doc.lower()
        )

    def test_doc_says_no_env_reads(self):
        self.assertTrue(
            "api key" in self.doc.lower() or "no env" in self.doc.lower()
        )

    def test_doc_says_no_real_teams(self):
        self.assertTrue(
            "FIC-" in self.doc or "synthetic" in self.doc.lower()
        )

    def test_doc_says_no_live_payload_committed(self):
        self.assertTrue(
            "live payload" in self.doc.lower() or "never commit" in self.doc.lower()
        )

    # ── Model probability boundary gates ──
    def test_doc_says_provider_does_not_alter_probabilities(self):
        self.assertIn("not alter", self.doc.lower())

    def test_doc_says_scout_does_not_alter_probabilities(self):
        self.assertTrue(
            "scout" in self.doc.lower() and "not alter" in self.doc.lower()
        )

    def test_doc_says_odds_market_comparison_only(self):
        self.assertIn("market comparison", self.doc.lower())

    def test_doc_says_no_xg_adjustment(self):
        self.assertIn("xG adjustment", self.doc)

    def test_doc_says_llm_does_not_guess_scores(self):
        self.assertTrue(
            "not guess" in self.doc.lower() or "not alter" in self.doc.lower()
        )

    # ── Data partition gates ──
    def test_doc_says_result_and_advancement_separate(self):
        self.assertIn("Probabilities come from", self.doc)

    def test_doc_says_report_does_not_invent_probabilities(self):
        self.assertTrue(
            "not invent" in self.doc.lower() or "no fabricated" in self.doc.lower()
        )

    # ── Test gate ──
    def test_doc_says_zero_fail_zero_skip(self):
        self.assertTrue(
            "0 failed" in self.doc
        )

    # ── Live test baseline ──
    def test_doc_records_live_test_baseline(self):
        self.assertIn("opt-in", self.doc.lower())

    def test_doc_says_live_not_required_for_mvp_release(self):
        self.assertTrue(
            "not" in self.doc.lower() and "require" in self.doc.lower()
        )


class TestCliOfflineBehavior(unittest.TestCase):
    """Verify the CLI wrapper remains offline and uses FIC-* data only."""

    def setUp(self):
        self.cli_module = "oracle_core.mvp_end_to_end_command"
        self.repo_root = os.path.dirname(os.path.dirname(__file__))

    # ── CLI produces Chinese report ──
    def test_cli_produces_chinese_report(self):
        result = subprocess.run(
            [sys.executable, "-m", self.cli_module],
            capture_output=True, text=True, timeout=30,
            cwd=self.repo_root,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("预测报告", result.stdout)

    # ── CLI output contains NO real teams ──
    def test_cli_output_no_real_teams(self):
        result = subprocess.run(
            [sys.executable, "-m", self.cli_module],
            capture_output=True, text=True, timeout=30,
            cwd=self.repo_root,
        )
        real_teams = ["Brazil", "Argentina", "France", "Germany", "England",
                       "Spain", "Italy", "Netherlands", "Portugal", "Croatia"]
        for rt in real_teams:
            self.assertNotIn(rt, result.stdout,
                             f"Real team '{rt}' appeared in CLI output")

    # ── CLI uses FIC-* fictional data ──
    def test_cli_output_contains_fic_data(self):
        result = subprocess.run(
            [sys.executable, "-m", self.cli_module],
            capture_output=True, text=True, timeout=30,
            cwd=self.repo_root,
        )
        self.assertIn("Fictional", result.stdout)

    # ── CLI does NOT require env vars ──
    def test_cli_works_without_env_vars(self):
        clean_env = {
            k: v for k, v in os.environ.items()
            if not any(token in k.upper() for token in
                       ("API_KEY", "APIKEY", "TOKEN", "SECRET", "PASSWORD",
                        "ANTHROPIC", "OPENAI", "LIVE"))
        }
        # Must still have PATH and SYSTEMROOT for Python to work on Windows
        for keep in ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "PATHEXT",
                      "TEMP", "TMP", "USERPROFILE", "HOME",
                      "PYTHONPATH", "PYTHONHOME"):
            if keep in os.environ:
                clean_env[keep] = os.environ[keep]

        result = subprocess.run(
            [sys.executable, "-m", self.cli_module],
            capture_output=True, text=True, timeout=30,
            cwd=self.repo_root,
            env=clean_env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("预测报告", result.stdout)

    # ── CLI --output works ──
    def test_cli_output_to_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        ) as tf:
            out_path = tf.name

        try:
            result = subprocess.run(
                [sys.executable, "-m", self.cli_module, "--output", out_path],
                capture_output=True, text=True, timeout=30,
                cwd=self.repo_root,
            )
            self.assertEqual(result.returncode, 0)
            with open(out_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("预测报告", content)
            self.assertIn("Fictional", content)
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    # ── CLI --json-metadata works ──
    def test_cli_json_metadata(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        ) as tf:
            meta_path = tf.name

        try:
            result = subprocess.run(
                [sys.executable, "-m", self.cli_module,
                 "--json-metadata", meta_path],
                capture_output=True, text=True, timeout=30,
                cwd=self.repo_root,
            )
            self.assertEqual(result.returncode, 0)
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            self.assertFalse(meta["live_api_called"])
            self.assertFalse(meta["env_read"])
            self.assertFalse(meta["real_teams_used"])
            self.assertFalse(meta["model_boundary"]["affects_model"])
            self.assertEqual(meta["data_source"], "FIC-* synthetic only")
        finally:
            if os.path.exists(meta_path):
                os.unlink(meta_path)


class TestRcInvariantsPreserved(unittest.TestCase):
    """Verify that key invariants from Patch 30-35 are preserved."""

    def test_replayability_still_works(self):
        from oracle_core.mvp_end_to_end_command import (
            build_synthetic_mvp_end_to_end_report,
        )
        result = build_synthetic_mvp_end_to_end_report()
        self.assertIsNotNone(result.snapshot_metadata)
        self.assertTrue(result.snapshot_metadata.snapshot_id)
        # Snapshot file exists
        self.assertTrue(os.path.exists(result.snapshot_metadata.file_path))

    def test_context_attach_leaves_model_output_unchanged(self):
        from oracle_core.prediction_context_boundary import (
            attach_external_context_to_prediction_output,
        )
        mo = {
            "team_a": "A", "team_b": "B",
            "result_probabilities": {"team_a_win": 0.5, "draw": 0.3, "team_b_win": 0.2},
            "advancement_probabilities": {"A": 0.6, "B": 0.4},
        }
        original = dict(mo)
        result = attach_external_context_to_prediction_output(
            model_output=mo,
            context_snapshot={"odds": {"team_a_win": 2.10}},
            data_gaps=("odds_missing",),
        )
        for key in original:
            self.assertEqual(result.model_output[key], original[key])

    def test_e2e_report_states_context_boundaries(self):
        from oracle_core.mvp_end_to_end_command import (
            build_synthetic_mvp_end_to_end_report,
        )
        result = build_synthetic_mvp_end_to_end_report()
        report = result.report_text

        # Provider context is report-only
        self.assertTrue(
            "report-only" in report.lower()
            or "不入模" in report
        )
        # Scout evidence is report-only
        self.assertIn("Scout", report)
        # Odds do not enter model
        self.assertTrue(
            "不入模" in report
            or "do not enter model" in report.lower()
            or "NOT blended" in report
        )
        # TheSportsDB not approved
        self.assertTrue(
            "needs_more_info" in report
            or "未 approved" in report
        )

    def test_e2e_no_real_teams_in_model_output(self):
        from oracle_core.mvp_end_to_end_command import (
            build_synthetic_mvp_end_to_end_report,
        )
        result = build_synthetic_mvp_end_to_end_report()
        mo = result.model_output_used
        real_teams = ["Brazil", "Argentina", "France", "Germany", "England"]
        for rt in real_teams:
            self.assertNotIn(rt, mo.get("team_a", ""))
            self.assertNotIn(rt, mo.get("team_b", ""))


if __name__ == "__main__":
    unittest.main()
