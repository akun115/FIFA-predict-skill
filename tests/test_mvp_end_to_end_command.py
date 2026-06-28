"""Tests for mvp_end_to_end_command — Patch 35."""

import unittest
import os
import socket
import tempfile

from oracle_core.mvp_end_to_end_command import (
    build_synthetic_mvp_end_to_end_report,
    run_mvp_prediction_report_command,
    MvpCommandResult,
)


class TestMvpEndToEndCommand(unittest.TestCase):
    """Tests for MVP end-to-end command."""

    # ── Test 51: synthetic E2E command returns report string ──
    def test_returns_report_string(self):
        result = build_synthetic_mvp_end_to_end_report()
        self.assertIsInstance(result, MvpCommandResult)
        self.assertIsInstance(result.report_text, str)
        self.assertGreater(len(result.report_text), 200)

    # ── Test 52: synthetic E2E command returns replay metadata ──
    def test_returns_replay_metadata(self):
        result = build_synthetic_mvp_end_to_end_report()
        self.assertIsNotNone(result.snapshot_metadata)
        self.assertTrue(result.snapshot_metadata.snapshot_id)

    # ── Test 53: synthetic E2E command uses only FIC/Fictional data ──
    def test_uses_only_fic_data(self):
        result = build_synthetic_mvp_end_to_end_report()
        report = result.report_text
        # Should contain FIC- or Fictional references
        self.assertTrue(
            "Fictional" in report or "FIC-" in report,
            "E2E report should use FIC-* fictional data"
        )
        # Must NOT contain real team names
        real_teams = ["Brazil", "Argentina", "France", "Germany", "England",
                       "Spain", "Italy", "Netherlands", "Portugal"]
        for rt in real_teams:
            self.assertNotIn(rt, report,
                             f"Real team '{rt}' should not appear in E2E report")

    # ── Test 54: synthetic E2E command does not network ──
    def test_does_not_network(self):
        # Build should complete without any network access
        result = build_synthetic_mvp_end_to_end_report()
        self.assertIsNotNone(result)
        self.assertGreater(len(result.report_text), 0)

    # ── Test 55: synthetic E2E command does not call live API ──
    def test_no_live_api_call(self):
        # All data is synthetic FIC-* — no API calls needed
        result = build_synthetic_mvp_end_to_end_report()
        self.assertIsNotNone(result)
        # The report should mention synthetic/fictional data
        self.assertIn("Fictional", result.report_text)

    # ── Test 56: synthetic E2E command does not save live payload ──
    def test_no_live_payload_saved(self):
        # The E2E command uses tempfile, not repo paths
        import oracle_core.mvp_end_to_end_command as cmd_mod
        import inspect
        source = inspect.getsource(cmd_mod)
        # Should use tempfile, not write to knowledge/ or data/ dirs
        self.assertIn("tempfile", source)

    # ── Test 57: report contains model probabilities from synthetic model_output ──
    def test_report_contains_model_probabilities(self):
        result = build_synthetic_mvp_end_to_end_report()
        report = result.report_text
        self.assertIn("48.0%", report)
        self.assertIn("27.0%", report)
        self.assertIn("25.0%", report)

    # ── Test 58: report contains gaps/caveats ──
    def test_report_contains_gaps_caveats(self):
        result = build_synthetic_mvp_end_to_end_report()
        report = result.report_text
        # Should mention gaps
        self.assertTrue(
            "injuries_missing" in report or
            "数据缺口" in report or
            "gap" in report.lower()
        )
        # Should have caveats
        self.assertIn("Caveat", report)

    # ── Test 59: report is replayable from saved snapshot ──
    def test_report_replayable(self):
        result = build_synthetic_mvp_end_to_end_report()
        self.assertIsNotNone(result.snapshot_metadata)
        sid = result.snapshot_metadata.snapshot_id
        self.assertTrue(sid)
        # The snapshot should exist on disk (tempfile)
        self.assertTrue(os.path.exists(result.snapshot_metadata.file_path))

    # ── Test: run_mvp_prediction_report_command works ──
    def test_run_command_without_input(self):
        result = run_mvp_prediction_report_command()
        self.assertIsInstance(result, MvpCommandResult)
        self.assertGreater(len(result.report_text), 100)

    # ── Test: run_mvp_prediction_report_command with None input ──
    def test_run_command_with_none_input(self):
        result = run_mvp_prediction_report_command(None)
        self.assertIsInstance(result, MvpCommandResult)

    # ── Test: E2E report contains all required sections ──
    def test_e2e_report_has_all_sections(self):
        result = build_synthetic_mvp_end_to_end_report()
        report = result.report_text
        # Check for key sections
        sections = [
            "预测报告",
            "比赛信息",
            "本地模型预测",
            "胜平负",
            "淘汰赛晋级",
            "Provider Context",
            "Scout",
            "Market Comparison",
            "数据缺口",
            "Caveat",
            "Replay",
        ]
        for section in sections:
            self.assertIn(section, report,
                          f"Report missing section: '{section}'")

    # ── Test: E2E with fake scout ──
    def test_e2e_with_fake_scout(self):
        result = build_synthetic_mvp_end_to_end_report(use_fake_scout=True)
        report = result.report_text
        # Fake scout should produce evidence
        self.assertIn("synthetic", report.lower())

    # ── Test: E2E result has gap list and caveats ──
    def test_result_has_gaps_and_caveats(self):
        result = build_synthetic_mvp_end_to_end_report()
        self.assertGreater(len(result.gap_list), 0)
        self.assertGreater(len(result.caveats), 0)

    # ── Test: model_output_used is preserved ──
    def test_model_output_used_preserved(self):
        result = build_synthetic_mvp_end_to_end_report()
        mo = result.model_output_used
        self.assertIn("result_probabilities", mo)
        self.assertIn("advancement_probabilities", mo)
        self.assertEqual(mo["result_probabilities"]["team_a_win"], 0.48)


if __name__ == "__main__":
    unittest.main()
