"""Tests for knockout advancement evaluation — Patch 12.

Covers: advancement_accuracy, advancement_brier, advancement_log_loss,
winner resolution, by_stage/by_round breakdowns, 1X2 metric invariance.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
import unittest

from oracle_core.evaluation import (
    AdvancementMetricBundle,
    MetricBundle,
    _classify_round,
    _classify_stage,
    _is_knockout_entry,
    _resolve_advancement_winner,
    _safe_log,
    evaluate,
)
from oracle_core.types import GroupDefinition, ScheduledMatch


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _knockout_schedule() -> tuple[ScheduledMatch, ...]:
    """Schedule with 1 group match + 3 knockout matches (2 R16, 1 QF)."""
    return (
        ScheduledMatch(
            "wc2026-grpA-aaa-bbb", "A", 1,
            "TeamAlpha", "TeamBeta",
            "2026-06-20T00:00:00Z", "Venue", True, (2, 1),
        ),
        # R16-01: regulation win
        ScheduledMatch(
            "wc2026-R16-01", "R16", 4,
            "TeamAlpha", "TeamGamma",
            "2026-06-30T00:00:00Z", "Venue", True, (3, 0),
        ),
        # R16-02: draw — needs knockout_winners to resolve
        ScheduledMatch(
            "wc2026-R16-02", "R16", 4,
            "TeamBeta", "TeamDelta",
            "2026-06-30T00:00:00Z", "Venue", True, (1, 1),
        ),
        # QF-01: regulation win
        ScheduledMatch(
            "wc2026-QF-01", "QF", 5,
            "TeamAlpha", "TeamEpsilon",
            "2026-07-04T00:00:00Z", "Venue", True, (2, 1),
        ),
    )


def _knockout_groups() -> dict[str, GroupDefinition]:
    return {"A": GroupDefinition("A", ("TeamAlpha", "TeamBeta", "TeamGamma"))}


def _knockout_winners() -> dict[str, str]:
    """R16-01: TeamAlpha wins (same as regulation). R16-02: TeamBeta wins in ET/PK."""
    return {
        "wc2026-R16-01": "TeamAlpha",
        "wc2026-R16-02": "TeamBeta",
        "wc2026-QF-01": "TeamAlpha",
    }


def _make_advancement_probs(
    team_a_advances: float, team_b_advances: float,
) -> dict:
    """Minimal advancement_probabilities dict with required keys."""
    draw_prob = 1.0 - team_a_advances - team_b_advances
    # Build a valid-looking decomposition
    reg_win_a = max(0, team_a_advances - 0.1)
    reg_win_b = max(0, team_b_advances - 0.1)
    regulation = reg_win_a + reg_win_b
    extra = max(0, 1.0 - regulation) * 0.35
    penalties = max(0, 1.0 - regulation) * 0.65

    return {
        "team_a_advances": team_a_advances,
        "team_b_advances": team_b_advances,
        "decided_in_regulation": regulation,
        "decided_in_extra_time": extra,
        "decided_on_penalties": penalties,
        "team_a_regulation_component": reg_win_a,
        "team_b_regulation_component": reg_win_b,
        "team_a_extra_time_component": extra * 0.5,
        "team_b_extra_time_component": extra * 0.5,
        "team_a_penalty_component": penalties * 0.5,
        "team_b_penalty_component": penalties * 0.5,
        "et_pk_source": "default",
        "extra_time_resolves_probability": 0.35,
        "team_a_extra_time_win_share": 0.50,
        "team_b_extra_time_win_share": 0.50,
        "team_a_penalty_win_probability": 0.50,
        "team_b_penalty_win_probability": 0.50,
    }


def _knockout_log_entries() -> list[dict]:
    """4 entries: 1 group-stage + 3 knockout."""
    base = {
        "predicted_at": "2026-06-20T00:00:00Z",
        "match_id": "",
        "match_id_source": "missing",
        "model_name": "test",
        "model_version": "test-v1",
        "model_artifact_hash": "h1",
        "input_context_hash": "h2",
        "category": "world_cup",
        "neutral_site": True,
        "expected_goals": [1.5, 1.0],
        "result_probabilities": {"team_a_win": 0.45, "draw": 0.28, "team_b_win": 0.27},
        "over_under": {},
        "top_scores": [],
        "score_matrix_hash": "h3",
        "tournament_context_available": False,
        "limitations": [],
        "source_snapshot_refs": {},
    }
    return [
        # Entry 0: group-stage — no advancement
        {
            **base,
            "prediction_id": "pred-group-01",
            "team_a": "TeamAlpha",
            "team_b": "TeamBeta",
        },
        # Entry 1: R16-01 — TeamAlpha heavily favored, actual winner TeamAlpha (regulation 3-0)
        {
            **base,
            "prediction_id": "pred-R16-01",
            "match_id": "wc2026-R16-01",
            "match_id_source": "provided",
            "team_a": "TeamAlpha",
            "team_b": "TeamGamma",
            "advancement_probabilities": _make_advancement_probs(0.85, 0.15),
        },
        # Entry 2: R16-02 — TeamBeta slightly favored, actual winner TeamBeta (ET/PK after draw)
        {
            **base,
            "prediction_id": "pred-R16-02",
            "match_id": "wc2026-R16-02",
            "match_id_source": "provided",
            "team_a": "TeamBeta",
            "team_b": "TeamDelta",
            "advancement_probabilities": _make_advancement_probs(0.55, 0.45),
        },
        # Entry 3: QF-01 — TeamAlpha advances, but prediction got it wrong
        {
            **base,
            "prediction_id": "pred-QF-01",
            "match_id": "wc2026-QF-01",
            "match_id_source": "provided",
            "team_a": "TeamAlpha",
            "team_b": "TeamEpsilon",
            # Prediction favors TeamEpsilon (team_b) but actual winner is TeamAlpha
            "advancement_probabilities": _make_advancement_probs(0.35, 0.65),
        },
    ]


def _write_log(log_dir: Path, entries: list[dict]) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "predictions-2026-06-20.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------


class KnockoutHelperTests(unittest.TestCase):
    """Low-level helper function correctness."""

    def test_is_knockout_entry_true(self):
        entry = {"advancement_probabilities": {"team_a_advances": 0.6}}
        self.assertTrue(_is_knockout_entry(entry))

    def test_is_knockout_entry_false_when_none(self):
        entry = {"advancement_probabilities": None}
        self.assertFalse(_is_knockout_entry(entry))

    def test_is_knockout_entry_false_when_missing(self):
        entry = {}
        self.assertFalse(_is_knockout_entry(entry))

    def test_classify_stage_group(self):
        match = ScheduledMatch(
            "m1", "A", 1, "a", "b", "2026-01-01T00:00:00Z", "V", True,
        )
        groups = {"A": GroupDefinition("A", ("a", "b", "c"))}
        self.assertEqual(_classify_stage(match, groups), "group")

    def test_classify_stage_knockout(self):
        match = ScheduledMatch(
            "m1", "R16", 4, "a", "b", "2026-01-01T00:00:00Z", "V", True,
        )
        self.assertEqual(_classify_stage(match, {}), "knockout")

    def test_classify_stage_other(self):
        match = ScheduledMatch(
            "m1", "unknown_round", 1, "a", "b", "2026-01-01T00:00:00Z", "V", True,
        )
        self.assertEqual(_classify_stage(match, {}), "other")

    def test_classify_round_r16(self):
        match = ScheduledMatch(
            "m1", "R16", 4, "a", "b", "2026-01-01T00:00:00Z", "V", True,
        )
        self.assertEqual(_classify_round(match), "R16")

    def test_classify_round_group_is_other(self):
        match = ScheduledMatch(
            "m1", "A", 1, "a", "b", "2026-01-01T00:00:00Z", "V", True,
        )
        self.assertEqual(_classify_round(match), "other")


# ---------------------------------------------------------------------------
# Winner resolution tests
# ---------------------------------------------------------------------------


class WinnerResolutionTests(unittest.TestCase):
    """_resolve_advancement_winner priority logic."""

    def setUp(self):
        self.match = ScheduledMatch(
            "wc2026-R16-01", "R16", 4, "TeamA", "TeamB",
            "2026-01-01T00:00:00Z", "V", True, (2, 1),
        )

    def test_knockout_winners_dict_priority(self):
        kw = {"wc2026-R16-01": "TeamB"}
        result = _resolve_advancement_winner(self.match, {}, kw)
        self.assertEqual(result, "team_b")

    def test_knockout_winners_not_matching_returns_none_for_unknown(self):
        """Winner name not matching either team → falls through to regulation."""
        kw = {"wc2026-R16-01": "TeamC"}
        # TeamC is not team_a or team_b → not matched at priority 1
        # Falls through to priority 3: regulation score (2,1) → team_a wins
        result = _resolve_advancement_winner(self.match, {}, kw)
        self.assertEqual(result, "team_a")

    def test_entry_winner_field_priority(self):
        entry = {"winner": "TeamB", "team_a": "TeamA", "team_b": "TeamB"}
        result = _resolve_advancement_winner(self.match, entry, None)
        self.assertEqual(result, "team_b")

    def test_regulation_score_non_draw_infers_winner(self):
        result = _resolve_advancement_winner(self.match, {}, None)
        self.assertEqual(result, "team_a")

    def test_regulation_score_team_b_wins(self):
        match = ScheduledMatch(
            "wc2026-R16-02", "R16", 4, "TeamA", "TeamB",
            "2026-01-01T00:00:00Z", "V", True, (0, 2),
        )
        result = _resolve_advancement_winner(match, {}, None)
        self.assertEqual(result, "team_b")

    def test_draw_no_winner_returns_none(self):
        match = ScheduledMatch(
            "wc2026-R16-03", "R16", 4, "TeamA", "TeamB",
            "2026-01-01T00:00:00Z", "V", True, (1, 1),
        )
        result = _resolve_advancement_winner(match, {}, None)
        self.assertIsNone(result)

    def test_draw_with_knockout_winners_resolves(self):
        match = ScheduledMatch(
            "wc2026-R16-03", "R16", 4, "TeamA", "TeamB",
            "2026-01-01T00:00:00Z", "V", True, (1, 1),
        )
        kw = {"wc2026-R16-03": "TeamA"}
        result = _resolve_advancement_winner(match, {}, kw)
        self.assertEqual(result, "team_a")


# ---------------------------------------------------------------------------
# AdvancementMetricBundle tests
# ---------------------------------------------------------------------------


class AdvancementMetricBundleTests(unittest.TestCase):
    """AdvancementMetricBundle computes correct accuracy, Brier, log-loss."""

    def test_empty_bundle(self):
        b = AdvancementMetricBundle()
        d = b.to_dict()
        self.assertEqual(d["advancement_count"], 0)
        self.assertIsNone(d["advancement_accuracy"])
        self.assertIsNone(d["advancement_brier"])
        self.assertIsNone(d["advancement_log_loss"])

    def test_single_entry_perfect_prediction(self):
        b = AdvancementMetricBundle()
        b.add_settled(_make_advancement_probs(1.0, 0.0), "team_a")
        d = b.to_dict()
        self.assertEqual(d["advancement_count"], 1)
        self.assertAlmostEqual(d["advancement_accuracy"], 1.0)
        self.assertAlmostEqual(d["advancement_brier"], 0.0)
        self.assertAlmostEqual(d["advancement_log_loss"], 0.0)

    def test_two_correct_one_incorrect(self):
        b = AdvancementMetricBundle()
        # Correct: higher prob = actual
        b.add_settled(_make_advancement_probs(0.70, 0.30), "team_a")
        b.add_settled(_make_advancement_probs(0.40, 0.60), "team_b")
        # Incorrect: higher prob team_a but actual team_b
        b.add_settled(_make_advancement_probs(0.65, 0.35), "team_b")
        d = b.to_dict()
        self.assertEqual(d["advancement_count"], 3)
        self.assertAlmostEqual(d["advancement_accuracy"], 2.0 / 3.0)

    def test_brier_manual_verification(self):
        """Brier for binary advancement: ((p_a - o_a)^2 + (p_b - o_b)^2) / 2."""
        b = AdvancementMetricBundle()
        # probs: team_a=0.8, team_b=0.2, actual=team_a → o_a=1, o_b=0
        # Brier = ((0.8-1)^2 + (0.2-0)^2) / 2 = (0.04 + 0.04) / 2 = 0.04
        b.add_settled(_make_advancement_probs(0.80, 0.20), "team_a")
        d = b.to_dict()
        self.assertAlmostEqual(d["advancement_brier"], 0.04)

    def test_log_loss_manual_verification(self):
        """Log loss: -ln(p_actual)."""
        b = AdvancementMetricBundle()
        # team_a_advances=0.7, actual=team_a → -ln(0.7)
        b.add_settled(_make_advancement_probs(0.70, 0.30), "team_a")
        d = b.to_dict()
        expected = -math.log(0.70)
        self.assertAlmostEqual(d["advancement_log_loss"], expected)

    def test_missing_count_recorded(self):
        b = AdvancementMetricBundle()
        b.record_missing()
        b.record_missing()
        d = b.to_dict()
        self.assertEqual(d["advancement_count"], 0)
        self.assertEqual(d["advancement_missing_count"], 2)


# ---------------------------------------------------------------------------
# Integration tests: evaluate() with knockout data
# ---------------------------------------------------------------------------


class KnockoutEvaluationIntegrationTests(unittest.TestCase):
    """Full evaluate() pipeline with knockout fixture data."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmpdir.name)
        self.schedule = _knockout_schedule()
        self.groups = _knockout_groups()
        self.kw = _knockout_winners()

    def tearDown(self):
        self.tmpdir.cleanup()

    # -- 1. Advancement accuracy -----------------------------------------------

    def test_advancement_accuracy(self):
        _write_log(self.log_dir, _knockout_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)

        adv = result["advancement_metrics"]["all"]
        self.assertEqual(adv["advancement_count"], 3)
        # R16-01: pred 0.85/0.15 → team_a, actual team_a ✓
        # R16-02: pred 0.55/0.45 → team_a (TeamBeta), actual TeamBeta ✓
        # QF-01:  pred 0.35/0.65 → team_b, actual TeamAlpha ✗
        self.assertAlmostEqual(adv["advancement_accuracy"], 2.0 / 3.0)

    def test_team_a_favored_team_a_wins_correct(self):
        """Higher team_a advancement prob + team_a winner → correct."""
        entries = [{
            "prediction_id": "pred-a-wins",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "wc2026-R16-01",
            "match_id_source": "provided",
            "team_a": "TeamAlpha",
            "team_b": "TeamGamma",
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [1.5, 1.0],
            "result_probabilities": {"team_a_win": 0.60, "draw": 0.25, "team_b_win": 0.15},
            "over_under": {}, "top_scores": [], "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
            "advancement_probabilities": _make_advancement_probs(0.75, 0.25),
        }]
        _write_log(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)
        adv = result["advancement_metrics"]["all"]
        self.assertEqual(adv["advancement_count"], 1)
        self.assertAlmostEqual(adv["advancement_accuracy"], 1.0)

    def test_team_a_favored_team_b_wins_incorrect(self):
        """Higher team_a advancement prob but team_b winner → incorrect."""
        entries = [{
            "prediction_id": "pred-a-favored-b-wins",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "wc2026-QF-01",
            "match_id_source": "provided",
            "team_a": "TeamAlpha",
            "team_b": "TeamEpsilon",
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [1.5, 1.0],
            "result_probabilities": {"team_a_win": 0.35, "draw": 0.25, "team_b_win": 0.40},
            "over_under": {}, "top_scores": [], "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
            # Prediction favors TeamEpsilon (team_b) but actual winner is TeamAlpha
            "advancement_probabilities": _make_advancement_probs(0.35, 0.65),
        }]
        _write_log(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)
        adv = result["advancement_metrics"]["all"]
        self.assertEqual(adv["advancement_count"], 1)
        self.assertAlmostEqual(adv["advancement_accuracy"], 0.0)

    def test_advancement_brier_and_log_loss(self):
        _write_log(self.log_dir, _knockout_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)
        adv = result["advancement_metrics"]["all"]
        self.assertEqual(adv["advancement_count"], 3)
        self.assertIsNotNone(adv["advancement_brier"])
        self.assertIsNotNone(adv["advancement_log_loss"])
        self.assertGreater(adv["advancement_brier"], 0.0)
        self.assertGreater(adv["advancement_log_loss"], 0.0)

    # -- 2. Missing advancement handling --------------------------------------

    def test_missing_advancement_probabilities_no_effect(self):
        """Entries without advancement_probabilities do not affect advancement metrics."""
        entries = [
            {  # Group entry — no advancement
                "prediction_id": "pred-group-only",
                "predicted_at": "2026-06-20T00:00:00Z",
                "match_id": "wc2026-grpA-aaa-bbb",
                "match_id_source": "provided",
                "team_a": "TeamAlpha", "team_b": "TeamBeta",
                "model_name": "test", "model_version": "test-v1",
                "model_artifact_hash": "h1", "input_context_hash": "h2",
                "category": "world_cup", "neutral_site": True,
                "expected_goals": [1.5, 1.0],
                "result_probabilities": {"team_a_win": 0.50, "draw": 0.30, "team_b_win": 0.20},
                "over_under": {}, "top_scores": [], "score_matrix_hash": "h3",
                "tournament_context_available": False,
                "limitations": [], "source_snapshot_refs": {},
            },
        ]
        _write_log(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)
        adv = result["advancement_metrics"]["all"]
        self.assertEqual(adv["advancement_count"], 0)
        self.assertEqual(adv["advancement_missing_count"], 0)

    def test_draw_no_winner_advancement_missing(self):
        """Draw without knockout_winners → advancement missing, not counted."""
        entries = [{
            "prediction_id": "pred-draw-no-winner",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "wc2026-R16-02",
            "match_id_source": "provided",
            "team_a": "TeamBeta", "team_b": "TeamDelta",
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [1.0, 1.0],
            "result_probabilities": {"team_a_win": 0.30, "draw": 0.40, "team_b_win": 0.30},
            "over_under": {}, "top_scores": [], "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
            "advancement_probabilities": _make_advancement_probs(0.55, 0.45),
        }]
        _write_log(self.log_dir, entries)
        # No knockout_winners → R16-02 is a draw (1,1), winner cannot be inferred
        result = evaluate(self.log_dir, self.schedule, self.groups)
        adv = result["advancement_metrics"]["all"]
        self.assertEqual(adv["advancement_count"], 0)
        self.assertEqual(adv["advancement_missing_count"], 1)

    def test_missing_winner_resolved_by_regulation_non_draw(self):
        """Non-draw regulation score infers winner even without knockout_winners."""
        entries = [{
            "prediction_id": "pred-reg-win",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "wc2026-R16-01",
            "match_id_source": "provided",
            "team_a": "TeamAlpha", "team_b": "TeamGamma",
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [2.0, 0.5],
            "result_probabilities": {"team_a_win": 0.70, "draw": 0.20, "team_b_win": 0.10},
            "over_under": {}, "top_scores": [], "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
            "advancement_probabilities": _make_advancement_probs(0.80, 0.20),
        }]
        _write_log(self.log_dir, entries)
        # No knockout_winners, but regulation score is (3,0) → team_a wins
        result = evaluate(self.log_dir, self.schedule, self.groups)
        adv = result["advancement_metrics"]["all"]
        self.assertEqual(adv["advancement_count"], 1)
        self.assertAlmostEqual(adv["advancement_accuracy"], 1.0)

    # -- 3. Existing 1X2 metrics unchanged ------------------------------------

    def test_1x2_metrics_unchanged_with_knockout_data(self):
        """1X2 metrics computed independently of advancement."""
        _write_log(self.log_dir, _knockout_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)

        metrics = result["metrics"]
        self.assertEqual(metrics["count"], 4)  # 1 group + 3 knockout settled
        self.assertIsNotNone(metrics["1x2_accuracy"])
        self.assertIsNotNone(metrics["brier"])
        self.assertIsNotNone(metrics["log_loss"])
        # 1X2 metrics unchanged by advancement
        self.assertNotIn("advancement_count", metrics)

    def test_group_only_advancement_all_zero(self):
        """Group-stage-only logs → advancement_count=0, accuracy=None."""
        entries = [{
            "prediction_id": "pred-group",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "wc2026-grpA-aaa-bbb",
            "match_id_source": "provided",
            "team_a": "TeamAlpha", "team_b": "TeamBeta",
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [1.5, 1.0],
            "result_probabilities": {"team_a_win": 0.50, "draw": 0.30, "team_b_win": 0.20},
            "over_under": {}, "top_scores": [], "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
        }]
        _write_log(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)
        adv = result["advancement_metrics"]["all"]
        self.assertEqual(adv["advancement_count"], 0)
        self.assertEqual(adv["advancement_missing_count"], 0)
        self.assertIsNone(adv["advancement_accuracy"])

    # -- 4. by_stage / by_round breakdowns ------------------------------------

    def test_by_stage_breakdown_includes_group_and_knockout(self):
        _write_log(self.log_dir, _knockout_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)

        self.assertIn("by_stage", result)
        by_stage = result["by_stage"]
        self.assertIn("all", by_stage)
        self.assertIn("group", by_stage)
        self.assertIn("knockout", by_stage)

        # Group: 1 settled entry
        self.assertEqual(by_stage["group"]["count"], 1)
        # Knockout: 3 settled entries
        self.assertEqual(by_stage["knockout"]["count"], 3)
        # all = group + knockout
        self.assertEqual(
            by_stage["all"]["count"],
            by_stage["group"]["count"] + by_stage["knockout"]["count"],
        )

    def test_by_round_includes_r16_and_qf(self):
        _write_log(self.log_dir, _knockout_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)

        self.assertIn("by_round", result)
        by_round = result["by_round"]
        self.assertIn("R16", by_round)
        self.assertIn("QF", by_round)
        self.assertEqual(by_round["R16"]["count"], 2)
        self.assertEqual(by_round["QF"]["count"], 1)

    def test_advancement_by_stage_breakdown(self):
        _write_log(self.log_dir, _knockout_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)

        adv = result["advancement_metrics"]
        self.assertIn("by_stage", adv)
        self.assertIn("knockout", adv["by_stage"])
        self.assertEqual(adv["by_stage"]["knockout"]["advancement_count"], 3)

    def test_advancement_by_round_breakdown(self):
        _write_log(self.log_dir, _knockout_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)

        adv = result["advancement_metrics"]
        self.assertIn("by_round", adv)
        self.assertIn("R16", adv["by_round"])
        self.assertIn("QF", adv["by_round"])
        self.assertEqual(adv["by_round"]["R16"]["advancement_count"], 2)
        self.assertEqual(adv["by_round"]["QF"]["advancement_count"], 1)

    # -- 5. data_quality still works ------------------------------------------

    def test_data_quality_breakdown_with_knockout(self):
        _write_log(self.log_dir, _knockout_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)

        by_dq = result["by_data_quality"]
        self.assertIn("ok", by_dq)
        # Group A has 3 teams but only 1 pairing → check_round_robin_integrity → "warning"
        # R16-01, R16-02, QF-01 are knockout → "ok" (3 entries)
        self.assertEqual(by_dq["ok"]["count"], 3)
        self.assertEqual(by_dq["warning"]["count"], 1)

    def test_knockout_no_group_still_ok(self):
        """Knockout matches without groups → data_quality='ok' (not 'no_group')."""
        entries = [{
            "prediction_id": "pred-ko-no-groups",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "wc2026-R16-01",
            "match_id_source": "provided",
            "team_a": "TeamAlpha", "team_b": "TeamGamma",
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [2.0, 0.5],
            "result_probabilities": {"team_a_win": 0.70, "draw": 0.20, "team_b_win": 0.10},
            "over_under": {}, "top_scores": [], "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
            "advancement_probabilities": _make_advancement_probs(0.80, 0.20),
        }]
        _write_log(self.log_dir, entries)
        # No groups passed → knockout match should be "ok", not "no_group"
        result = evaluate(self.log_dir, self.schedule, {})
        by_dq = result["by_data_quality"]
        self.assertIn("ok", by_dq)
        self.assertEqual(by_dq["ok"]["count"], 1)


# ---------------------------------------------------------------------------
# Metric invariance: advancement does NOT affect 1X2
# ---------------------------------------------------------------------------


class MetricInvarianceTests(unittest.TestCase):
    """Advancement computation must not change 1X2 metrics."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmpdir.name)
        self.schedule = _knockout_schedule()
        self.groups = _knockout_groups()
        self.kw = _knockout_winners()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_1x2_brier_identical_with_or_without_knockout_winners(self):
        """knockout_winners only affects advancement, never 1X2."""
        _write_log(self.log_dir, _knockout_log_entries())
        result_with = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)
        result_without = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(
            result_with["metrics"]["brier"],
            result_without["metrics"]["brier"],
        )
        self.assertEqual(
            result_with["metrics"]["1x2_accuracy"],
            result_without["metrics"]["1x2_accuracy"],
        )

    def test_advancement_metrics_not_in_1x2_metrics(self):
        """1X2 metrics dict does not contain advancement keys."""
        _write_log(self.log_dir, _knockout_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups, knockout_winners=self.kw)

        for key in result["metrics"]:
            self.assertFalse(key.startswith("advancement_"))

        for stage_key in result["by_stage"]:
            for metric_key in result["by_stage"][stage_key]:
                self.assertFalse(metric_key.startswith("advancement_"))


if __name__ == "__main__":
    unittest.main()
