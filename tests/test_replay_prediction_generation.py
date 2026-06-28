"""Tests for scripts/generate_replay_predictions.py — replay prediction generation.

All tests use temporary fixture data. No real knowledge/ or logs/ files are touched.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from oracle_core.evaluation import evaluate
from oracle_core.tournament import check_round_robin_integrity
from oracle_core.types import GroupDefinition, ScheduledMatch, TournamentRules

from scripts.generate_replay_predictions import (
    _build_replay_log_entry,
    _build_team_snapshot,
    _build_tournament_context_payload,
    _enrich_prediction,
    generate_replay_predictions,
)
from oracle_core.engine import predict_match as predict_score


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _fixture_schedule() -> tuple[ScheduledMatch, ...]:
    """6 matches: Group A (3 teams, all 3 pairs, all completed → ok),
    Group B (3 teams, only 1 unique pair duplicated → warning),
    1 knockout match (unplayed).

    Group A — 3 teams, all 3 pairs scheduled, all completed:
      MD1: Alpha-Beta (2,1)  completed
      MD1: Alpha-Gamma (1,1) completed
      MD3: Beta-Gamma (1,0)  completed

    Group B — 3 teams, only 1 pair (X-Y) duplicated, missing X-Z and Y-Z:
      MD1: X-Y (0,0)  completed — overwritten by MD3 entry in match index
      MD3: X-Y (3,0)  completed — wins the match index

    No-group match:
      Final: Champ-Runner  None   unplayed
    """
    return (
        # Group A — valid round-robin (3 C 2 = 3 pairs, all present)
        ScheduledMatch("wc2026-grpA-aaa-bbb", "A", 1, "TeamAlpha", "TeamBeta",
                       "2026-06-20T00:00:00Z", "Venue", True, (2, 1)),
        ScheduledMatch("wc2026-grpA-aaa-ccc", "A", 1, "TeamAlpha", "TeamGamma",
                       "2026-06-20T01:00:00Z", "Venue", True, (1, 1)),
        ScheduledMatch("wc2026-grpA-bbb-ccc", "A", 3, "TeamBeta", "TeamGamma",
                       "2026-06-26T00:00:00Z", "Venue", True, (1, 0)),
        # Group B — duplicate pair for TeamX-TeamY, missing X-Z and Y-Z
        ScheduledMatch("wc2026-grpB-xxx-yyy-md1", "B", 1, "TeamX", "TeamY",
                       "2026-06-20T00:00:00Z", "Venue", True, (0, 0)),
        ScheduledMatch("wc2026-grpB-xxx-yyy-md3", "B", 3, "TeamX", "TeamY",
                       "2026-06-26T00:00:00Z", "Venue", True, (3, 0)),
        # No-group match (knockout) — unplayed
        ScheduledMatch("wc2026-final", "Final", 1, "TeamChamp", "TeamRunner",
                       "2026-07-19T00:00:00Z", "Venue", True, None),
    )


def _fixture_groups() -> dict[str, GroupDefinition]:
    return {
        "A": GroupDefinition("A", ("TeamAlpha", "TeamBeta", "TeamGamma")),
        "B": GroupDefinition("B", ("TeamX", "TeamY", "TeamZ")),
    }


def _fixture_rules() -> TournamentRules:
    return TournamentRules(
        tournament_name="Test Cup",
        group_stage_format="test",
        total_groups=2,
        teams_per_group=3,
        matchdays_per_group=3,
        top_n_per_group=2,
        best_third_place_count=0,
        total_advancing=4,
        group_tiebreakers=("points", "goal_difference"),
        best_third_place_criteria=("points",),
    )


def _fixture_teams() -> dict[str, dict]:
    """Some teams with real data, some missing (will use defaults)."""
    return {
        "TeamAlpha": {"elo": 1850.0, "attack": 75.0, "defense": 70.0},
        "TeamBeta": {"elo": 1700.0, "attack": 65.0, "defense": 68.0},
        # TeamGamma missing → defaults
        "TeamX": {"elo": 1800.0, "attack": 72.0, "defense": 71.0},
        "TeamY": {"elo": 1600.0, "attack": 62.0, "defense": 64.0},
        # TeamZ missing → defaults
    }


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------


class TeamSnapshotHelperTests(unittest.TestCase):
    """Verify _build_team_snapshot behaviour."""

    def test_known_team_uses_provided_data(self):
        teams = {"Mexico": {"elo": 1853.0, "attack": 75.0, "defense": 68.0}}
        snap = _build_team_snapshot("Mexico", teams)
        self.assertEqual(snap.name, "Mexico")
        self.assertAlmostEqual(snap.elo, 1853.0)
        self.assertAlmostEqual(snap.attack, 75.0)
        self.assertAlmostEqual(snap.defense, 68.0)
        self.assertAlmostEqual(snap.form, 0.0)
        self.assertAlmostEqual(snap.availability, 0.0)

    def test_unknown_team_uses_defaults(self):
        snap = _build_team_snapshot("UnknownFC", {})
        self.assertEqual(snap.name, "UnknownFC")
        self.assertAlmostEqual(snap.elo, 1500.0)
        self.assertAlmostEqual(snap.attack, 70.0)
        self.assertAlmostEqual(snap.defense, 70.0)

    def test_attack_rating_alias(self):
        """attack_rating is accepted as an alias for attack."""
        teams = {"TeamX": {"attack_rating": 80.0, "defense_rating": 60.0}}
        snap = _build_team_snapshot("TeamX", teams)
        self.assertAlmostEqual(snap.attack, 80.0)
        self.assertAlmostEqual(snap.defense, 60.0)


class TournamentContextHelperTests(unittest.TestCase):
    """Verify _build_tournament_context_payload structure."""

    def test_payload_includes_required_fields(self):
        """Context payload must have state_mode, incentives, excluded_matches."""
        from oracle_core.tournament import get_tournament_state

        schedule = _fixture_schedule()
        groups = _fixture_groups()
        rules = _fixture_rules()

        state = get_tournament_state(
            "wc2026-grpA-aaa-bbb", schedule, groups, rules,
            state_mode="pre_match",
        )
        tc = _build_tournament_context_payload(state)

        self.assertEqual(tc["state_mode"], "pre_match")
        self.assertIn("match_id", tc)
        self.assertIn("team_a_incentive", tc)
        self.assertIn("team_b_incentive", tc)
        self.assertIn("excluded_matches", tc)
        # data_quality is included when available
        self.assertIn("data_quality", tc)
        # Group A has all 3 pairs for its 3 teams → round-robin is complete
        self.assertEqual(tc["data_quality"]["status"], "ok")

    def test_payload_includes_data_quality_warning(self):
        """When a group has round-robin issues, data_quality=warning propagates."""
        from oracle_core.tournament import get_tournament_state

        schedule = _fixture_schedule()
        groups = _fixture_groups()
        rules = _fixture_rules()

        # Group B has duplicate pairs → warning
        state = get_tournament_state(
            "wc2026-grpB-xxx-yyy-md3", schedule, groups, rules,
            state_mode="pre_match",
        )
        tc = _build_tournament_context_payload(state)

        self.assertIn("data_quality", tc)
        self.assertEqual(tc["data_quality"]["status"], "warning")
        self.assertTrue(
            any("duplicate_pair" in i for i in tc["data_quality"]["issues"])
        )


class EnrichPredictionTests(unittest.TestCase):
    """Verify _enrich_prediction preserves probabilities and adds context."""

    def test_probabilities_unchanged_after_enrichment(self):
        snap_a = _build_team_snapshot("TeamA", {})
        snap_b = _build_team_snapshot("TeamB", {})
        pred = predict_score(snap_a, snap_b, neutral_site=True)

        tc = {"state_mode": "pre_match", "match_id": "test-1"}
        enriched = _enrich_prediction(pred, tc, {"status": "ok", "issues": []})

        # Probabilities must be identical
        self.assertEqual(
            dict(pred.result_probabilities),
            dict(enriched.result_probabilities),
        )
        self.assertEqual(pred.expected_goals, enriched.expected_goals)

    def test_tournament_context_set_after_enrichment(self):
        snap_a = _build_team_snapshot("TeamA", {})
        snap_b = _build_team_snapshot("TeamB", {})
        pred = predict_score(snap_a, snap_b, neutral_site=True)

        tc = {"state_mode": "pre_match", "match_id": "test-1"}
        enriched = _enrich_prediction(pred, tc, {"status": "ok", "issues": []})

        self.assertIsNotNone(enriched.tournament_context)
        self.assertEqual(enriched.tournament_context["state_mode"], "pre_match")

    def test_warning_data_quality_adds_limitation_note(self):
        snap_a = _build_team_snapshot("TeamA", {})
        snap_b = _build_team_snapshot("TeamB", {})
        pred = predict_score(snap_a, snap_b, neutral_site=True)

        tc = {"state_mode": "pre_match", "match_id": "test-1"}
        dq = {"status": "warning", "issues": ["duplicate_pair: X vs Y"]}
        enriched = _enrich_prediction(pred, tc, dq)

        self.assertTrue(
            any("Schedule integrity warning" in lim for lim in enriched.limitations),
            f"Expected integrity note in limitations: {enriched.limitations}",
        )

    def test_ok_data_quality_does_not_add_integrity_note(self):
        snap_a = _build_team_snapshot("TeamA", {})
        snap_b = _build_team_snapshot("TeamB", {})
        pred = predict_score(snap_a, snap_b, neutral_site=True)

        tc = {"state_mode": "pre_match", "match_id": "test-1"}
        dq = {"status": "ok", "issues": []}
        enriched = _enrich_prediction(pred, tc, dq)

        self.assertFalse(
            any("Schedule integrity warning" in lim for lim in enriched.limitations),
        )


class ReplayLogEntryTests(unittest.TestCase):
    """Verify _build_replay_log_entry structure."""

    def test_entry_includes_all_required_fields(self):
        snap_a = _build_team_snapshot("TeamA", {})
        snap_b = _build_team_snapshot("TeamB", {})
        pred = predict_score(snap_a, snap_b, neutral_site=True)

        match = ScheduledMatch(
            "wc2026-test", "A", 1, "TeamA", "TeamB",
            "2026-06-20T00:00:00Z", "Venue", True, (2, 1),
        )
        tc = {"state_mode": "pre_match", "match_id": "wc2026-test"}
        dq = {"status": "ok", "issues": []}

        entry = _build_replay_log_entry(pred, match, tc, dq)

        # Required fields per spec
        self.assertEqual(entry["match_id"], "wc2026-test")
        self.assertEqual(entry["team_a"], "TeamA")
        self.assertEqual(entry["team_b"], "TeamB")
        self.assertIn("predicted_at", entry)
        self.assertTrue(entry["replay_mode"])
        self.assertEqual(entry["state_mode"], "pre_match")
        self.assertTrue(entry["tournament_context_available"])
        # model_mode and engine_path
        self.assertEqual(entry["model_mode"], "provisional")
        self.assertEqual(entry["engine_path"], "oracle_core.engine.predict_score")
        # data_quality.status is included
        self.assertIn("data_quality", entry)
        self.assertEqual(entry["data_quality"]["status"], "ok")
        # Standard prediction fields
        self.assertIn("result_probabilities", entry)
        self.assertIn("expected_goals", entry)
        self.assertIn("over_under", entry)
        self.assertIn("top_scores", entry)
        self.assertIn("limitations", entry)
        self.assertEqual(entry["match_id_source"], "provided")

    def test_entry_model_mode_is_provisional(self):
        """Every replay entry explicitly declares model_mode='provisional'."""
        snap_a = _build_team_snapshot("TeamA", {})
        snap_b = _build_team_snapshot("TeamB", {})
        pred = predict_score(snap_a, snap_b, neutral_site=True)

        match = ScheduledMatch(
            "wc2026-test", "A", 1, "TeamA", "TeamB",
            "2026-06-20T00:00:00Z", "Venue", True, (2, 1),
        )
        tc = {"state_mode": "pre_match", "match_id": "wc2026-test"}
        dq = {"status": "ok", "issues": []}

        entry = _build_replay_log_entry(pred, match, tc, dq)
        self.assertEqual(entry["model_mode"], "provisional")

    def test_entry_engine_path_is_correct(self):
        """Every replay entry includes the engine_path."""
        snap_a = _build_team_snapshot("TeamA", {})
        snap_b = _build_team_snapshot("TeamB", {})
        pred = predict_score(snap_a, snap_b, neutral_site=True)

        match = ScheduledMatch(
            "wc2026-test", "A", 1, "TeamA", "TeamB",
            "2026-06-20T00:00:00Z", "Venue", True, (2, 1),
        )
        tc = {"state_mode": "pre_match", "match_id": "wc2026-test"}
        dq = {"status": "ok", "issues": []}

        entry = _build_replay_log_entry(pred, match, tc, dq)
        self.assertEqual(entry["engine_path"], "oracle_core.engine.predict_score")

    def test_entry_is_json_serializable(self):
        snap_a = _build_team_snapshot("TeamA", {})
        snap_b = _build_team_snapshot("TeamB", {})
        pred = predict_score(snap_a, snap_b, neutral_site=True)

        match = ScheduledMatch(
            "wc2026-test", "A", 1, "TeamA", "TeamB",
            "2026-06-20T00:00:00Z", "Venue", True, (2, 1),
        )
        tc = {"state_mode": "pre_match", "match_id": "wc2026-test"}
        dq = {"status": "ok", "issues": []}

        entry = _build_replay_log_entry(pred, match, tc, dq)
        # Must not raise
        json_str = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        roundtripped = json.loads(json_str)
        self.assertEqual(roundtripped["match_id"], "wc2026-test")
        self.assertTrue(roundtripped["replay_mode"])


# ---------------------------------------------------------------------------
# Integration tests: generate_replay_predictions()
# ---------------------------------------------------------------------------


class GenerateReplayIntegrationTests(unittest.TestCase):
    """End-to-end replay generation with fixture data."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tmpdir.name) / "replay"
        self.schedule = _fixture_schedule()
        self.groups = _fixture_groups()
        self.rules = _fixture_rules()
        self.teams = _fixture_teams()

    def tearDown(self):
        self.tmpdir.cleanup()

    # -- helpers --

    def _generate(self) -> dict:
        return generate_replay_predictions(
            self.schedule, self.groups, self.rules, self.teams,
            self.output_dir,
        )

    def _read_log_entries(self) -> list[dict]:
        entries: list[dict] = []
        for jf in sorted(self.output_dir.glob("predictions-*.jsonl")):
            for line in jf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    # -- 1. counts ------------------------------------------------------------

    def test_only_completed_matches_generated(self):
        """Only matches with score are predicted. Unplayed matches skipped."""
        result = self._generate()

        # Fixture has 5 completed matches: 3 in A + 2 in B
        # wc2026-grpA-aaa-bbb (2,1), wc2026-grpA-aaa-ccc (1,1),
        # wc2026-grpA-bbb-ccc (1,0),
        # wc2026-grpB-xxx-yyy-md1 (0,0), wc2026-grpB-xxx-yyy-md3 (3,0)
        self.assertEqual(result["total_completed_matches"], 5)
        self.assertEqual(result["generated"], 5)
        self.assertIsNone(result["skipped_predictions"])

    def test_no_predictions_for_unplayed_matches(self):
        """Unplayed matches (score=None) are not predicted."""
        result = self._generate()
        entries = self._read_log_entries()

        # None of the entries should correspond to unplayed matches
        match_ids = {e["match_id"] for e in entries}
        self.assertNotIn("wc2026-final", match_ids)  # unplayed

        # All 5 completed match_ids should be present
        for mid in [
            "wc2026-grpA-aaa-bbb", "wc2026-grpA-aaa-ccc",
            "wc2026-grpA-bbb-ccc",
            "wc2026-grpB-xxx-yyy-md1", "wc2026-grpB-xxx-yyy-md3",
        ]:
            self.assertIn(mid, match_ids, f"Missing match_id: {mid}")

    # -- 2. replay mode fields ------------------------------------------------

    def test_all_entries_have_replay_mode_true(self):
        self._generate()
        entries = self._read_log_entries()
        self.assertTrue(len(entries) > 0)
        for e in entries:
            self.assertTrue(e.get("replay_mode"), f"replay_mode missing for {e['match_id']}")

    def test_all_entries_have_state_mode_pre_match(self):
        self._generate()
        entries = self._read_log_entries()
        for e in entries:
            self.assertEqual(e.get("state_mode"), "pre_match",
                             f"state_mode wrong for {e['match_id']}")

    def test_all_entries_have_tournament_context_available_true(self):
        self._generate()
        entries = self._read_log_entries()
        for e in entries:
            self.assertTrue(e.get("tournament_context_available"),
                            f"tournament_context_available missing for {e['match_id']}")

    def test_all_entries_have_match_id_and_match_id_source(self):
        self._generate()
        entries = self._read_log_entries()
        for e in entries:
            self.assertTrue(e.get("match_id"), f"match_id empty for entry")
            self.assertEqual(e.get("match_id_source"), "provided")

    def test_all_entries_have_data_quality_status(self):
        self._generate()
        entries = self._read_log_entries()
        for e in entries:
            dq = e.get("data_quality")
            self.assertIsNotNone(dq, f"data_quality missing for {e['match_id']}")
            self.assertIn(dq.get("status"), ("ok", "warning"),
                          f"unexpected data_quality.status: {dq.get('status')}")

    # -- 3. data_quality breakdown in entries ---------------------------------

    def test_group_a_entries_have_ok_status(self):
        self._generate()
        entries = self._read_log_entries()
        a_entries = [e for e in entries if e["match_id"].startswith("wc2026-grpA")]
        self.assertTrue(len(a_entries) > 0)
        for e in a_entries:
            self.assertEqual(e["data_quality"]["status"], "ok")

    def test_group_b_entries_have_warning_status(self):
        self._generate()
        entries = self._read_log_entries()
        b_entries = [e for e in entries if e["match_id"].startswith("wc2026-grpB")]
        self.assertTrue(len(b_entries) > 0)
        for e in b_entries:
            self.assertEqual(e["data_quality"]["status"], "warning")

    # -- 4. output directory isolation ----------------------------------------

    def test_output_written_to_specified_dir_not_production(self):
        """Replay logs must go to the specified output_dir, not logs/predictions/."""
        self._generate()
        # Files should exist in our temp output_dir
        files = list(self.output_dir.glob("predictions-*.jsonl"))
        self.assertTrue(len(files) > 0, "No log files found in output_dir")

    # -- 5. valid JSONL -------------------------------------------------------

    def test_generated_logs_are_valid_jsonl(self):
        self._generate()
        for jf in self.output_dir.glob("predictions-*.jsonl"):
            for lineno, line in enumerate(
                jf.read_text(encoding="utf-8").splitlines(), start=1
            ):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    self.fail(f"Invalid JSON at {jf.name}:{lineno}: {exc}")
                self.assertIsInstance(entry, dict)

    # -- 6. evaluable by evaluate() -------------------------------------------

    def test_generated_logs_evaluable_by_evaluate(self):
        """The generated replay logs must be consumable by evaluate()."""
        self._generate()
        result = evaluate(self.output_dir, self.schedule, self.groups)

        self.assertGreater(result["total_predictions"], 0)
        self.assertGreater(result["settled_predictions"], 0,
                           "Replay logs should have settled predictions")
        self.assertIn("metrics", result)
        self.assertIn("by_data_quality", result)
        # Should have "all" and at least "ok" breakdown
        self.assertIn("all", result["by_data_quality"])
        self.assertIn("ok", result["by_data_quality"])
        # Group B provides the warning bucket
        self.assertIn("warning", result["by_data_quality"])

    def test_evaluation_has_correct_data_quality_breakdown(self):
        """OK and warning counts match expected group assignments."""
        self._generate()
        result = evaluate(self.output_dir, self.schedule, self.groups)

        by_dq = result["by_data_quality"]
        # 3 Group A + 2 Group B = 5 settled (all completed matches)
        # Group B has 2 entries for TeamX-TeamY; both match the same duplicated
        # schedule entry (the last one, (3,0), wins the match index).
        # Group A: TeamAlpha-TeamBeta, TeamAlpha-TeamGamma, TeamBeta-TeamGamma → 3 ok
        # Group B: 2 entries for TeamX-TeamY → 2 warning

        self.assertEqual(by_dq["all"]["count"], result["settled_predictions"])
        self.assertEqual(by_dq["ok"]["count"], 3)     # Group A
        self.assertEqual(by_dq["warning"]["count"], 2)  # Group B

    # -- 7. defaults for missing team data ------------------------------------

    def test_team_with_no_data_still_generates_prediction(self):
        """TeamGamma and TeamZ have no data; defaults should be used."""
        result = self._generate()
        # TeamGamma appears in Group A matches → defaults used, should succeed
        self.assertIsNone(result["skipped_predictions"])
        self.assertGreater(result["generated"], 0)

    # -- 8. skipped predictions on error --------------------------------------

    def test_skipped_prediction_recorded_for_same_team_match(self):
        """A completed match where team_a == team_b → predict_score raises → skipped."""
        schedule = _fixture_schedule()
        # Append a completed match with same team on both sides
        bad_match = ScheduledMatch(
            "wc2026-same-team", "A", 1, "TeamAlpha", "TeamAlpha",
            "2026-06-20T00:00:00Z", "Venue", True, (1, 1),
        )
        bad_schedule = schedule + (bad_match,)
        result = generate_replay_predictions(
            bad_schedule, self.groups, self.rules, self.teams, self.output_dir,
        )
        # The original 5 completed matches should still succeed
        self.assertEqual(result["total_completed_matches"], 6)
        self.assertEqual(result["generated"], 5)
        self.assertIsNotNone(result["skipped_predictions"])
        self.assertEqual(len(result["skipped_predictions"]), 1)
        self.assertEqual(
            result["skipped_predictions"][0]["match_id"], "wc2026-same-team"
        )

    # -- 9. probabilities remain deterministic ---------------------------------

    def test_probabilities_are_deterministic(self):
        """Same inputs → same probabilities (two runs produce identical values)."""
        self._generate()
        entries_1 = self._read_log_entries()

        # Remove output and regenerate
        import shutil
        shutil.rmtree(self.output_dir)
        self._generate()
        entries_2 = self._read_log_entries()

        self.assertEqual(len(entries_1), len(entries_2))
        for e1, e2 in zip(
            sorted(entries_1, key=lambda x: x["match_id"]),
            sorted(entries_2, key=lambda x: x["match_id"]),
        ):
            self.assertEqual(e1["match_id"], e2["match_id"])
            for key in ("result_probabilities", "expected_goals", "over_under"):
                self.assertEqual(
                    e1[key], e2[key],
                    f"{key} differs for {e1['match_id']} between runs",
                )


# ---------------------------------------------------------------------------
# Skipped predictions from the generate function (error handling)
# ---------------------------------------------------------------------------


class SkippedPredictionsTests(unittest.TestCase):
    """Edge cases that trigger skipped_predictions."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tmpdir.name) / "replay"
        self.groups = _fixture_groups()
        self.rules = _fixture_rules()
        self.teams = _fixture_teams()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_all_matches_completed_none_skipped_with_valid_data(self):
        """Happy path: all completed matches generate successfully."""
        schedule = (
            ScheduledMatch("wc2026-grpA-aaa-bbb", "A", 1, "TeamAlpha", "TeamBeta",
                           "2026-06-20T00:00:00Z", "Venue", True, (2, 1)),
        )
        result = generate_replay_predictions(
            schedule, self.groups, self.rules, self.teams, self.output_dir,
        )
        self.assertEqual(result["generated"], 1)
        self.assertIsNone(result["skipped_predictions"])

    def test_same_team_match_triggers_skip(self):
        """predict_score raises when team_a == team_b → skip recorded."""
        schedule = (
            ScheduledMatch("wc2026-same", "A", 1, "TeamX", "TeamX",
                           "2026-06-20T00:00:00Z", "Venue", True, (1, 1)),
        )
        result = generate_replay_predictions(
            schedule, self.groups, self.rules, self.teams, self.output_dir,
        )
        self.assertEqual(result["generated"], 0)
        self.assertIsNotNone(result["skipped_predictions"])
        self.assertEqual(len(result["skipped_predictions"]), 1)
        self.assertEqual(
            result["skipped_predictions"][0]["match_id"], "wc2026-same"
        )
        # The error is "ValueError: teams must differ"
        self.assertIn("ValueError", result["skipped_predictions"][0]["reason"])

    def test_skipped_and_generated_coexist(self):
        """Some matches succeed, some fail — both reported."""
        schedule = (
            # Valid
            ScheduledMatch("wc2026-grpA-aaa-bbb", "A", 1, "TeamAlpha", "TeamBeta",
                           "2026-06-20T00:00:00Z", "Venue", True, (2, 1)),
            # Invalid — same team on both sides
            ScheduledMatch("wc2026-same", "A", 1, "TeamX", "TeamX",
                           "2026-06-20T00:00:00Z", "Venue", True, (1, 1)),
        )
        result = generate_replay_predictions(
            schedule, self.groups, self.rules, self.teams, self.output_dir,
        )
        self.assertEqual(result["total_completed_matches"], 2)
        self.assertEqual(result["generated"], 1)
        self.assertIsNotNone(result["skipped_predictions"])
        self.assertEqual(len(result["skipped_predictions"]), 1)


if __name__ == "__main__":
    unittest.main()
