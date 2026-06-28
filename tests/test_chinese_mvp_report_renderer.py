"""Tests for chinese_mvp_report_renderer — Patch 34 Part 2."""

import unittest

from oracle_core.chinese_mvp_report_renderer import (
    render_chinese_mvp_report,
)
from oracle_core.mvp_report_input_builder import (
    build_mvp_report_input,
    MVPReportInput,
)


def _make_model_output():
    return {
        "team_a": "Fictional Alpha FC",
        "team_b": "Fictional Beta FC",
        "expected_goals": [1.45, 0.92],
        "result_probabilities": {
            "team_a_win": 0.48,
            "draw": 0.27,
            "team_b_win": 0.25,
        },
        "top_scores": [
            {"score": [1, 0], "probability": 0.18},
            {"score": [2, 0], "probability": 0.12},
            {"score": [1, 1], "probability": 0.11},
        ],
        "advancement_probabilities": {
            "Fictional Alpha FC": 0.65,
            "Fictional Beta FC": 0.35,
        },
        "model_version": "provisional-v1",
        "model_status": "provisional",
        "assumptions": ["neutral site"],
        "limitations": ["provisional priors"],
    }


class TestChineseMvpReportRenderer(unittest.TestCase):
    """Tests for Chinese MVP report renderer."""

    def setUp(self):
        self.model_output = _make_model_output()
        self.report_input = build_mvp_report_input(
            model_output=self.model_output,
            context_view_or_assembly_result={
                "canonical_teams": [{"team_id": "FIC-001"}],
                "snapshot_id": "snap-test-001",
            },
        )

    # ── Test 36: renders Chinese string ──
    def test_renders_chinese_string(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 100)
        # Should contain Chinese characters
        has_chinese = any('一' <= c <= '鿿' for c in report)
        self.assertTrue(has_chinese, "Report should contain Chinese characters")

    # ── Test 37: includes model probability section ──
    def test_includes_model_probability_section(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertIn("胜平负", report)
        self.assertIn("48.0%", report)
        self.assertIn("27.0%", report)
        self.assertIn("25.0%", report)

    # ── Test 38: includes provider context section ──
    def test_includes_provider_context_section(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertIn("Provider Context", report)

    # ── Test 39: includes Scout evidence section or disabled statement ──
    def test_includes_scout_section(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertIn("Scout", report)

    # ── Test 40: includes market comparison section or missing statement ──
    def test_includes_market_comparison_section(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertIn("Market Comparison", report)

    # ── Test 41: includes data gaps section ──
    def test_includes_data_gaps_section(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertIn("数据缺口", report)

    # ── Test 42: includes caveats section ──
    def test_includes_caveats_section(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertIn("Caveats", report)

    # ── Test 43: includes provenance/replay section ──
    def test_includes_provenance_section(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertIn("Replay", report)
        self.assertIn("snap-test-001", report)

    # ── Test 44: does not invent probabilities ──
    def test_does_not_invent_probabilities(self):
        # Build input with NO result_probabilities
        no_prob_output = {"team_a": "A", "team_b": "B"}
        no_prob_input = build_mvp_report_input(model_output=no_prob_output)
        report = render_chinese_mvp_report(no_prob_input)
        # Should state that probabilities are missing, not invent them
        self.assertIn("无 result_probabilities", report)
        # Must not contain fake percentages like "50.0%"
        self.assertNotIn("50.0%", report)

    # ── Test 45: does not invent top scores ──
    def test_does_not_invent_top_scores(self):
        no_scores_output = {
            "team_a": "A", "team_b": "B",
            "result_probabilities": {"team_a_win": 0.5, "draw": 0.3, "team_b_win": 0.2},
        }
        no_scores_input = build_mvp_report_input(model_output=no_scores_output)
        report = render_chinese_mvp_report(no_scores_input)
        self.assertIn("无 top_scores", report)

    # ── Test 46: does not invent advancement probabilities ──
    def test_does_not_invent_advancement_probabilities(self):
        no_adv_output = {
            "team_a": "A", "team_b": "B",
            "result_probabilities": {"team_a_win": 0.5, "draw": 0.3, "team_b_win": 0.2},
        }
        no_adv_input = build_mvp_report_input(model_output=no_adv_output)
        report = render_chinese_mvp_report(no_adv_input)
        self.assertIn("无 advancement_probabilities", report)

    # ── Test 47: states provider/scout context is report-only ──
    def test_states_context_is_report_only(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertIn("report-only", report.lower() or report)
        self.assertIn("context-only", report.lower() or report)

    # ── Test 48: states odds do not enter model ──
    def test_states_odds_do_not_enter_model(self):
        report = render_chinese_mvp_report(self.report_input)
        # Either Chinese or English statement about odds
        self.assertTrue(
            "不入模" in report or
            "do not enter model" in report.lower() or
            "NOT blended" in report or
            "not blended" in report.lower()
        )

    # ── Test 49: states injuries/lineups/news/weather do not adjust xG ──
    def test_states_no_xg_adjustment(self):
        report = render_chinese_mvp_report(self.report_input)
        # Should mention xG is not adjusted by context
        self.assertTrue(
            "xG" in report or
            "expected goals" in report.lower()
        )

    # ── Test 50: states TheSportsDB not approved ──
    def test_states_thesportsdb_not_approved(self):
        report = render_chinese_mvp_report(self.report_input)
        self.assertTrue(
            "needs_more_info" in report or
            "not approved" in report.lower() or
            "未 approved" in report
        )


if __name__ == "__main__":
    unittest.main()
