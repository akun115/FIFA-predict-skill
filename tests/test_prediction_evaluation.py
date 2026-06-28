"""Tests for oracle_core/evaluation.py — replay evaluation against fixture data.

All tests use temporary fixture data. No real knowledge/ or logs/ files are touched.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
import unittest

from oracle_core.evaluation import (
    MetricBundle,
    _actual_1x2,
    _compute_brier,
    _compute_log_loss,
    _compute_rps,
    _expected_goal_mae,
    _over_under_hit,
    _score_hit,
    evaluate,
)
from oracle_core.tournament import check_round_robin_integrity
from oracle_core.types import GroupDefinition, ScheduledMatch


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _fixture_schedule() -> tuple[ScheduledMatch, ...]:
    """5 matches: 2 completed (Group A), 1 unplayed (A), 2 with duplicate pair (Group B).

    Important: the match index maps (team_a, team_b) → LAST matching entry.
    Group B has two (TeamX, TeamY) entries — the second (score 3-0) wins.
    The duplicate pairing is intentional: it triggers data_quality=warning.
    """
    return (
        # Group A — valid round-robin (all 3 pairs present, 2 completed + 1 unplayed)
        ScheduledMatch("wc2026-grpA-aaa-bbb", "A", 1, "TeamAlpha", "TeamBeta",
                       "2026-06-20T00:00:00Z", "Venue", True, (2, 1)),
        ScheduledMatch("wc2026-grpA-aaa-ccc", "A", 2, "TeamAlpha", "TeamGamma",
                       "2026-06-23T00:00:00Z", "Venue", True, (1, 1)),
        ScheduledMatch("wc2026-grpA-bbb-ccc", "A", 3, "TeamBeta", "TeamGamma",
                       "2026-06-26T00:00:00Z", "Venue", True, None),  # unplayed
        # Group B — duplicate pair (TeamX, TeamY) triggers warning status.
        # The LAST entry with the same key wins in the match index.
        ScheduledMatch("wc2026-grpB-xxx-yyy-md1", "B", 1, "TeamX", "TeamY",
                       "2026-06-20T00:00:00Z", "Venue", True, (0, 0)),  # overwritten
        ScheduledMatch("wc2026-grpB-xxx-yyy-md3", "B", 3, "TeamX", "TeamY",
                       "2026-06-26T00:00:00Z", "Venue", True, (3, 0)),  # wins index
    )


def _fixture_groups() -> dict[str, GroupDefinition]:
    """Group A: 3 teams, all pairings scheduled → data_quality="ok".
    Group B: 4 teams, only 1 pair scheduled (twice!) → data_quality="warning"."""
    return {
        "A": GroupDefinition("A", ("TeamAlpha", "TeamBeta", "TeamGamma")),
        "B": GroupDefinition("B", ("TeamX", "TeamY", "TeamZ", "TeamW")),
    }


def _fixture_log_entries() -> list[dict]:
    """4 log entries:
    1. TeamAlpha vs TeamBeta — matches Group A completed (score 2-1)
    2. TeamX vs TeamY — matches Group B completed (score 3-0, warning group)
    3. TeamAlpha vs TeamGamma — matches Group A completed (score 1-1)
    4. UnknownA vs UnknownB — no match in schedule → unsettled
    """
    return [
        {
            "prediction_id": "pred-001",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "",
            "match_id_source": "missing",
            "team_a": "TeamAlpha",
            "team_b": "TeamBeta",
            "model_name": "test",
            "model_version": "test-v1",
            "model_artifact_hash": "h1",
            "input_context_hash": "h2",
            "category": "world_cup",
            "neutral_site": True,
            "expected_goals": [1.8, 0.9],
            "result_probabilities": {
                "team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20,
            },
            "over_under": {
                "over_0_5": 0.90, "under_0_5": 0.10,
                "over_1_5": 0.70, "under_1_5": 0.30,
                "over_2_5": 0.50, "under_2_5": 0.50,
                "over_3_5": 0.30, "under_3_5": 0.70,
                "over_4_5": 0.10, "under_4_5": 0.90,
            },
            "top_scores": [
                {"score": [1, 1], "probability": 0.14},
                {"score": [2, 1], "probability": 0.12},
                {"score": [2, 0], "probability": 0.10},
                {"score": [1, 0], "probability": 0.09},
                {"score": [3, 1], "probability": 0.07},
            ],
            "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [],
            "source_snapshot_refs": {},
        },
        {
            "prediction_id": "pred-002",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "",
            "match_id_source": "missing",
            "team_a": "TeamX",
            "team_b": "TeamY",
            "model_name": "test",
            "model_version": "test-v1",
            "model_artifact_hash": "h1",
            "input_context_hash": "h2",
            "category": "world_cup",
            "neutral_site": True,
            "expected_goals": [2.5, 0.5],
            "result_probabilities": {
                "team_a_win": 0.70, "draw": 0.20, "team_b_win": 0.10,
            },
            "over_under": {
                "over_0_5": 0.95, "under_0_5": 0.05,
                "over_1_5": 0.75, "under_1_5": 0.25,
                "over_2_5": 0.55, "under_2_5": 0.45,
                "over_3_5": 0.30, "under_3_5": 0.70,
                "over_4_5": 0.10, "under_4_5": 0.90,
            },
            "top_scores": [
                {"score": [2, 0], "probability": 0.12},
                {"score": [3, 0], "probability": 0.10},
                {"score": [1, 0], "probability": 0.09},
                {"score": [2, 1], "probability": 0.08},
                {"score": [3, 1], "probability": 0.06},
            ],
            "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [],
            "source_snapshot_refs": {},
        },
        {
            "prediction_id": "pred-003",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "",
            "match_id_source": "missing",
            "team_a": "TeamAlpha",
            "team_b": "TeamGamma",
            "model_name": "test",
            "model_version": "test-v1",
            "model_artifact_hash": "h1",
            "input_context_hash": "h2",
            "category": "world_cup",
            "neutral_site": True,
            "expected_goals": [1.2, 1.1],
            "result_probabilities": {
                "team_a_win": 0.30, "draw": 0.40, "team_b_win": 0.30,
            },
            "over_under": {
                "over_0_5": 0.85, "under_0_5": 0.15,
                "over_1_5": 0.60, "under_1_5": 0.40,
                "over_2_5": 0.35, "under_2_5": 0.65,
                "over_3_5": 0.15, "under_3_5": 0.85,
                "over_4_5": 0.05, "under_4_5": 0.95,
            },
            "top_scores": [
                {"score": [1, 1], "probability": 0.20},
                {"score": [0, 1], "probability": 0.12},
                {"score": [1, 0], "probability": 0.11},
                {"score": [2, 1], "probability": 0.08},
                {"score": [0, 0], "probability": 0.07},
            ],
            "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [],
            "source_snapshot_refs": {},
        },
        {
            "prediction_id": "pred-004",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "",
            "match_id_source": "missing",
            "team_a": "UnknownA",
            "team_b": "UnknownB",
            "model_name": "test",
            "model_version": "test-v1",
            "model_artifact_hash": "h1",
            "input_context_hash": "h2",
            "category": "world_cup",
            "neutral_site": True,
            "expected_goals": [1.0, 1.0],
            "result_probabilities": {
                "team_a_win": 0.33, "draw": 0.34, "team_b_win": 0.33,
            },
            "over_under": {},
            "top_scores": [],
            "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [],
            "source_snapshot_refs": {},
        },
    ]


def _write_log_file(log_dir: Path, entries: list[dict]) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "predictions-2026-06-20.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Unit tests: metric helpers
# ---------------------------------------------------------------------------


class MetricHelperTests(unittest.TestCase):
    """Verify low-level metric computations."""

    def test_actual_1x2_correctly_classifies(self):
        self.assertEqual(_actual_1x2((2, 1)), "team_a_win")
        self.assertEqual(_actual_1x2((0, 0)), "draw")
        self.assertEqual(_actual_1x2((0, 3)), "team_b_win")

    def test_brier_perfect_prediction_is_zero(self):
        probs = {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0}
        self.assertAlmostEqual(_compute_brier(probs, "team_a_win"), 0.0, places=10)

    def test_brier_worst_prediction_is_two_thirds(self):
        probs = {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0}
        result = _compute_brier(probs, "team_b_win")
        expected = ((1.0 - 0.0)**2 + (0.0 - 0.0)**2 + (0.0 - 1.0)**2) / 3.0
        self.assertAlmostEqual(result, expected, places=10)
        self.assertAlmostEqual(result, 2.0 / 3.0, places=10)

    def test_log_loss_perfect_approaches_zero(self):
        probs = {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0}
        self.assertAlmostEqual(_compute_log_loss(probs, "team_a_win"), 0.0, places=10)

    def test_log_loss_worst_is_large(self):
        probs = {"team_a_win": 1e-15, "draw": 0.5, "team_b_win": 0.5}
        result = _compute_log_loss(probs, "team_a_win")
        self.assertGreater(result, 30)

    def test_rps_perfect_is_zero(self):
        probs = {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0}
        self.assertAlmostEqual(_compute_rps(probs, "team_a_win"), 0.0, places=10)

    def test_rps_decomposes_correctly_team_b_win(self):
        probs = {"team_a_win": 0.1, "draw": 0.3, "team_b_win": 0.6}
        # Order: team_b_win, draw, team_a_win
        # Cum1: p(tbw)=0.6, o(tbw)=1 → (0.6-1)² = 0.16
        # Cum2: p(tbw+draw)=0.9, o(tbw+draw)=1 → (0.9-1)² = 0.01
        # RPS = (0.16 + 0.01) / 2 = 0.085
        expected = (0.16 + 0.01) / 2.0
        self.assertAlmostEqual(_compute_rps(probs, "team_b_win"), expected, places=10)

    def test_score_hit_exact_match(self):
        top_scores = [
            {"score": [2, 1], "probability": 0.15},
            {"score": [1, 0], "probability": 0.12},
            {"score": [3, 1], "probability": 0.10},
        ]
        self.assertTrue(_score_hit((2, 1), top_scores, 1))   # exact
        self.assertTrue(_score_hit((2, 1), top_scores, 3))   # top-3
        self.assertFalse(_score_hit((3, 1), top_scores, 1))  # not exact
        self.assertTrue(_score_hit((3, 1), top_scores, 3))   # top-3

    def test_over_under_hit_correct(self):
        ou = {"over_2_5": 0.7, "under_2_5": 0.3}
        # total=4 > 2.5, over_2_5 >= 0.5 → correct
        self.assertTrue(_over_under_hit(ou, 4, 2.5))
        # total=1 < 2.5, over_2_5 >= 0.5 → incorrect (predicted over, actual under)
        self.assertFalse(_over_under_hit(ou, 1, 2.5))

    def test_expected_goal_mae(self):
        mae = _expected_goal_mae((1.8, 0.9), (2, 1))
        self.assertAlmostEqual(mae, (abs(1.8 - 2) + abs(0.9 - 1)) / 2.0, places=10)

    def test_expected_goal_mae_perfect_is_zero(self):
        self.assertAlmostEqual(
            _expected_goal_mae((2.0, 1.0), (2, 1)), 0.0, places=10,
        )


# ---------------------------------------------------------------------------
# Integration tests: evaluate()
# ---------------------------------------------------------------------------


class EvaluateIntegrationTests(unittest.TestCase):
    """Full evaluate() pipeline with fixture data."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmpdir.name)
        self.schedule = _fixture_schedule()
        self.groups = _fixture_groups()

    def tearDown(self):
        self.tmpdir.cleanup()

    # -- 1. settled / unsettled counts ---------------------------------------

    def test_settled_and_unsettled_counts(self):
        _write_log_file(self.log_dir, _fixture_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(result["total_predictions"], 4)
        self.assertEqual(result["settled_predictions"], 3)
        self.assertEqual(result["unsettled_predictions"], 1)

    # -- 2. 1X2 directional accuracy -----------------------------------------

    def test_directional_accuracy(self):
        entries = _fixture_log_entries()[:3]  # only the 3 settled entries
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        metrics = result["metrics"]
        self.assertEqual(metrics["count"], 3)

        # pred-001: TeamAlpha(55%) vs Beta(20%) draw(25%), actual Alpha win → highest=team_a_win ✓
        # pred-002: TeamX(70%) vs Y(10%) draw(20%), actual X win → highest=team_a_win ✓
        # pred-003: TeamAlpha(30%) vs Gamma(30%) draw(40%), actual draw → highest=draw ✓
        # All 3 directional correct
        self.assertAlmostEqual(metrics["1x2_accuracy"], 1.0, places=10)

    # -- 3. Brier / log-loss / RPS -------------------------------------------

    def test_brier_log_loss_rps_values(self):
        """Verify metric values for known prediction-actual pairs."""
        entries = _fixture_log_entries()[:1]  # only pred-001
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        metrics = result["metrics"]
        self.assertEqual(metrics["count"], 1)

        # pred-001: probs {0.55, 0.25, 0.20}, actual team_a_win
        probs = {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}
        actual = "team_a_win"
        expected_brier = _compute_brier(probs, actual)
        expected_log_loss = _compute_log_loss(probs, actual)
        expected_rps = _compute_rps(probs, actual)

        self.assertAlmostEqual(metrics["brier"], expected_brier, places=10)
        self.assertAlmostEqual(metrics["log_loss"], expected_log_loss, places=10)
        self.assertAlmostEqual(metrics["rps"], expected_rps, places=10)

    # -- 4. exact / top-3 / top-5 score hit ----------------------------------

    def test_score_hit_rates(self):
        _write_log_file(self.log_dir, _fixture_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups)

        metrics = result["metrics"]
        self.assertEqual(metrics["count"], 3)

        # pred-001: actual (2,1), top_scores has [2,1] at position 2 → top-3 ✓
        # pred-002: actual (3,0), top_scores has [3,0] at position 2 → top-3 ✓
        # pred-003: actual (1,1), top_scores has [1,1] at position 1 → exact ✓
        self.assertAlmostEqual(metrics["exact_score_hit_rate"], 1.0 / 3.0, places=10)
        self.assertAlmostEqual(metrics["top3_score_hit_rate"], 1.0, places=10)
        self.assertAlmostEqual(metrics["top5_score_hit_rate"], 1.0, places=10)

    # -- 5. over_2_5 / under_2_5 accuracy ------------------------------------

    def test_over_under_accuracy(self):
        _write_log_file(self.log_dir, _fixture_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups)

        metrics = result["metrics"]
        # pred-001: actual 2+1=3 > 2.5, over_2_5=0.50 → tie, but >=0.5 → "over" → correct
        # pred-002: actual 3+0=3 > 2.5, over_2_5=0.55 → >=0.5 → correct
        # pred-003: actual 1+1=2 < 2.5, over_2_5=0.35 → <0.5 → "under" → correct
        # pred-001: over=0.50/total=3 → over correct (>=0.5), under=0.50
        #   fails because 0.50>=0.5 predicts "under" but actual is "over"
        # pred-002: over=0.55/total=3 → both correct
        # pred-003: over=0.35/total=2 → both correct
        # over_2_5: 3/3, under_2_5: 2/3
        self.assertEqual(metrics["over_2_5_accuracy"], 1.0)
        self.assertAlmostEqual(metrics["under_2_5_accuracy"], 2.0 / 3.0, places=10)

    # -- 6. data_quality=warning grouping ------------------------------------

    def test_data_quality_breakdown(self):
        _write_log_file(self.log_dir, _fixture_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups)

        by_dq = result["by_data_quality"]

        # "all" has all 3 settled
        self.assertEqual(by_dq["all"]["count"], 3)

        # "ok" has Group A matches: pred-001 (Alpha-Beta) + pred-003 (Alpha-Gamma) = 2
        self.assertEqual(by_dq["ok"]["count"], 2)

        # "warning" has Group B matches: pred-002 (X-Y) = 1
        self.assertEqual(by_dq["warning"]["count"], 1)

        # "no_match" has the unsettled entry — but it's not in any settled bundle
        # because only settled predictions go into bundles. Verify total counts:
        self.assertEqual(
            by_dq["ok"]["count"] + by_dq["warning"]["count"],
            by_dq["all"]["count"],
        )

    def test_data_quality_warning_group_has_correct_status(self):
        """Verify that Group B's check_round_robin_integrity returns 'warning'."""
        schedule = _fixture_schedule()
        groups = _fixture_groups()
        dq = check_round_robin_integrity(schedule, "B", groups["B"].teams)
        self.assertEqual(dq["status"], "warning")
        self.assertTrue(any("duplicate_pair" in i for i in dq["issues"]))

    def test_data_quality_ok_group_has_correct_status(self):
        schedule = _fixture_schedule()
        groups = _fixture_groups()
        dq = check_round_robin_integrity(schedule, "A", groups["A"].teams)
        # Group A has only 3 teams and 2 active pairings — no duplicates
        # among the 2 completed + 1 unplayed. But it's missing some expected pairs.
        # Let's check: expected pairs = 3 choose 2 = 3, actual pairs = 2
        # So status should be "warning" due to missing_pair
        # Actually, with only 3 scheduled matches (2 completed, 1 unplayed)
        # and 3 teams with 3 expected pairings:
        # Scheduled pairs: (Alpha,Beta), (Alpha,Gamma), (Beta,Gamma)
        # That's all 3! So status should be "ok"
        self.assertEqual(dq["status"], "ok")

    # -- 7. unplayed matches stay unsettled ----------------------------------

    def test_unplayed_match_not_settled(self):
        """A prediction matched to an unplayed (score=null) match must be unsettled."""
        entries = [
            {
                "prediction_id": "pred-unplayed",
                "predicted_at": "2026-06-20T00:00:00Z",
                "match_id": "",
                "match_id_source": "missing",
                "team_a": "TeamBeta",
                "team_b": "TeamGamma",
                "model_name": "test",
                "model_version": "test-v1",
                "model_artifact_hash": "h1",
                "input_context_hash": "h2",
                "category": "world_cup",
                "neutral_site": True,
                "expected_goals": [1.0, 1.0],
                "result_probabilities": {
                    "team_a_win": 0.33, "draw": 0.34, "team_b_win": 0.33,
                },
                "over_under": {},
                "top_scores": [],
                "score_matrix_hash": "h3",
                "tournament_context_available": False,
                "limitations": [],
                "source_snapshot_refs": {},
            },
        ]
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(result["total_predictions"], 1)
        self.assertEqual(result["settled_predictions"], 0)
        self.assertEqual(result["unsettled_predictions"], 1)

    # -- 8. malformed log line skipped, not crashed --------------------------

    def test_malformed_line_skipped(self):
        _write_log_file(self.log_dir, _fixture_log_entries())
        # Append a malformed line
        log_file = self.log_dir / "predictions-2026-06-20.jsonl"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write("this is not valid json\n")
            fh.write('{"half": "broken"\n')  # unclosed brace

        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(result["total_predictions"], 4)  # original 4
        self.assertEqual(result["malformed_lines_skipped"], 2)
        self.assertIsNotNone(result["warnings"])
        self.assertEqual(len(result["warnings"]), 2)
        self.assertTrue(
            any("malformed JSON" in w for w in result["warnings"])
        )

    # -- 9. empty log directory returns zero counts --------------------------

    def test_empty_log_directory(self):
        _write_log_file(self.log_dir, [])
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(result["total_predictions"], 0)
        self.assertEqual(result["settled_predictions"], 0)
        self.assertEqual(result["unsettled_predictions"], 0)
        self.assertEqual(result["metrics"]["count"], 0)
        self.assertIsNone(result["metrics"]["1x2_accuracy"])

    # -- 10. match_id priority over team pair ----------------------------------

    def test_match_id_priority_wins_over_different_team_pair(self):
        """match_id matches schedule entry A; team pair matches schedule entry B.
        match_id MUST win."""
        # Entry: match_id=Alpha-Beta, but team names suggest Alpha-Gamma
        # Alpha-Beta has score (2,1), Alpha-Gamma has score (1,1)
        entries = [{
            "prediction_id": "pred-matchid-test",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "wc2026-grpA-aaa-bbb",   # → Alpha vs Beta
            "match_id_source": "provided",
            "team_a": "TeamAlpha",
            "team_b": "TeamGamma",                # ← points to different match
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "model_mode": "provisional",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [2.0, 1.0],
            "result_probabilities": {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0},
            "over_under": {}, "top_scores": [],
            "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
        }]
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(result["total_predictions"], 1)
        self.assertEqual(result["settled_predictions"], 1)
        # Must match via match_id, not team pair
        self.assertEqual(result["matching_stats"]["matched_by_match_id"], 1)
        self.assertEqual(result["matching_stats"]["matched_by_team_pair"], 0)

        # Verify the match used the correct score: Alpha-Beta = (2,1), not Alpha-Gamma = (1,1)
        # With perfect team_a_win prediction and actual (2,1):
        metrics = result["metrics"]
        self.assertAlmostEqual(metrics["brier"], 0.0, places=10)

    def test_match_id_not_found_falls_back_to_team_pair(self):
        """When match_id is empty, team pair fallback is used."""
        entries = _fixture_log_entries()[:1]  # pred-001: TeamAlpha vs TeamBeta
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(result["settled_predictions"], 1)
        # Fixture log entries have match_id="" → must use team pair
        self.assertEqual(result["matching_stats"]["matched_by_match_id"], 0)
        self.assertEqual(result["matching_stats"]["matched_by_team_pair"], 1)

    def test_reversed_team_pair_fallback_still_works(self):
        """Team pair (B, A) matches schedule entry for (A, B)."""
        entries = [{
            "prediction_id": "pred-reversed",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "",
            "match_id_source": "missing",
            "team_a": "TeamBeta",       # ← reversed from schedule
            "team_b": "TeamAlpha",      # ← reversed from schedule
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "model_mode": "provisional",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [0.9, 1.8],
            "result_probabilities": {"team_a_win": 0.2, "draw": 0.25, "team_b_win": 0.55},
            "over_under": {}, "top_scores": [],
            "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
        }]
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(result["settled_predictions"], 1)
        self.assertEqual(result["matching_stats"]["matched_by_team_pair"], 1)

    def test_match_id_not_found_and_team_pair_fails_results_unsettled(self):
        """Neither match_id nor team pair matches → unsettled."""
        entries = [{
            "prediction_id": "pred-unsettled-both",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "wc2026-nonexistent",   # not in schedule
            "match_id_source": "provided",
            "team_a": "UnknownX",
            "team_b": "UnknownY",
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "model_mode": "provisional",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [1.0, 1.0],
            "result_probabilities": {"team_a_win": 0.33, "draw": 0.34, "team_b_win": 0.33},
            "over_under": {}, "top_scores": [],
            "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
        }]
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(result["total_predictions"], 1)
        self.assertEqual(result["settled_predictions"], 0)
        self.assertEqual(result["unsettled_predictions"], 1)
        self.assertEqual(result["matching_stats"]["unmatched"], 1)

    def test_match_id_exists_with_correct_team_names_uses_match_id(self):
        """match_id AND team pair both point to the same match → match_id counter wins."""
        entries = [{
            "prediction_id": "pred-both-ok",
            "predicted_at": "2026-06-20T00:00:00Z",
            "match_id": "wc2026-grpA-aaa-bbb",
            "match_id_source": "provided",
            "team_a": "TeamAlpha",
            "team_b": "TeamBeta",
            "model_name": "test", "model_version": "test-v1",
            "model_artifact_hash": "h1", "input_context_hash": "h2",
            "model_mode": "provisional",
            "category": "world_cup", "neutral_site": True,
            "expected_goals": [2.0, 1.0],
            "result_probabilities": {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0},
            "over_under": {}, "top_scores": [],
            "score_matrix_hash": "h3",
            "tournament_context_available": False,
            "limitations": [], "source_snapshot_refs": {},
        }]
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertEqual(result["settled_predictions"], 1)
        self.assertEqual(result["matching_stats"]["matched_by_match_id"], 1)
        self.assertEqual(result["matching_stats"]["matched_by_team_pair"], 0)

    # -- 11. model_mode breakdown ----------------------------------------------

    def test_model_mode_breakdown_groups_by_mode(self):
        """Entries with model_mode='provisional' appear in by_model_mode breakdown."""
        entries = _fixture_log_entries()[:3]  # all have empty match_id
        # Add model_mode to each
        for e in entries:
            e["match_id"] = ""  # ensure team pair matching
            e["model_mode"] = "provisional"
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertIn("by_model_mode", result)
        by_model = result["by_model_mode"]
        self.assertIn("all", by_model)
        self.assertIn("provisional", by_model)
        self.assertEqual(by_model["all"]["count"], 3)
        self.assertEqual(by_model["provisional"]["count"], 3)
        # "fitted" and "unknown" should be present but empty or null counts
        self.assertIn("fitted", by_model)

    def test_missing_model_mode_defaults_to_unknown(self):
        """Old logs without model_mode → counted as 'unknown'."""
        entries = _fixture_log_entries()[:1]  # no model_mode field
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        by_model = result["by_model_mode"]
        self.assertIn("unknown", by_model)
        self.assertEqual(by_model["unknown"]["count"], 1)
        # "provisional" should be present but empty
        self.assertIn("provisional", by_model)
        self.assertEqual(by_model["provisional"]["count"], 0)

    def test_mixed_model_modes_break_down_correctly(self):
        """provisional + fitted (when present) + unknown each get their own bundle."""
        entries = [
            {  # model_mode omitted → unknown
                "prediction_id": "pred-unknown",
                "predicted_at": "2026-06-20T00:00:00Z",
                "match_id": "",
                "match_id_source": "missing",
                "team_a": "TeamAlpha", "team_b": "TeamBeta",
                "model_name": "test", "model_version": "test-v1",
                "model_artifact_hash": "h1", "input_context_hash": "h2",
                "category": "world_cup", "neutral_site": True,
                "expected_goals": [1.8, 0.9],
                "result_probabilities": {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20},
                "over_under": {}, "top_scores": [],
                "score_matrix_hash": "h3",
                "tournament_context_available": False,
                "limitations": [], "source_snapshot_refs": {},
            },
            {  # explicit provisional
                "prediction_id": "pred-prov",
                "predicted_at": "2026-06-20T00:00:00Z",
                "match_id": "",
                "match_id_source": "missing",
                "team_a": "TeamX", "team_b": "TeamY",
                "model_name": "test", "model_version": "test-v1",
                "model_artifact_hash": "h1", "input_context_hash": "h2",
                "model_mode": "provisional",
                "category": "world_cup", "neutral_site": True,
                "expected_goals": [2.5, 0.5],
                "result_probabilities": {"team_a_win": 0.70, "draw": 0.20, "team_b_win": 0.10},
                "over_under": {}, "top_scores": [],
                "score_matrix_hash": "h3",
                "tournament_context_available": False,
                "limitations": [], "source_snapshot_refs": {},
            },
        ]
        _write_log_file(self.log_dir, entries)
        result = evaluate(self.log_dir, self.schedule, self.groups)

        by_model = result["by_model_mode"]
        self.assertEqual(by_model["all"]["count"], 2)
        self.assertEqual(by_model["provisional"]["count"], 1)
        self.assertEqual(by_model["unknown"]["count"], 1)

    # -- 12. matching_stats in output -----------------------------------------

    def test_matching_stats_present_in_output(self):
        """matching_stats key is always present in evaluate() output."""
        _write_log_file(self.log_dir, _fixture_log_entries())
        result = evaluate(self.log_dir, self.schedule, self.groups)

        self.assertIn("matching_stats", result)
        stats = result["matching_stats"]
        self.assertIn("matched_by_match_id", stats)
        self.assertIn("matched_by_team_pair", stats)
        self.assertIn("unmatched", stats)
        # Sum of settled + unmatched should equal (not directly, but verify consistency)
        self.assertEqual(
            stats["matched_by_match_id"] + stats["matched_by_team_pair"],
            result["settled_predictions"],
        )
        self.assertEqual(stats["unmatched"], result["unsettled_predictions"])

    # -- 13. missing log directory raises ------------------------------------

    def test_missing_log_directory_raises(self):
        with self.assertRaises(FileNotFoundError):
            evaluate(Path("/nonexistent/path/12345"), self.schedule, self.groups)


# ---------------------------------------------------------------------------
# MetricBundle unit tests
# ---------------------------------------------------------------------------


class MetricBundleTests(unittest.TestCase):
    def test_empty_bundle_returns_null_metrics(self):
        b = MetricBundle()
        d = b.to_dict()
        self.assertEqual(d["count"], 0)
        self.assertIsNone(d["1x2_accuracy"])
        self.assertIsNone(d["brier"])
        self.assertIsNone(d["rps"])

    def test_single_entry_bundle_correct_rates(self):
        b = MetricBundle()
        # Perfect prediction: 100% on actual outcome
        probs = {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0}
        b.add_settled(
            probs, "team_a_win",
            (2.0, 0.0), (2, 0),
            [{"score": [2, 0], "probability": 0.3}],
            {"over_2_5": 0.6, "under_2_5": 0.4},
        )
        d = b.to_dict()
        self.assertEqual(d["count"], 1)
        self.assertAlmostEqual(d["1x2_accuracy"], 1.0)
        self.assertAlmostEqual(d["brier"], 0.0)
        self.assertAlmostEqual(d["exact_score_hit_rate"], 1.0)
        self.assertAlmostEqual(d["expected_goal_mae"], 0.0)


if __name__ == "__main__":
    unittest.main()
