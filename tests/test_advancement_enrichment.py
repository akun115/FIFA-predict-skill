"""Tests for advancement_probabilities enrichment — Patch 11.

Coverage: enrichment logic, log integration, invariant preservation.
No modification to predict_score math or odds.
"""

from __future__ import annotations

import dataclasses
import json
import math
import tempfile
import unittest
from pathlib import Path

from dataclasses import replace

from oracle_core.engine import predict_match as predict_score
from oracle_core.logging import PredictionLogEntry, PredictionLogger
from oracle_core.types import ModelConfig, Prediction, TeamSnapshot

# Import the enrichment helper directly from the MCP server
import importlib.util
_server_path = Path(__file__).resolve().parent.parent / "mcp-server" / "server.py"
spec = importlib.util.spec_from_file_location("mcp_server_for_test", _server_path)
_server_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_server_mod)

_enrich_advancement = _server_mod._enrich_advancement
_ADVANCEMENT_DERIVED_NOTE = _server_mod._ADVANCEMENT_DERIVED_NOTE
_ADVANCEMENT_DEFAULTS_NOTE = _server_mod._ADVANCEMENT_DEFAULTS_NOTE
_ADVANCEMENT_PROVIDED_NOTE = _server_mod._ADVANCEMENT_PROVIDED_NOTE
_ADVANCEMENT_WARNING_NOTE = _server_mod._ADVANCEMENT_WARNING_NOTE
_ADVANCEMENT_NO_TEAMS_NOTE = _server_mod._ADVANCEMENT_NO_TEAMS_NOTE
_MIXED_CONTEXT_NOTE = _server_mod._MIXED_CONTEXT_NOTE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_prediction() -> Prediction:
    """Return a minimal Prediction with plausible regulation probabilities."""
    team_a = TeamSnapshot("TeamAlpha", elo=1500, attack=70, defense=70)
    team_b = TeamSnapshot("TeamBeta", elo=1500, attack=70, defense=70)
    return predict_score(team_a, team_b, neutral_site=True)


def _ok_knockout_context(**overrides) -> dict:
    """Minimal valid knockout context with both teams resolved."""
    ctx = {
        "match_id": "wc2026-R16-01",
        "round": "R16",
        "team_a": "TeamAlpha",
        "team_b": "TeamBeta",
        "team_a_slot": {"slot_id": "1A", "source_type": "group_rank", "group": "A", "rank": 1},
        "team_b_slot": {"slot_id": "2B", "source_type": "group_rank", "group": "B", "rank": 2},
        "winner_advances_to": "wc2026-QF-01",
        "loser_eliminated": True,
        "extra_time_possible": True,
        "penalties_possible": True,
        "data_quality": {"status": "ok", "issues": []},
    }
    ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# 1. Knockout context generates advancement_probabilities
# ---------------------------------------------------------------------------


class KnockoutContextGeneratesAdvancementTests(unittest.TestCase):
    """Valid knockout context triggers advancement computation."""

    def test_valid_knockout_context_generates_advancement(self):
        pred = _base_prediction()
        self.assertIsNone(pred.advancement_probabilities)

        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        self.assertIsNotNone(enriched.advancement_probabilities)
        adv = enriched.advancement_probabilities
        self.assertIn("team_a_advances", adv)
        self.assertIn("team_b_advances", adv)
        self.assertIn("decided_in_regulation", adv)
        self.assertIn("decided_in_extra_time", adv)
        self.assertIn("decided_on_penalties", adv)
        # 11 advancement fields + 6 audit fields = 17 total
        self.assertEqual(len(adv), 17)

    def test_knockout_context_nested_in_tournament_context(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        tc = {"knockout_context": kc, "state_mode": "pre_match"}
        enriched = _enrich_advancement(pred, tc=tc, kc=None)
        self.assertIsNotNone(enriched.advancement_probabilities)


# ---------------------------------------------------------------------------
# 2. Group context does not generate advancement_probabilities
# ---------------------------------------------------------------------------


class GroupContextNoAdvancementTests(unittest.TestCase):
    """Tournament context without knockout_context does NOT trigger advancement."""

    def test_group_tournament_context_no_advancement(self):
        pred = _base_prediction()
        tc = {
            "state_mode": "pre_match",
            "match_id": "wc2026-grpA-aaa-bbb",
            "team_a_incentive": {"primary_incentive": "must_win_for_top2"},
            "team_b_incentive": {"primary_incentive": "draw_sufficient_for_top2"},
        }
        enriched = _enrich_advancement(pred, tc=tc, kc=None)
        self.assertIsNone(enriched.advancement_probabilities)

    def test_empty_tournament_context_no_advancement(self):
        pred = _base_prediction()
        enriched = _enrich_advancement(pred, tc={}, kc=None)
        self.assertIsNone(enriched.advancement_probabilities)


# ---------------------------------------------------------------------------
# 3. No context does not generate advancement_probabilities
# ---------------------------------------------------------------------------


class NoContextNoAdvancementTests(unittest.TestCase):
    """Without any context, advancement_probabilities stays None."""

    def test_no_context_at_all(self):
        pred = _base_prediction()
        enriched = _enrich_advancement(pred, tc=None, kc=None)
        self.assertIsNone(enriched.advancement_probabilities)
        # Prediction is returned unchanged
        self.assertIs(enriched, pred)


# ---------------------------------------------------------------------------
# 4. Advancement probabilities sum to 1
# ---------------------------------------------------------------------------


class AdvancementSumsToOneTests(unittest.TestCase):
    """team_a_advances + team_b_advances == 1.0."""

    def test_advancement_sums_to_one(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        adv = enriched.advancement_probabilities

        total = adv["team_a_advances"] + adv["team_b_advances"]
        self.assertTrue(math.isclose(total, 1.0))

    def test_decision_decomposition_sums_to_one(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        adv = enriched.advancement_probabilities

        d_total = (
            adv["decided_in_regulation"]
            + adv["decided_in_extra_time"]
            + adv["decided_on_penalties"]
        )
        self.assertTrue(math.isclose(d_total, 1.0))


# ---------------------------------------------------------------------------
# 5. result_probabilities unchanged
# ---------------------------------------------------------------------------


class ResultProbabilitiesUnchangedTests(unittest.TestCase):
    """Regulation-time result_probabilities are never modified by advancement."""

    def test_result_probs_unchanged_after_advancement(self):
        pred = _base_prediction()
        original = dict(pred.result_probabilities)

        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        self.assertEqual(dict(enriched.result_probabilities), original)

    def test_expected_goals_unchanged(self):
        pred = _base_prediction()
        original = tuple(pred.expected_goals)

        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        self.assertEqual(tuple(enriched.expected_goals), original)

    def test_over_under_unchanged(self):
        pred = _base_prediction()
        original = dict(pred.over_under)

        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        self.assertEqual(dict(enriched.over_under), original)


# ---------------------------------------------------------------------------
# 6. Default ET/PK split used when context lacks override
# ---------------------------------------------------------------------------


class DefaultETPKUsedTests(unittest.TestCase):
    """When knockout_context lacks extra_time_penalty_context, defaults apply."""

    def test_default_et_pk_used_when_no_override(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()  # No extra_time_penalty_context key
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        self.assertIsNotNone(enriched.advancement_probabilities)
        # Default ET/PK limitation should be present
        self.assertIn(_ADVANCEMENT_DEFAULTS_NOTE, enriched.limitations)

    def test_defaults_produce_symmetric_split_for_even_teams(self):
        pred = _base_prediction()  # Equal teams → roughly symmetric probs
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        adv = enriched.advancement_probabilities

        # With equal teams, regulation probs are ~equal, so advancement ~equal
        self.assertTrue(math.isclose(adv["team_a_advances"], 0.5, abs_tol=0.02))
        self.assertTrue(math.isclose(adv["team_b_advances"], 0.5, abs_tol=0.02))


# ---------------------------------------------------------------------------
# 7. Custom ET/PK context changes advancement only, not 90-minute probabilities
# ---------------------------------------------------------------------------


class CustomETPKOnlyChangesAdvancementTests(unittest.TestCase):
    """Custom ET/PK parameters affect advancement but NOT regulation probs."""

    def test_custom_et_pk_changes_advancement_not_regulation(self):
        pred = _base_prediction()
        original_reg = dict(pred.result_probabilities)

        # Default context
        kc_default = _ok_knockout_context()
        enriched_default = _enrich_advancement(pred, tc=None, kc=kc_default)

        # Custom ET/PK context — team_a has ET advantage
        kc_custom = _ok_knockout_context(
            extra_time_penalty_context={
                "extra_time_resolves_probability": 0.40,
                "team_a_extra_time_win_share": 0.70,
                "team_b_extra_time_win_share": 0.30,
                "team_a_penalty_win_probability": 0.55,
                "team_b_penalty_win_probability": 0.45,
            }
        )
        enriched_custom = _enrich_advancement(pred, tc=None, kc=kc_custom)

        # Regulation probs unchanged
        self.assertEqual(dict(enriched_custom.result_probabilities), original_reg)

        # Advancement probs DIFFERENT from default
        self.assertNotEqual(
            enriched_default.advancement_probabilities["team_a_advances"],
            enriched_custom.advancement_probabilities["team_a_advances"],
        )

        # Custom context with team_a advantage should give higher team_a advancement
        self.assertGreater(
            enriched_custom.advancement_probabilities["team_a_advances"],
            enriched_default.advancement_probabilities["team_a_advances"],
        )

    def test_custom_context_no_defaults_note(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(
            extra_time_penalty_context={
                "extra_time_resolves_probability": 0.35,
                "team_a_extra_time_win_share": 0.50,
                "team_b_extra_time_win_share": 0.50,
                "team_a_penalty_win_probability": 0.50,
                "team_b_penalty_win_probability": 0.50,
            }
        )
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        # Even though the values match defaults, we DID provide explicit context,
        # so the defaults note should NOT appear
        self.assertNotIn(_ADVANCEMENT_DEFAULTS_NOTE, enriched.limitations)
        # Provided note SHOULD appear since we supplied explicit ET/PK params
        self.assertIn(_ADVANCEMENT_PROVIDED_NOTE, enriched.limitations)


# ---------------------------------------------------------------------------
# 8. Data quality warning propagates limitation
# ---------------------------------------------------------------------------


class DataQualityWarningLimitationTests(unittest.TestCase):
    """KnockoutContext data_quality warnings appear in limitations."""

    def test_warning_propagates_limitation(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(
            data_quality={"status": "warning", "issues": ["unresolved_slot: team_b"]}
        )
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        # Limitation about data quality should be present
        found = any("data quality warning" in l.lower() for l in enriched.limitations)
        self.assertTrue(found, f"Expected data quality warning in {enriched.limitations}")

    def test_ok_status_no_warning_limitation(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(
            data_quality={"status": "ok", "issues": []}
        )
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        # No data quality warning for ok status
        found = any("data quality warning" in l.lower() for l in enriched.limitations)
        self.assertFalse(found)

    def test_derived_note_always_present(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        self.assertIn(_ADVANCEMENT_DERIVED_NOTE, enriched.limitations)


# ---------------------------------------------------------------------------
# 9. Unresolved teams do not generate advancement
# ---------------------------------------------------------------------------


class UnresolvedTeamsNoAdvancementTests(unittest.TestCase):
    """When team_a or team_b is None, advancement is not computed."""

    def test_missing_team_b_no_advancement(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(team_b=None)
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        self.assertIsNone(enriched.advancement_probabilities)
        self.assertIn(_ADVANCEMENT_NO_TEAMS_NOTE, enriched.limitations)

    def test_missing_team_a_no_advancement(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(team_a=None)
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        self.assertIsNone(enriched.advancement_probabilities)
        self.assertIn(_ADVANCEMENT_NO_TEAMS_NOTE, enriched.limitations)

    def test_both_teams_none_no_advancement(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(team_a=None, team_b=None)
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        self.assertIsNone(enriched.advancement_probabilities)
        self.assertIn(_ADVANCEMENT_NO_TEAMS_NOTE, enriched.limitations)


# ---------------------------------------------------------------------------
# 10. Prediction log includes advancement_probabilities
# ---------------------------------------------------------------------------


class PredictionLogAdvancementTests(unittest.TestCase):
    """PredictionLogEntry carries advancement_probabilities in the log."""

    def test_log_entry_includes_advancement(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        entry = PredictionLogEntry(
            prediction_id="test-id",
            predicted_at="2026-06-26T00:00:00Z",
            match_id="wc2026-R16-01",
            match_id_source="provided",
            team_a=enriched.team_a,
            team_b=enriched.team_b,
            model_name="test",
            model_version="test-v1",
            model_artifact_hash="abc",
            input_context_hash="def",
            category="knockout",
            neutral_site=True,
            expected_goals=enriched.expected_goals,
            result_probabilities=dict(enriched.result_probabilities),
            over_under=dict(enriched.over_under),
            top_scores=enriched.top_scores,
            score_matrix_hash="ghi",
            tournament_context_available=True,
            limitations=enriched.limitations,
            source_snapshot_refs={},
            advancement_probabilities=enriched.advancement_probabilities,
        )
        self.assertIsNotNone(entry.advancement_probabilities)
        adv = entry.advancement_probabilities
        self.assertIn("team_a_advances", adv)

        # JSONL serialization includes advancement
        line = entry.to_jsonl()
        parsed = json.loads(line)
        self.assertIn("advancement_probabilities", parsed)
        self.assertIsNotNone(parsed["advancement_probabilities"])
        self.assertIn("team_a_advances", parsed["advancement_probabilities"])

    def test_log_entry_without_advancement(self):
        pred = _base_prediction()
        entry = PredictionLogEntry(
            prediction_id="test-id",
            predicted_at="2026-06-26T00:00:00Z",
            match_id="",
            match_id_source="missing",
            team_a=pred.team_a,
            team_b=pred.team_b,
            model_name="test",
            model_version="test-v1",
            model_artifact_hash="abc",
            input_context_hash="def",
            category="group",
            neutral_site=True,
            expected_goals=pred.expected_goals,
            result_probabilities=dict(pred.result_probabilities),
            over_under=dict(pred.over_under),
            top_scores=pred.top_scores,
            score_matrix_hash="ghi",
            tournament_context_available=False,
            limitations=pred.limitations,
            source_snapshot_refs={},
        )
        self.assertIsNone(entry.advancement_probabilities)

        line = entry.to_jsonl()
        parsed = json.loads(line)
        self.assertIn("advancement_probabilities", parsed)
        self.assertIsNone(parsed["advancement_probabilities"])

    def test_log_written_to_disk_includes_advancement(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        entry = PredictionLogEntry(
            prediction_id="test-id-disk",
            predicted_at="2026-06-26T00:00:00Z",
            match_id="wc2026-R16-01",
            match_id_source="provided",
            team_a=enriched.team_a,
            team_b=enriched.team_b,
            model_name="test",
            model_version="test-v1",
            model_artifact_hash="abc",
            input_context_hash="def",
            category="knockout",
            neutral_site=True,
            expected_goals=enriched.expected_goals,
            result_probabilities=dict(enriched.result_probabilities),
            over_under=dict(enriched.over_under),
            top_scores=enriched.top_scores,
            score_matrix_hash="ghi",
            tournament_context_available=True,
            limitations=enriched.limitations,
            source_snapshot_refs={},
            advancement_probabilities=enriched.advancement_probabilities,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = PredictionLogger(tmpdir)
            logger.write(entry)
            log_files = list(Path(tmpdir).glob("*.jsonl"))
            self.assertEqual(len(log_files), 1)
            content = log_files[0].read_text(encoding="utf-8")
            self.assertIn("advancement_probabilities", content)
            self.assertIn("team_a_advances", content)


# ---------------------------------------------------------------------------
# 11. Prediction.to_dict includes advancement_probabilities
# ---------------------------------------------------------------------------


class PredictionToDictAdvancementTests(unittest.TestCase):
    """Prediction.to_dict() serializes advancement_probabilities correctly."""

    def test_to_dict_includes_advancement_when_present(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        d = enriched.to_dict()
        self.assertIn("advancement_probabilities", d)
        self.assertIsNotNone(d["advancement_probabilities"])
        self.assertIn("team_a_advances", d["advancement_probabilities"])

    def test_to_dict_advancement_none_when_not_set(self):
        pred = _base_prediction()
        d = pred.to_dict()
        self.assertIn("advancement_probabilities", d)
        self.assertIsNone(d["advancement_probabilities"])

    def test_to_dict_roundtrip(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        d = enriched.to_dict()

        # All original fields present
        self.assertIn("team_a", d)
        self.assertIn("team_b", d)
        self.assertIn("result_probabilities", d)
        self.assertIn("expected_goals", d)
        self.assertIn("over_under", d)

        # Original probabilities unchanged in dict
        for k, v in pred.result_probabilities.items():
            self.assertAlmostEqual(d["result_probabilities"][k], v, places=10)

    def test_to_dict_include_score_matrix_still_works(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        d = enriched.to_dict(include_score_matrix=True)
        self.assertIn("score_probabilities", d)
        self.assertIn("advancement_probabilities", d)


# ---------------------------------------------------------------------------
# Edge case: invalid ET params don't crash
# ---------------------------------------------------------------------------


class InvalidETParamsFallbackTests(unittest.TestCase):
    """Malformed extra_time_penalty_context degrades gracefully."""

    def test_invalid_et_params_falls_back_to_defaults(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(
            extra_time_penalty_context={
                "extra_time_resolves_probability": 2.0,  # invalid (>1)
                "team_a_extra_time_win_share": 0.50,
                "team_b_extra_time_win_share": 0.50,
                "team_a_penalty_win_probability": 0.50,
                "team_b_penalty_win_probability": 0.50,
            }
        )
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        # Should not crash — falls back to None et_context, uses defaults
        self.assertIsNotNone(enriched.advancement_probabilities)
        # Defaults note should appear since et_context was invalid
        self.assertIn(_ADVANCEMENT_DEFAULTS_NOTE, enriched.limitations)

    def test_invalid_et_sum_falls_back_to_defaults(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(
            extra_time_penalty_context={
                "extra_time_resolves_probability": 0.35,
                "team_a_extra_time_win_share": 0.70,
                "team_b_extra_time_win_share": 0.70,  # sum > 1
                "team_a_penalty_win_probability": 0.50,
                "team_b_penalty_win_probability": 0.50,
            }
        )
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        self.assertIsNotNone(enriched.advancement_probabilities)
        self.assertIn(_ADVANCEMENT_DEFAULTS_NOTE, enriched.limitations)


# ---------------------------------------------------------------------------
# Patch 11.1 — Mixed context detection
# ---------------------------------------------------------------------------


class MixedContextWarningTests(unittest.TestCase):
    """When both tournament_context_json and knockout_context_json are provided,
    a mixed_context warning is added to limitations."""

    def test_both_contexts_provided_adds_mixed_warning(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        tc = {
            "state_mode": "pre_match",
            "match_id": "wc2026-grpA-aaa-bbb",
        }
        enriched = _enrich_advancement(pred, tc=tc, kc=kc)
        self.assertIsNotNone(enriched.advancement_probabilities)
        self.assertIn(_MIXED_CONTEXT_NOTE, enriched.limitations)

    def test_knockout_only_no_mixed_warning(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        self.assertIsNotNone(enriched.advancement_probabilities)
        self.assertNotIn(_MIXED_CONTEXT_NOTE, enriched.limitations)

    def test_nested_knockout_in_tc_no_mixed_warning(self):
        """When knockout_context is nested inside tournament_context (no separate
        knockout_context_json), no mixed warning should fire."""
        pred = _base_prediction()
        kc_nested = _ok_knockout_context()
        tc = {"knockout_context": kc_nested, "state_mode": "pre_match"}
        enriched = _enrich_advancement(pred, tc=tc, kc=None)
        self.assertIsNotNone(enriched.advancement_probabilities)
        self.assertNotIn(_MIXED_CONTEXT_NOTE, enriched.limitations)

    def test_mixed_context_still_computes_advancement(self):
        """Mixed context should not block advancement computation."""
        pred = _base_prediction()
        kc = _ok_knockout_context()
        tc = {"state_mode": "pre_match"}
        enriched = _enrich_advancement(pred, tc=tc, kc=kc)
        self.assertIsNotNone(enriched.advancement_probabilities)
        self.assertIn("team_a_advances", enriched.advancement_probabilities)


# ---------------------------------------------------------------------------
# Patch 11.1 — ET/PK source audit in advancement_probabilities
# ---------------------------------------------------------------------------


class ETPKSourceAuditTests(unittest.TestCase):
    """advancement_probabilities records et_pk_source and the 5 ET/PK parameters."""

    def test_default_source_recorded(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()  # No extra_time_penalty_context key
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        adv = enriched.advancement_probabilities

        self.assertEqual(adv["et_pk_source"], "default")
        self.assertAlmostEqual(adv["extra_time_resolves_probability"], 0.35)
        self.assertAlmostEqual(adv["team_a_extra_time_win_share"], 0.50)
        self.assertAlmostEqual(adv["team_b_extra_time_win_share"], 0.50)
        self.assertAlmostEqual(adv["team_a_penalty_win_probability"], 0.50)
        self.assertAlmostEqual(adv["team_b_penalty_win_probability"], 0.50)

    def test_provided_source_recorded(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(
            extra_time_penalty_context={
                "extra_time_resolves_probability": 0.40,
                "team_a_extra_time_win_share": 0.60,
                "team_b_extra_time_win_share": 0.40,
                "team_a_penalty_win_probability": 0.55,
                "team_b_penalty_win_probability": 0.45,
            }
        )
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        adv = enriched.advancement_probabilities

        self.assertEqual(adv["et_pk_source"], "provided")
        self.assertAlmostEqual(adv["extra_time_resolves_probability"], 0.40)
        self.assertAlmostEqual(adv["team_a_extra_time_win_share"], 0.60)
        self.assertAlmostEqual(adv["team_b_extra_time_win_share"], 0.40)
        self.assertAlmostEqual(adv["team_a_penalty_win_probability"], 0.55)
        self.assertAlmostEqual(adv["team_b_penalty_win_probability"], 0.45)

    def test_invalid_et_params_falls_back_to_default_source(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(
            extra_time_penalty_context={
                "extra_time_resolves_probability": 2.0,  # invalid
                "team_a_extra_time_win_share": 0.50,
                "team_b_extra_time_win_share": 0.50,
                "team_a_penalty_win_probability": 0.50,
                "team_b_penalty_win_probability": 0.50,
            }
        )
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        adv = enriched.advancement_probabilities

        self.assertEqual(adv["et_pk_source"], "default")
        self.assertAlmostEqual(adv["extra_time_resolves_probability"], 0.35)

    def test_advancement_dict_has_17_keys(self):
        """11 advancement fields + 6 audit fields = 17 total."""
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        self.assertEqual(len(enriched.advancement_probabilities), 17)


# ---------------------------------------------------------------------------
# Patch 11.1 — Provided ET/PK limitation
# ---------------------------------------------------------------------------


class ETPKProvidedLimitationTests(unittest.TestCase):
    """When ET/PK parameters are provided, the provided note is in limitations."""

    def test_provided_note_present_with_custom_et_pk(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(
            extra_time_penalty_context={
                "extra_time_resolves_probability": 0.30,
                "team_a_extra_time_win_share": 0.55,
                "team_b_extra_time_win_share": 0.45,
                "team_a_penalty_win_probability": 0.60,
                "team_b_penalty_win_probability": 0.40,
            }
        )
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        self.assertIn(_ADVANCEMENT_PROVIDED_NOTE, enriched.limitations)
        self.assertNotIn(_ADVANCEMENT_DEFAULTS_NOTE, enriched.limitations)

    def test_defaults_note_present_without_custom_et_pk(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)
        self.assertIn(_ADVANCEMENT_DEFAULTS_NOTE, enriched.limitations)
        self.assertNotIn(_ADVANCEMENT_PROVIDED_NOTE, enriched.limitations)


# ---------------------------------------------------------------------------
# Patch 11.1 — Log entry includes ET/PK context
# ---------------------------------------------------------------------------


class LogEntryETPKContextTests(unittest.TestCase):
    """PredictionLogEntry JSONL carries the ET/PK audit trail."""

    def test_log_entry_includes_et_pk_source(self):
        pred = _base_prediction()
        kc = _ok_knockout_context()
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        entry = PredictionLogEntry(
            prediction_id="test-etpk-log",
            predicted_at="2026-06-26T00:00:00Z",
            match_id="wc2026-R16-01",
            match_id_source="provided",
            team_a=enriched.team_a,
            team_b=enriched.team_b,
            model_name="test",
            model_version="test-v1",
            model_artifact_hash="abc",
            input_context_hash="def",
            category="knockout",
            neutral_site=True,
            expected_goals=enriched.expected_goals,
            result_probabilities=dict(enriched.result_probabilities),
            over_under=dict(enriched.over_under),
            top_scores=enriched.top_scores,
            score_matrix_hash="ghi",
            tournament_context_available=True,
            limitations=enriched.limitations,
            source_snapshot_refs={},
            advancement_probabilities=enriched.advancement_probabilities,
        )

        line = entry.to_jsonl()
        parsed = json.loads(line)
        adv = parsed["advancement_probabilities"]
        self.assertEqual(adv["et_pk_source"], "default")
        self.assertIn("extra_time_resolves_probability", adv)
        self.assertIn("team_a_extra_time_win_share", adv)
        self.assertIn("team_b_extra_time_win_share", adv)
        self.assertIn("team_a_penalty_win_probability", adv)
        self.assertIn("team_b_penalty_win_probability", adv)

    def test_log_entry_has_provided_source_in_jsonl(self):
        pred = _base_prediction()
        kc = _ok_knockout_context(
            extra_time_penalty_context={
                "extra_time_resolves_probability": 0.40,
                "team_a_extra_time_win_share": 0.60,
                "team_b_extra_time_win_share": 0.40,
                "team_a_penalty_win_probability": 0.55,
                "team_b_penalty_win_probability": 0.45,
            }
        )
        enriched = _enrich_advancement(pred, tc=None, kc=kc)

        entry = PredictionLogEntry(
            prediction_id="test-etpk-provided",
            predicted_at="2026-06-26T00:00:00Z",
            match_id="wc2026-R16-02",
            match_id_source="provided",
            team_a=enriched.team_a,
            team_b=enriched.team_b,
            model_name="test",
            model_version="test-v1",
            model_artifact_hash="abc",
            input_context_hash="def",
            category="knockout",
            neutral_site=True,
            expected_goals=enriched.expected_goals,
            result_probabilities=dict(enriched.result_probabilities),
            over_under=dict(enriched.over_under),
            top_scores=enriched.top_scores,
            score_matrix_hash="ghi",
            tournament_context_available=True,
            limitations=enriched.limitations,
            source_snapshot_refs={},
            advancement_probabilities=enriched.advancement_probabilities,
        )

        line = entry.to_jsonl()
        parsed = json.loads(line)
        adv = parsed["advancement_probabilities"]
        self.assertEqual(adv["et_pk_source"], "provided")
        self.assertAlmostEqual(adv["extra_time_resolves_probability"], 0.40)
        self.assertAlmostEqual(adv["team_a_extra_time_win_share"], 0.60)
        self.assertAlmostEqual(adv["team_b_extra_time_win_share"], 0.40)
        self.assertAlmostEqual(adv["team_a_penalty_win_probability"], 0.55)
        self.assertAlmostEqual(adv["team_b_penalty_win_probability"], 0.45)
