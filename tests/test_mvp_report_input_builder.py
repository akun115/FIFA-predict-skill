"""Tests for mvp_report_input_builder — Patch 34 Part 1."""

import unittest

from oracle_core.mvp_report_input_builder import (
    build_mvp_report_input,
    MVPReportInput,
)
from oracle_core.prediction_context_boundary import (
    attach_external_context_to_prediction_output,
)
from oracle_core.web_scout_fallback import (
    WebScoutResult,
    WebScoutEvidence,
    WebScoutRequest,
    DisabledWebScoutAdapter,
    build_web_scout_requests,
    run_web_scout_fallback,
)
from datetime import datetime, timezone


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
        ],
        "advancement_probabilities": {
            "Fictional Alpha FC": 0.65,
            "Fictional Beta FC": 0.35,
        },
        "model_version": "provisional-v1",
    }


class TestMvpReportInputBuilder(unittest.TestCase):
    """Tests for MVP Report Input Builder."""

    def setUp(self):
        self.model_output = _make_model_output()

    # ── Test 29: model_output preserved exactly ──
    def test_model_output_preserved_exactly(self):
        original = dict(self.model_output)
        result = build_mvp_report_input(model_output=self.model_output)
        for key in original:
            self.assertEqual(result.model_output[key], original[key])

    # ── Test 30: provider_context separate ──
    def test_provider_context_separate(self):
        ctx = {"canonical_teams": ["FIC-001"], "snapshot_id": "snap-1"}
        result = build_mvp_report_input(
            model_output=self.model_output,
            context_view_or_assembly_result=ctx,
        )
        self.assertIsNotNone(result.provider_context)
        self.assertIn("canonical_teams", result.provider_context)
        # Model output must NOT contain provider context
        self.assertNotIn("canonical_teams", result.model_output)

    # ── Test 31: market_comparison separate ──
    def test_market_comparison_separate(self):
        market = {"1X2": {"team_a_win": 2.10, "draw": 3.50, "team_b_win": 3.80}}
        result = build_mvp_report_input(
            model_output=self.model_output,
            market_comparison=market,
        )
        self.assertIsNotNone(result.market_comparison)
        self.assertEqual(result.market_comparison, market)
        # Market data must NOT be in model_output
        self.assertNotIn("1X2", result.model_output)

    # ── Test 32: scout_evidence separate ──
    def test_scout_evidence_separate(self):
        scout = WebScoutResult(
            evidence=(
                WebScoutEvidence(
                    evidence_id="ev-1", evidence_type="injuries",
                    summary="Test injury", confidence="synthetic",
                    source_url_or_reference="fixture://test",
                    provenance="fake",
                ),
            ),
            adapter_used="fake",
        )
        result = build_mvp_report_input(
            model_output=self.model_output,
            scout_result=scout,
        )
        self.assertGreater(len(result.scout_evidence), 0)
        # Scout evidence must NOT be in model_output
        self.assertNotIn("evidence_id", result.model_output)

    # ── Test 33: missing probabilities create caveat not fake values ──
    def test_missing_probabilities_creates_caveat(self):
        no_prob_output = {
            "team_a": "Team A",
            "team_b": "Team B",
        }
        result = build_mvp_report_input(model_output=no_prob_output)
        found = False
        for c in result.caveats:
            if "missing result_probabilities" in c.lower() or \
               "result_probabilities" in c.lower():
                found = True
                break
        self.assertTrue(found,
                        "Should have caveat about missing result_probabilities")
        # Must NOT have fake result_probabilities
        self.assertNotIn("result_probabilities", result.model_output)

    # ── Test 34: result_probabilities and advancement_probabilities remain separate ──
    def test_result_and_advancement_separate(self):
        result = build_mvp_report_input(model_output=self.model_output)
        mo = result.model_output
        self.assertIsNot(
            mo.get("result_probabilities"),
            mo.get("advancement_probabilities"),
        )

    # ── Test 35: no odds blending / xG adjustment fields ──
    def test_no_odds_blending_or_xg_adjustment(self):
        result = build_mvp_report_input(model_output=self.model_output)
        forbidden = ["odds_blending", "xg_adjustment", "blended_probabilities"]
        for field in forbidden:
            self.assertNotIn(field, result.model_output,
                             f"Forbidden field '{field}' in model_output")
            if result.provider_context:
                self.assertNotIn(field, result.provider_context,
                                 f"Forbidden field '{field}' in provider_context")

    # ── Test: MVPReportInput structure has all required fields ──
    def test_report_input_structure(self):
        result = build_mvp_report_input(model_output=self.model_output)
        self.assertIsInstance(result, MVPReportInput)
        self.assertIsNotNone(result.model_output)
        self.assertIsNotNone(result.caveats)
        self.assertIsNotNone(result.data_gaps)
        self.assertIsNotNone(result.model_boundary)

    # ── Test: builder does NOT call prediction engine ──
    def test_builder_does_not_call_prediction_engine(self):
        import oracle_core.mvp_report_input_builder as builder_mod
        import inspect
        source = inspect.getsource(builder_mod)
        self.assertNotIn("from oracle_core.engine import", source)
        self.assertNotIn("predict_match(", source)

    # ── Test: builder with contextualized prediction output ──
    def test_builder_with_contextualized_output(self):
        ctx_output = attach_external_context_to_prediction_output(
            model_output=self.model_output,
            context_snapshot={"snapshot_id": "snap-test"},
            data_gaps=("gap1", "gap2"),
        )
        result = build_mvp_report_input(
            model_output=self.model_output,
            context_view_or_assembly_result=ctx_output,
        )
        self.assertIsNotNone(result.provider_context)
        self.assertGreater(len(result.data_gaps), 0)

    # ── Test: no env read ──
    def test_no_env_read(self):
        # Should work without any environment variables
        result = build_mvp_report_input(model_output=self.model_output)
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
