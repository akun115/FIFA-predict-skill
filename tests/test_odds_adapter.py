"""Tests for oracle_core/odds.py — implied probabilities and model-vs-market delta.

All tests use local computation only. No network access. No odds scraping.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from oracle_core.evaluation import evaluate
from oracle_core.odds import (
    ImpliedProbabilities,
    OddsEntry,
    build_odds_index,
    compute_implied,
    compute_implied_1x2,
    compute_implied_over_under,
    load_odds_from_jsonl,
    model_vs_market_delta,
)
from oracle_core.tournament import check_round_robin_integrity
from oracle_core.types import GroupDefinition, ScheduledMatch


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _fixture_schedule() -> tuple[ScheduledMatch, ...]:
    """3 matches with Group A (3 teams, all pairs, all completed)."""
    return (
        ScheduledMatch("wc2026-grpA-aaa-bbb", "A", 1, "TeamAlpha", "TeamBeta",
                       "2026-06-20T00:00:00Z", "Venue", True, (2, 1)),
        ScheduledMatch("wc2026-grpA-aaa-ccc", "A", 1, "TeamAlpha", "TeamGamma",
                       "2026-06-20T01:00:00Z", "Venue", True, (1, 1)),
        ScheduledMatch("wc2026-grpA-bbb-ccc", "A", 3, "TeamBeta", "TeamGamma",
                       "2026-06-26T00:00:00Z", "Venue", True, (1, 0)),
    )


def _fixture_groups() -> dict[str, GroupDefinition]:
    return {"A": GroupDefinition("A", ("TeamAlpha", "TeamBeta", "TeamGamma"))}


def _fixture_odds_entries() -> list[OddsEntry]:
    """3 1X2 odds entries using team_a_win/draw/team_b_win keys."""
    return [
        OddsEntry("wc2026-grpA-aaa-bbb", "fixture", "decimal", "1x2",
                  team_a_win=2.10, draw=3.25, team_b_win=3.60,
                  captured_at="2026-06-20T00:00:00Z"),
        OddsEntry("wc2026-grpA-aaa-ccc", "fixture", "decimal", "1x2",
                  team_a_win=1.80, draw=3.50, team_b_win=4.50,
                  captured_at="2026-06-20T00:00:00Z"),
        OddsEntry("wc2026-grpA-bbb-ccc", "fixture", "decimal", "1x2",
                  team_a_win=2.50, draw=3.10, team_b_win=2.90,
                  captured_at="2026-06-20T00:00:00Z"),
    ]


def _fixture_odds_entry_ou25() -> OddsEntry:
    return OddsEntry("wc2026-ou25-test", "fixture", "decimal", "over_under_2_5",
                     over=1.90, under=1.95, threshold=2.5,
                     captured_at="2026-06-20T00:00:00Z")


# ---------------------------------------------------------------------------
# 1. Decimal odds → raw implied probabilities
# ---------------------------------------------------------------------------


class ImpliedProbabilityTests(unittest.TestCase):
    """Unit tests for odds → implied probability computation."""

    def test_decimal_odds_to_raw_implied(self):
        """1 / decimal_odds = raw implied probability."""
        result = compute_implied_1x2(2.10, 3.25, 3.60)
        self.assertAlmostEqual(result.raw_implied["team_a_win"], 1.0 / 2.10, places=10)
        self.assertAlmostEqual(result.raw_implied["draw"], 1.0 / 3.25, places=10)
        self.assertAlmostEqual(result.raw_implied["team_b_win"], 1.0 / 3.60, places=10)

    def test_output_keys_use_team_a_b_semantics(self):
        """Normalized output keys are team_a_win / draw / team_b_win."""
        result = compute_implied_1x2(2.10, 3.25, 3.60)
        self.assertEqual(
            set(result.normalized.keys()),
            {"team_a_win", "draw", "team_b_win"},
        )
        self.assertNotIn("home_win", result.normalized)
        self.assertNotIn("away_win", result.normalized)

    def test_raw_implied_sums_above_one(self):
        """Raw implied probabilities always sum > 1.0 due to overround."""
        result = compute_implied_1x2(2.10, 3.25, 3.60)
        raw_sum = sum(result.raw_implied.values())
        self.assertGreater(raw_sum, 1.0)

    # -- 2. overround calculation ----------------------------------------------

    def test_overround_calculation(self):
        """overround = sum(raw_implied) - 1.0"""
        result = compute_implied_1x2(2.10, 3.25, 3.60)
        raw = 1.0 / 2.10 + 1.0 / 3.25 + 1.0 / 3.60
        expected_overround = raw - 1.0
        self.assertAlmostEqual(result.overround, expected_overround, places=10)
        self.assertGreater(result.overround, 0.0)

    def test_overround_for_tight_odds(self):
        """Balanced odds with minimal margin → small overround."""
        result = compute_implied_1x2(2.90, 3.10, 2.85)
        self.assertLess(result.overround, 0.10)

    # -- 3. normalized probabilities sum to 1 ----------------------------------

    def test_normalized_probabilities_sum_to_one(self):
        """After overround removal, normalized probs sum to 1.0."""
        for odds in [(2.10, 3.25, 3.60), (1.80, 3.50, 4.50),
                     (1.55, 4.00, 5.50), (2.90, 3.10, 2.85)]:
            with self.subTest(odds=odds):
                result = compute_implied_1x2(*odds)
                total = sum(result.normalized.values())
                self.assertAlmostEqual(total, 1.0, places=10)

    def test_normalized_preserves_relative_ordering(self):
        """Normalization preserves the rank order of outcomes."""
        result = compute_implied_1x2(2.10, 3.25, 3.60)
        self.assertGreater(result.normalized["team_a_win"],
                           result.normalized["draw"])
        self.assertGreater(result.normalized["draw"],
                           result.normalized["team_b_win"])

    # -- 4. invalid odds raise ValueError --------------------------------------

    def test_odds_equal_to_one_raises(self):
        with self.assertRaises(ValueError):
            compute_implied_1x2(1.0, 3.25, 3.60)

    def test_odds_below_one_raises(self):
        with self.assertRaises(ValueError):
            compute_implied_1x2(0.50, 3.25, 3.60)

    def test_negative_odds_raises(self):
        with self.assertRaises(ValueError):
            compute_implied_1x2(-2.10, 3.25, 3.60)

    def test_nan_odds_raises(self):
        with self.assertRaises(ValueError):
            compute_implied_1x2(float("nan"), 3.25, 3.60)

    # -- 5. over/under 2.5 implied probabilities -------------------------------

    def test_over_under_implied_probabilities(self):
        """Over/under odds → implied probabilities with correct key names."""
        result = compute_implied_over_under(1.90, 1.95, 2.5)
        self.assertAlmostEqual(result.raw_implied["over_2_5"], 1.0 / 1.90, places=10)
        self.assertAlmostEqual(result.raw_implied["under_2_5"], 1.0 / 1.95, places=10)
        self.assertAlmostEqual(
            sum(result.normalized.values()), 1.0, places=10,
        )

    def test_over_under_normalized_sums_to_one(self):
        result = compute_implied_over_under(1.90, 1.95)
        self.assertAlmostEqual(
            sum(result.normalized.values()), 1.0, places=10,
        )

    def test_over_under_custom_threshold(self):
        """Custom threshold (3.5) appears in key names."""
        result = compute_implied_over_under(1.70, 2.10, threshold=3.5)
        self.assertIn("over_3_5", result.raw_implied)
        self.assertIn("under_3_5", result.raw_implied)


# ---------------------------------------------------------------------------
# 6. compute_implied dispatch
# ---------------------------------------------------------------------------


class ComputeImpliedDispatchTests(unittest.TestCase):
    """Tests for compute_implied(OddsEntry) dispatch."""

    def test_1x2_entry_dispatches_correctly(self):
        entry = OddsEntry("m1", "fixture", "decimal", "1x2",
                          team_a_win=2.10, draw=3.25, team_b_win=3.60)
        result = compute_implied(entry)
        self.assertIsNotNone(result)
        self.assertEqual(result.market_type, "1x2")
        self.assertAlmostEqual(sum(result.normalized.values()), 1.0, places=10)

    def test_over_under_entry_dispatches_correctly(self):
        entry = OddsEntry("m1", "fixture", "decimal", "over_under_2_5",
                          over=1.90, under=1.95, threshold=2.5)
        result = compute_implied(entry)
        self.assertIsNotNone(result)
        self.assertEqual(result.market_type, "over_under_2_5")
        self.assertIn("over_2_5", result.normalized)

    def test_missing_1x2_fields_returns_none(self):
        entry = OddsEntry("m1", "fixture", "decimal", "1x2",
                          draw=3.25, team_b_win=3.60)
        result = compute_implied(entry)
        self.assertIsNone(result)

    def test_missing_over_under_fields_returns_none(self):
        entry = OddsEntry("m1", "fixture", "decimal", "over_under_2_5",
                          under=1.95)
        result = compute_implied(entry)
        self.assertIsNone(result)

    def test_unknown_market_type_returns_none(self):
        entry = OddsEntry("m1", "fixture", "decimal", "btts")
        result = compute_implied(entry)
        self.assertIsNone(result)

    def test_partial_1x2_with_some_missing_returns_none(self):
        entry = OddsEntry("m1", "fixture", "decimal", "1x2",
                          team_a_win=2.10, team_b_win=3.60)
        result = compute_implied(entry)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 7. model-vs-market delta
# ---------------------------------------------------------------------------


class ModelVsMarketDeltaTests(unittest.TestCase):
    """Tests for model_vs_market_delta()."""

    def test_delta_sign_positive_when_model_higher(self):
        model = {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}
        market = {"team_a_win": 0.45, "draw": 0.29, "team_b_win": 0.26}
        delta = model_vs_market_delta(model, market)
        self.assertAlmostEqual(delta["team_a_win"], 0.10, places=10)
        self.assertAlmostEqual(delta["draw"], -0.04, places=10)
        self.assertAlmostEqual(delta["team_b_win"], -0.06, places=10)

    def test_delta_sum_is_zero(self):
        """Since both sum to 1.0, the delta sum is always 0."""
        model = {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}
        market = {"team_a_win": 0.45, "draw": 0.29, "team_b_win": 0.26}
        delta = model_vs_market_delta(model, market)
        self.assertAlmostEqual(sum(delta.values()), 0.0, places=10)

    def test_delta_only_returns_market_keys(self):
        model = {"team_a_win": 0.50, "draw": 0.30, "team_b_win": 0.20, "extra": 0.10}
        market = {"team_a_win": 0.45, "draw": 0.55}
        delta = model_vs_market_delta(model, market)
        self.assertEqual(set(delta.keys()), {"team_a_win", "draw"})

    def test_delta_with_missing_model_key_uses_zero(self):
        model = {"team_a_win": 0.55}
        market = {"team_a_win": 0.45, "draw": 0.29, "team_b_win": 0.26}
        delta = model_vs_market_delta(model, market)
        self.assertAlmostEqual(delta["draw"], -0.29, places=10)


# ---------------------------------------------------------------------------
# 8. prediction enrichment does not change probabilities
# ---------------------------------------------------------------------------


class PredictionEnrichmentTests(unittest.TestCase):
    """Verify odds-related operations never modify model probabilities."""

    def test_compute_implied_does_not_alter_model_probs(self):
        model_probs = {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}
        original = dict(model_probs)
        _ = compute_implied_1x2(2.10, 3.25, 3.60)
        self.assertEqual(model_probs, original)

    def test_model_vs_market_delta_does_not_mutate_inputs(self):
        model = {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}
        market = {"team_a_win": 0.45, "draw": 0.29, "team_b_win": 0.26}
        model_copy = dict(model)
        market_copy = dict(market)
        _ = model_vs_market_delta(model, market)
        self.assertEqual(model, model_copy)
        self.assertEqual(market, market_copy)


# ---------------------------------------------------------------------------
# 9. evaluation with odds → market metrics
# ---------------------------------------------------------------------------


class EvaluationWithOddsTests(unittest.TestCase):
    """Integration tests: evaluate() with odds_index."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmpdir.name)
        self.schedule = _fixture_schedule()
        self.groups = _fixture_groups()
        self.odds = _fixture_odds_entries()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_log(self, entries: list[dict]) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / "predictions-2026-06-20.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")

    def _make_entry(self, match_id: str, team_a: str, team_b: str,
                    probs: dict[str, float], expected_goals=(1.5, 1.0)) -> dict:
        return {
            "prediction_id": f"pred-{match_id}",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": match_id,
            "match_id_source": "provided",
            "team_a": team_a, "team_b": team_b,
            "model_mode": "provisional",
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": list(expected_goals),
            "result_probabilities": probs,
            "over_under": {}, "top_scores": [],
            "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
        }

    def _make_index(self, entries=None) -> dict:
        if entries is None:
            entries = self.odds
        idx, _ = build_odds_index(entries)
        return idx

    def test_evaluate_with_odds_has_market_metrics(self):
        entries = [
            self._make_entry("wc2026-grpA-aaa-bbb", "TeamAlpha", "TeamBeta",
                             {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}),
        ]
        self._write_log(entries)
        result = evaluate(
            self.log_dir, self.schedule, self.groups,
            odds_index=self._make_index(),
        )
        self.assertIn("market_metrics", result)

    def test_market_metrics_count_matches_settled_with_odds(self):
        entries = [
            self._make_entry("wc2026-grpA-aaa-bbb", "TeamAlpha", "TeamBeta",
                             {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}),
            self._make_entry("wc2026-grpA-aaa-ccc", "TeamAlpha", "TeamGamma",
                             {"team_a_win": 0.30, "draw": 0.40, "team_b_win": 0.30}),
            self._make_entry("wc2026-grpA-bbb-ccc", "TeamBeta", "TeamGamma",
                             {"team_a_win": 0.50, "draw": 0.25, "team_b_win": 0.25}),
        ]
        self._write_log(entries)
        result = evaluate(
            self.log_dir, self.schedule, self.groups,
            odds_index=self._make_index(),
        )
        self.assertEqual(result["settled_predictions"], 3)
        self.assertEqual(result["market_metrics"]["count"], 3)

    def test_market_brier_computed_correctly(self):
        """Market Brier uses market implied probabilities as predictions."""
        entries = [
            self._make_entry("wc2026-grpA-aaa-bbb", "TeamAlpha", "TeamBeta",
                             {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}),
        ]
        self._write_log(entries)
        result = evaluate(
            self.log_dir, self.schedule, self.groups,
            odds_index=self._make_index(),
        )

        market = result["market_metrics"]
        self.assertEqual(market["count"], 1)
        self.assertIsNotNone(market["brier"])
        self.assertIsNotNone(market["1x2_accuracy"])

    def test_evaluate_without_odds_has_no_market_metrics(self):
        entries = [
            self._make_entry("wc2026-grpA-aaa-bbb", "TeamAlpha", "TeamBeta",
                             {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}),
        ]
        self._write_log(entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)
        self.assertNotIn("market_metrics", result)

    def test_evaluate_with_empty_odds_has_zero_market_count(self):
        entries = [
            self._make_entry("wc2026-other-match", "TeamX", "TeamY",
                             {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}),
        ]
        self._write_log(entries)
        result = evaluate(
            self.log_dir, self.schedule, self.groups,
            odds_index=self._make_index(),
        )
        self.assertIn("market_metrics", result)
        self.assertEqual(result["market_metrics"]["count"], 0)

    def test_market_metrics_does_not_affect_model_metrics(self):
        entries = [
            self._make_entry("wc2026-grpA-aaa-bbb", "TeamAlpha", "TeamBeta",
                             {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}),
        ]
        self._write_log(entries)

        result_no_odds = evaluate(self.log_dir, self.schedule, self.groups)
        result_with_odds = evaluate(
            self.log_dir, self.schedule, self.groups,
            odds_index=self._make_index(),
        )

        for key in ("1x2_accuracy", "brier", "log_loss", "rps", "count"):
            self.assertEqual(
                result_no_odds["metrics"][key],
                result_with_odds["metrics"][key],
                f"Model metric '{key}' changed when odds_index was added!",
            )

    def test_market_metrics_uses_team_a_b_keys(self):
        """Market implied probs use team_a_win/draw/team_b_win, matching model keys."""
        entries = [
            self._make_entry("wc2026-grpA-aaa-bbb", "TeamAlpha", "TeamBeta",
                             {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}),
        ]
        self._write_log(entries)
        result = evaluate(
            self.log_dir, self.schedule, self.groups,
            odds_index=self._make_index(),
        )
        # Market metrics should compute successfully using team_a/b keys
        market = result["market_metrics"]
        self.assertIsNotNone(market["brier"])


# ---------------------------------------------------------------------------
# 10. OddsIndex duplicate resolution
# ---------------------------------------------------------------------------


class OddsIndexTests(unittest.TestCase):
    """Tests for build_odds_index() and load_odds_from_jsonl()."""

    def test_build_odds_index_returns_index_and_audit(self):
        entries = _fixture_odds_entries()
        index, audit = build_odds_index(entries)
        self.assertIsInstance(index, dict)
        self.assertIsInstance(audit, dict)
        self.assertEqual(len(index), 3)
        self.assertIn("wc2026-grpA-aaa-bbb", index)

    def test_build_odds_index_audit_no_duplicates(self):
        """Audit reports zero duplicates when all match_ids are unique."""
        entries = _fixture_odds_entries()
        _, audit = build_odds_index(entries)
        self.assertEqual(audit["total_entries"], 3)
        self.assertEqual(audit["unique_match_ids"], 3)
        self.assertEqual(audit["duplicate_count"], 0)
        self.assertIsNone(audit["duplicate_match_ids"])

    def test_duplicate_match_id_with_captured_at_picks_latest(self):
        """When duplicates have captured_at, the entry with latest timestamp wins."""
        entries = [
            OddsEntry("m1", "a", "decimal", "1x2",
                      team_a_win=2.00, draw=3.00, team_b_win=4.00,
                      captured_at="2026-01-01T00:00:00Z"),
            OddsEntry("m1", "b", "decimal", "1x2",
                      team_a_win=2.50, draw=3.00, team_b_win=3.00,
                      captured_at="2026-06-20T00:00:00Z"),  # later
        ]
        index, audit = build_odds_index(entries)
        self.assertEqual(index["m1"].team_a_win, 2.50)
        self.assertEqual(index["m1"].source, "b")
        self.assertEqual(audit["duplicate_count"], 1)
        self.assertEqual(audit["resolved_by_captured_at"], 1)
        self.assertEqual(audit["resolved_by_last_entry"], 0)

    def test_duplicate_match_id_without_captured_at_falls_back_to_last(self):
        """Without captured_at, last entry in list wins."""
        entries = [
            OddsEntry("m1", "early", "decimal", "1x2",
                      team_a_win=2.00, draw=3.00, team_b_win=4.00),
            OddsEntry("m1", "late", "decimal", "1x2",
                      team_a_win=3.00, draw=3.00, team_b_win=2.00),
        ]
        index, audit = build_odds_index(entries)
        self.assertEqual(index["m1"].team_a_win, 3.00)
        self.assertEqual(index["m1"].source, "late")
        self.assertEqual(audit["resolved_by_last_entry"], 1)
        self.assertEqual(audit["resolved_by_captured_at"], 0)

    def test_duplicate_audit_visible_in_output(self):
        """Duplicate match_ids are listed in audit."""
        entries = [
            OddsEntry("m1", "a", "decimal", "1x2",
                      team_a_win=2.00, draw=3.00, team_b_win=4.00),
            OddsEntry("m1", "b", "decimal", "1x2",
                      team_a_win=2.50, draw=3.00, team_b_win=3.00),
        ]
        _, audit = build_odds_index(entries)
        self.assertEqual(audit["duplicate_count"], 1)
        self.assertIsNotNone(audit["duplicate_match_ids"])
        self.assertIn("m1", audit["duplicate_match_ids"])

    def test_mixed_duplicates_with_and_without_timestamps(self):
        """Some duplicates have timestamps, some don't."""
        entries = [
            # m1: duplicates with timestamps
            OddsEntry("m1", "old", "decimal", "1x2",
                      team_a_win=2.00, draw=3.00, team_b_win=4.00,
                      captured_at="2026-01-01T00:00:00Z"),
            OddsEntry("m1", "new", "decimal", "1x2",
                      team_a_win=2.50, draw=3.00, team_b_win=3.00,
                      captured_at="2026-06-20T00:00:00Z"),
            # m2: duplicates without timestamps
            OddsEntry("m2", "first", "decimal", "1x2",
                      team_a_win=1.80, draw=3.50, team_b_win=4.50),
            OddsEntry("m2", "second", "decimal", "1x2",
                      team_a_win=1.90, draw=3.40, team_b_win=4.40),
            # m3: unique, no duplicates
            OddsEntry("m3", "only", "decimal", "1x2",
                      team_a_win=3.00, draw=3.00, team_b_win=2.50),
        ]
        index, audit = build_odds_index(entries)
        self.assertEqual(len(index), 3)
        self.assertEqual(audit["duplicate_count"], 2)
        self.assertEqual(audit["resolved_by_captured_at"], 1)
        self.assertEqual(audit["resolved_by_last_entry"], 1)
        # Verify correct selections
        self.assertEqual(index["m1"].source, "new")
        self.assertEqual(index["m2"].source, "second")

    def test_load_odds_from_jsonl(self):
        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures" / "odds" / "sample.jsonl"
        )
        entries = load_odds_from_jsonl(str(fixture_path))
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[0].match_id, "wc2026-grpA-aaa-bbb")
        self.assertEqual(entries[0].market_type, "1x2")
        self.assertAlmostEqual(entries[0].team_a_win, 2.10, places=10)
        # Over/under entry
        self.assertEqual(entries[3].market_type, "over_under_2_5")
        self.assertAlmostEqual(entries[3].over, 1.90, places=10)

    def test_load_legacy_odds_from_jsonl(self):
        """Legacy home_win/away_win keys are normalized to team_a_win/team_b_win."""
        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures" / "odds" / "legacy_sample.jsonl"
        )
        entries = load_odds_from_jsonl(str(fixture_path))
        self.assertEqual(len(entries), 2)
        # Legacy home_win → team_a_win
        self.assertAlmostEqual(entries[0].team_a_win, 2.10, places=10)
        # Legacy away_win → team_b_win
        self.assertAlmostEqual(entries[0].team_b_win, 3.60, places=10)
        self.assertAlmostEqual(entries[0].draw, 3.25, places=10)


# ---------------------------------------------------------------------------
# OddsEntry from_dict & field normalisation
# ---------------------------------------------------------------------------


class OddsEntryFromDictTests(unittest.TestCase):
    """Tests for OddsEntry.from_dict() with preferred and legacy key names."""

    def test_from_dict_parses_preferred_1x2_fields(self):
        data = {
            "match_id": "m1", "source": "fixture", "odds_format": "decimal",
            "market_type": "1x2",
            "team_a_win": 2.10, "draw": 3.25, "team_b_win": 3.60,
            "captured_at": "2026-06-20T00:00:00Z",
        }
        entry = OddsEntry.from_dict(data)
        self.assertEqual(entry.match_id, "m1")
        self.assertAlmostEqual(entry.team_a_win, 2.10, places=10)
        self.assertAlmostEqual(entry.team_b_win, 3.60, places=10)
        self.assertIsNone(entry.over)
        self.assertIsNone(entry.under)

    def test_from_dict_parses_legacy_home_away_fields(self):
        """Legacy home_win/away_win are normalized to team_a_win/team_b_win."""
        data = {
            "match_id": "m1", "source": "fixture", "odds_format": "decimal",
            "market_type": "1x2",
            "home_win": 2.10, "draw": 3.25, "away_win": 3.60,
            "captured_at": "2026-06-20T00:00:00Z",
        }
        entry = OddsEntry.from_dict(data)
        self.assertAlmostEqual(entry.team_a_win, 2.10, places=10)
        self.assertAlmostEqual(entry.team_b_win, 3.60, places=10)
        self.assertAlmostEqual(entry.draw, 3.25, places=10)

    def test_preferred_fields_override_legacy(self):
        """When both are present, team_a_win/team_b_win take priority."""
        data = {
            "match_id": "m1", "source": "fixture", "odds_format": "decimal",
            "market_type": "1x2",
            "team_a_win": 2.10, "home_win": 9.99,   # preferred wins
            "draw": 3.25,
            "team_b_win": 3.60, "away_win": 8.88,    # preferred wins
        }
        entry = OddsEntry.from_dict(data)
        self.assertAlmostEqual(entry.team_a_win, 2.10, places=10)
        self.assertAlmostEqual(entry.team_b_win, 3.60, places=10)

    def test_from_dict_parses_over_under(self):
        data = {
            "match_id": "m1", "source": "fixture", "odds_format": "decimal",
            "market_type": "over_under_2_5",
            "over": 1.90, "under": 1.95, "threshold": 2.5,
            "captured_at": "2026-06-20T00:00:00Z",
        }
        entry = OddsEntry.from_dict(data)
        self.assertAlmostEqual(entry.over, 1.90, places=10)
        self.assertAlmostEqual(entry.under, 1.95, places=10)
        self.assertIsNone(entry.team_a_win)

    def test_from_dict_missing_fields_are_none(self):
        entry = OddsEntry.from_dict({
            "match_id": "m1", "source": "fixture", "odds_format": "decimal",
            "market_type": "1x2",
        })
        self.assertIsNone(entry.team_a_win)
        self.assertIsNone(entry.draw)
        self.assertIsNone(entry.team_b_win)


if __name__ == "__main__":
    unittest.main()
