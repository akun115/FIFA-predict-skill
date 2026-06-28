"""Tests for prediction_context_boundary — Patch 32."""

import unittest

from oracle_core.prediction_context_boundary import (
    attach_external_context_to_prediction_output,
    build_contextualized_prediction_view,
    ContextualizedPredictionOutput,
)
from oracle_core.free_provider_context_assembly import (
    MatchContextAssemblyResult,
    ModelBoundary,
)
from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderFetchResult,
)
from oracle_core.free_provider_mappers import (
    map_thesportsdb_teams,
)
from oracle_core.free_provider_context_assembly import (
    assemble_match_context_from_mapping_results,
)
from datetime import datetime, timezone


def _make_synthetic_model_output():
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


def _make_assembly():
    fetch = ProviderFetchResult(
        provider_name="thesportsdb",
        adapter_version="0.1.0-skeleton",
        capability=ProviderCapability.TEAMS,
        fetched_at=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        source_reference="fixture://thesportsdb/searchteams",
        raw_payload_hash="abc123",
        payload={
            "teams": [
                {"idTeam": "FIC-001", "strTeam": "Fictional Alpha FC",
                 "strCountry": "Fiction"},
                {"idTeam": "FIC-002", "strTeam": "Fictional Beta FC",
                 "strCountry": "Fiction"},
            ],
        },
        completeness={"available": True},
    )
    mapping = map_thesportsdb_teams(fetch)
    return assemble_match_context_from_mapping_results(mapping)


class TestPredictionContextBoundary(unittest.TestCase):
    """Tests for prediction context boundary."""

    def setUp(self):
        self.model_output = _make_synthetic_model_output()

    # ── Test 15: attach context preserves model_output exactly ──
    def test_attach_preserves_model_output(self):
        original = dict(self.model_output)
        result = attach_external_context_to_prediction_output(
            model_output=self.model_output,
            data_gaps=("gap1",),
        )
        # Check all original keys are preserved
        for key in original:
            self.assertIn(key, result.model_output)
            self.assertEqual(result.model_output[key], original[key])

    # ── Test 16: result_probabilities unchanged ──
    def test_result_probabilities_unchanged(self):
        original_rp = dict(self.model_output["result_probabilities"])
        context = {"some": "context", "data": "here"}
        result = attach_external_context_to_prediction_output(
            model_output=self.model_output,
            context_snapshot=context,
        )
        rp = result.model_output.get("result_probabilities", {})
        self.assertEqual(rp, original_rp)

    # ── Test 17: advancement_probabilities unchanged ──
    def test_advancement_probabilities_unchanged(self):
        original_ap = dict(self.model_output["advancement_probabilities"])
        result = attach_external_context_to_prediction_output(
            model_output=self.model_output,
            context_snapshot={"odds": {"team_a_win": 2.10}},
        )
        ap = result.model_output.get("advancement_probabilities", {})
        self.assertEqual(ap, original_ap)

    # ── Test 18: context separate from model_output ──
    def test_context_separate_from_model_output(self):
        context = {"injuries": ["fake injury"]}
        result = attach_external_context_to_prediction_output(
            model_output=self.model_output,
            context_snapshot=context,
        )
        # Context should NOT be merged into model_output
        self.assertNotIn("injuries", result.model_output)
        # Context should be in its own field
        self.assertIsNotNone(result.context_snapshot)
        self.assertIn("injuries", result.context_snapshot)

    # ── Test 19: odds/scout/provider context cannot override model_output ──
    def test_context_cannot_override_model_output(self):
        original_rp = self.model_output["result_probabilities"]["team_a_win"]
        context_with_odds = {
            "result_probabilities": {"team_a_win": 0.99},  # This must not override
        }
        result = attach_external_context_to_prediction_output(
            model_output=self.model_output,
            context_snapshot=context_with_odds,
        )
        # model_output must be unchanged
        self.assertEqual(
            result.model_output["result_probabilities"]["team_a_win"],
            original_rp,
        )
        # Context's fake probabilities must NOT leak into model_output
        self.assertNotEqual(
            result.model_output["result_probabilities"]["team_a_win"],
            0.99,
        )

    # ── Test 20: no prediction engine recalculation ──
    def test_no_prediction_engine_recalculation(self):
        # The boundary modules should NOT import engine
        import oracle_core.prediction_context_boundary as boundary_mod
        import inspect
        source = inspect.getsource(boundary_mod)
        self.assertNotIn("from oracle_core.engine import", source)
        self.assertNotIn("from oracle_core.engine import predict_match", source)
        self.assertNotIn("predict_match(", source)

    # ── Test 21: no forbidden imports or import direction violation ──
    def test_no_forbidden_imports(self):
        import oracle_core.prediction_context_boundary as boundary_mod
        import inspect
        source = inspect.getsource(boundary_mod)
        # Must not import renderer (would create circular dependency risk)
        self.assertNotIn("renderer", source.lower())
        self.assertNotIn("chinese_mvp_report", source)

    # ── Test: build_contextualized_prediction_view works ──
    def test_build_contextualized_view_with_assembly(self):
        assembly = _make_assembly()
        result = build_contextualized_prediction_view(
            model_output=self.model_output,
            context_assembly_result=assembly,
        )
        self.assertIsInstance(result, ContextualizedPredictionOutput)
        self.assertGreater(len(result.data_gaps), 0)
        self.assertGreater(len(result.caveats), 0)

    # ── Test: build_contextualized_view with None assembly ──
    def test_build_contextualized_view_without_assembly(self):
        result = build_contextualized_prediction_view(
            model_output=self.model_output,
            context_assembly_result=None,
        )
        self.assertIsInstance(result, ContextualizedPredictionOutput)
        self.assertIsNone(result.context_snapshot)

    # ── Test: model_output exact equality before/after ──
    def test_model_output_exact_equality_after_attach(self):
        original = dict(self.model_output)
        result = attach_external_context_to_prediction_output(
            model_output=self.model_output,
            context_snapshot={"provider": "thesportsdb", "odds": {"win": 2.0}},
            data_gaps=("gap_a", "gap_b"),
        )
        # Verify ALL keys match
        for key in original:
            self.assertEqual(
                result.model_output[key], original[key],
                f"Key '{key}' was modified by attach_external_context"
            )

    # ── Test: ContextualizedPredictionOutput has correct structure ──
    def test_contextualized_output_structure(self):
        result = attach_external_context_to_prediction_output(
            model_output=self.model_output,
            context_snapshot={"snapshot_id": "snap-1"},
        )
        d = result.to_dict()
        self.assertIn("model_output", d)
        self.assertIn("context_snapshot", d)
        self.assertIn("data_gaps", d)
        self.assertIn("caveats", d)
        self.assertIn("model_boundary", d)

    # ── Test: result_probabilities and advancement_probabilities separate ──
    def test_result_and_advancement_probabilities_separate(self):
        result = attach_external_context_to_prediction_output(
            model_output=self.model_output,
        )
        mo = result.model_output
        self.assertIn("result_probabilities", mo)
        self.assertIn("advancement_probabilities", mo)
        # They must be different dicts
        self.assertIsNot(mo["result_probabilities"], mo.get("advancement_probabilities"))


if __name__ == "__main__":
    unittest.main()
