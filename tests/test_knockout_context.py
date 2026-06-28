"""Tests for knockout context generation — Patch 10.

Covers bracket loading, get_knockout_state, data quality checks.
No runtime integration with predict_match / MCP / evaluation / logs.
"""

from __future__ import annotations

import dataclasses
import math
import os
import tempfile
import unittest
from pathlib import Path

from oracle_core.knockout import (
    AdvancementProbabilities,
    BracketSlot,
    ExtraTimePenaltyContext,
    KnockoutContext,
    KnockoutMatch,
    KnockoutRound,
    compute_advancement_probabilities,
    get_knockout_state,
    load_knockout_bracket,
)


# ---------------------------------------------------------------------------
# Path to the test fixture
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_BRACKET_PATH = str(_FIXTURE_DIR / "knockout-bracket.yaml")


# ---------------------------------------------------------------------------
# 1. Load bracket fixture
# ---------------------------------------------------------------------------


class LoadBracketFixtureTests(unittest.TestCase):
    """load_knockout_bracket parses the fixture YAML correctly."""

    @classmethod
    def setUpClass(cls):
        cls.bracket = load_knockout_bracket(_BRACKET_PATH)

    def test_loads_seven_matches(self):
        self.assertEqual(len(self.bracket), 7)

    def test_all_matches_are_knockout_match_instances(self):
        for match in self.bracket:
            self.assertIsInstance(match, KnockoutMatch)

    def test_first_match_is_r16_fic_alpha_fic_beta(self):
        match = self.bracket[0]
        self.assertEqual(match.match_id, "wc2026-R16-01")
        self.assertEqual(match.round, KnockoutRound.R16)
        self.assertEqual(match.team_a, "FIC_ALPHA")
        self.assertEqual(match.team_b, "FIC_BETA")
        self.assertEqual(match.status, "scheduled")
        self.assertIsNone(match.winner)

    def test_completed_match_has_score_and_winner(self):
        match = self.bracket[2]  # wc2026-R32-01
        self.assertEqual(match.match_id, "wc2026-R32-01")
        self.assertEqual(match.status, "completed")
        self.assertEqual(match.regulation_score, (2, 1))
        self.assertEqual(match.winner, "TeamDelta")

    def test_match_with_et_and_pk_scores(self):
        match = self.bracket[4]  # wc2026-QF-missing-winner
        self.assertEqual(match.regulation_score, (1, 1))
        self.assertEqual(match.extra_time_score, (0, 0))
        self.assertEqual(match.penalties_score, (4, 3))

    def test_pk_no_et_match(self):
        match = self.bracket[5]  # wc2026-R16-pk-no-et
        self.assertEqual(match.regulation_score, (0, 0))
        self.assertIsNone(match.extra_time_score)
        self.assertEqual(match.penalties_score, (5, 4))


# ---------------------------------------------------------------------------
# 2. Parse BracketSlot group_rank: "1A"
# ---------------------------------------------------------------------------


class ParseBracketSlotGroupRankTests(unittest.TestCase):
    """BracketSlot correctly parses group_rank slots."""

    @classmethod
    def setUpClass(cls):
        cls.bracket = load_knockout_bracket(_BRACKET_PATH)

    def test_team_a_slot_is_group_rank_1a(self):
        match = self.bracket[0]  # wc2026-R16-01
        slot = match.team_a_slot
        self.assertEqual(slot.slot_id, "1A")
        self.assertEqual(slot.source_type, "group_rank")
        self.assertEqual(slot.group, "A")
        self.assertEqual(slot.rank, 1)
        self.assertIsNone(slot.source_match_id)
        self.assertIsNone(slot.resolved_team)

    def test_team_b_slot_is_group_rank_2b(self):
        match = self.bracket[0]
        slot = match.team_b_slot
        self.assertEqual(slot.slot_id, "2B")
        self.assertEqual(slot.source_type, "group_rank")
        self.assertEqual(slot.group, "B")
        self.assertEqual(slot.rank, 2)

    def test_from_dict_constructs_slot(self):
        data = {"slot_id": "3C", "source_type": "group_rank",
                "group": "C", "rank": 3}
        slot = BracketSlot.from_dict(data)
        self.assertEqual(slot.slot_id, "3C")
        self.assertEqual(slot.source_type, "group_rank")
        self.assertEqual(slot.group, "C")
        self.assertEqual(slot.rank, 3)


# ---------------------------------------------------------------------------
# 3. Parse BracketSlot match_winner: "W-R32-01"
# ---------------------------------------------------------------------------


class ParseBracketSlotMatchWinnerTests(unittest.TestCase):
    """BracketSlot correctly parses match_winner slots."""

    @classmethod
    def setUpClass(cls):
        cls.bracket = load_knockout_bracket(_BRACKET_PATH)

    def test_team_b_slot_is_match_winner(self):
        match = self.bracket[1]  # wc2026-R16-02
        slot = match.team_b_slot
        self.assertEqual(slot.slot_id, "W-R32-07")
        self.assertEqual(slot.source_type, "match_winner")
        self.assertEqual(slot.source_match_id, "wc2026-R32-07")
        self.assertIsNone(slot.group)
        self.assertIsNone(slot.rank)
        self.assertIsNone(slot.resolved_team)

    def test_team_a_slot_is_match_winner_from_prior_round(self):
        match = self.bracket[3]  # wc2026-R16-03
        slot = match.team_a_slot
        self.assertEqual(slot.slot_id, "W-R32-01")
        self.assertEqual(slot.source_type, "match_winner")
        self.assertEqual(slot.source_match_id, "wc2026-R32-01")

    def test_from_dict_constructs_match_winner_slot(self):
        data = {"slot_id": "W-R16-05", "source_type": "match_winner",
                "source_match_id": "wc2026-R16-05"}
        slot = BracketSlot.from_dict(data)
        self.assertEqual(slot.slot_id, "W-R16-05")
        self.assertEqual(slot.source_type, "match_winner")
        self.assertEqual(slot.source_match_id, "wc2026-R16-05")
        self.assertIsNone(slot.group)


# ---------------------------------------------------------------------------
# 4. get_knockout_state scheduled resolved match returns ok
# ---------------------------------------------------------------------------


class KnockoutStateOkTests(unittest.TestCase):
    """get_knockout_state returns 'ok' for clean scheduled matches."""

    @classmethod
    def setUpClass(cls):
        cls.bracket = load_knockout_bracket(_BRACKET_PATH)

    def test_scheduled_resolved_match_returns_ok(self):
        ctx = get_knockout_state("wc2026-R16-01", self.bracket)
        self.assertEqual(ctx.match_id, "wc2026-R16-01")
        self.assertEqual(ctx.round, "R16")
        self.assertEqual(ctx.team_a, "FIC_ALPHA")
        self.assertEqual(ctx.team_b, "FIC_BETA")
        self.assertEqual(ctx.data_quality["status"], "ok")
        self.assertEqual(ctx.data_quality["issues"], [])

    def test_scheduled_resolved_match_extra_time_info(self):
        ctx = get_knockout_state("wc2026-R16-01", self.bracket)
        # R16: ET possible, PK possible, loser IS eliminated
        self.assertTrue(ctx.extra_time_possible)
        self.assertTrue(ctx.penalties_possible)
        self.assertTrue(ctx.loser_eliminated)

    def test_final_has_no_loser_elimination(self):
        # Need a final match in bracket... we don't have one.
        # Test via the logic: create a minimal bracket with a final match.
        final_match = KnockoutMatch(
            match_id="wc2026-FINAL",
            round=KnockoutRound.FINAL,
            team_a_slot=BracketSlot("W-SF-01", "match_winner",
                                    source_match_id="wc2026-SF-01"),
            team_b_slot=BracketSlot("W-SF-02", "match_winner",
                                    source_match_id="wc2026-SF-02"),
            team_a="TeamX", team_b="TeamY", status="scheduled",
        )
        bracket = [final_match]
        ctx = get_knockout_state("wc2026-FINAL", bracket)
        self.assertFalse(ctx.loser_eliminated)
        self.assertTrue(ctx.extra_time_possible)  # FINAL has extra time

    def test_third_place_no_extra_time(self):
        match = KnockoutMatch(
            match_id="wc2026-3RD",
            round=KnockoutRound.THIRD_PLACE,
            team_a_slot=BracketSlot("L-SF-01", "match_loser",
                                    source_match_id="wc2026-SF-01"),
            team_b_slot=BracketSlot("L-SF-02", "match_loser",
                                    source_match_id="wc2026-SF-02"),
            team_a="TeamP", team_b="TeamQ", status="scheduled",
        )
        bracket = [match]
        ctx = get_knockout_state("wc2026-3RD", bracket)
        self.assertFalse(ctx.extra_time_possible)
        self.assertTrue(ctx.penalties_possible)
        self.assertFalse(ctx.loser_eliminated)


# ---------------------------------------------------------------------------
# 5. Unresolved slot returns warning
# ---------------------------------------------------------------------------


class UnresolvedSlotWarningTests(unittest.TestCase):
    """get_knockout_state flags unresolved slots as warning."""

    @classmethod
    def setUpClass(cls):
        cls.bracket = load_knockout_bracket(_BRACKET_PATH)

    def test_partially_unresolved_match_returns_warning(self):
        ctx = get_knockout_state("wc2026-R16-02", self.bracket)
        self.assertEqual(ctx.match_id, "wc2026-R16-02")
        self.assertEqual(ctx.team_a, "FIC_GAMMA")
        self.assertIsNone(ctx.team_b)  # unresolved
        self.assertEqual(ctx.data_quality["status"], "warning")
        issues = ctx.data_quality["issues"]
        self.assertIn("unresolved_slot: team_b", issues)

    def test_fully_unresolved_match_returns_warning(self):
        ctx = get_knockout_state("wc2026-R32-unresolved", self.bracket)
        self.assertIsNone(ctx.team_a)
        self.assertIsNone(ctx.team_b)
        self.assertEqual(ctx.data_quality["status"], "warning")
        issues = ctx.data_quality["issues"]
        self.assertIn("unresolved_slot: team_a", issues)
        self.assertIn("unresolved_slot: team_b", issues)


# ---------------------------------------------------------------------------
# 6. Completed match without winner returns warning
# ---------------------------------------------------------------------------


class CompletedWithoutWinnerWarningTests(unittest.TestCase):
    """get_knockout_state flags completed-without-winner as warning."""

    @classmethod
    def setUpClass(cls):
        cls.bracket = load_knockout_bracket(_BRACKET_PATH)

    def test_completed_missing_winner_returns_warning(self):
        ctx = get_knockout_state("wc2026-QF-missing-winner", self.bracket)
        self.assertEqual(ctx.data_quality["status"], "warning")
        issues = ctx.data_quality["issues"]
        self.assertIn("missing_winner", issues)

    def test_completed_with_winner_returns_ok(self):
        ctx = get_knockout_state("wc2026-R32-01", self.bracket)
        self.assertEqual(ctx.data_quality["status"], "ok")


# ---------------------------------------------------------------------------
# 7. Penalties without extra_time_score returns warning
# ---------------------------------------------------------------------------


class PenaltiesWithoutETWarningTests(unittest.TestCase):
    """get_knockout_state flags pk-no-et as warning."""

    @classmethod
    def setUpClass(cls):
        cls.bracket = load_knockout_bracket(_BRACKET_PATH)

    def test_pk_without_et_returns_warning(self):
        ctx = get_knockout_state("wc2026-R16-pk-no-et", self.bracket)
        self.assertEqual(ctx.data_quality["status"], "warning")
        issues = ctx.data_quality["issues"]
        self.assertIn("penalties_without_extra_time_score", issues)

    def test_pk_with_et_is_ok(self):
        ctx = get_knockout_state("wc2026-QF-missing-winner", self.bracket)
        # This match has both ET and PK scores, so no "penalties_without_extra_time_score"
        issues = ctx.data_quality["issues"]
        self.assertNotIn("penalties_without_extra_time_score", issues)
        # But it does have missing_winner
        self.assertIn("missing_winner", issues)


# ---------------------------------------------------------------------------
# 8. Invalid match_id raises ValueError
# ---------------------------------------------------------------------------


class InvalidMatchIdTests(unittest.TestCase):
    """get_knockout_state raises ValueError for unknown match_id."""

    @classmethod
    def setUpClass(cls):
        cls.bracket = load_knockout_bracket(_BRACKET_PATH)

    def test_nonexistent_match_id_raises_valueerror(self):
        with self.assertRaises(ValueError) as ctx:
            get_knockout_state("wc2026-NONEXISTENT", self.bracket)
        self.assertIn("wc2026-NONEXISTENT", str(ctx.exception))

    def test_empty_match_id_raises_valueerror(self):
        with self.assertRaises(ValueError) as ctx:
            get_knockout_state("", self.bracket)
        self.assertIn("''", str(ctx.exception))

    def test_empty_bracket_raises_valueerror(self):
        with self.assertRaises(ValueError):
            get_knockout_state("wc2026-any", [])


# ---------------------------------------------------------------------------
# 9. KnockoutContext serializes cleanly with asdict
# ---------------------------------------------------------------------------


class KnockoutContextSerializationTests(unittest.TestCase):
    """KnockoutContext and its dependent types serialize via dataclasses.asdict."""

    @classmethod
    def setUpClass(cls):
        cls.bracket = load_knockout_bracket(_BRACKET_PATH)

    def test_context_asdict_all_keys_present(self):
        ctx = get_knockout_state("wc2026-R16-01", self.bracket)
        d = dataclasses.asdict(ctx)

        expected_keys = [
            "match_id", "round", "team_a", "team_b",
            "team_a_slot", "team_b_slot",
            "winner_advances_to", "loser_eliminated",
            "extra_time_possible", "penalties_possible",
            "data_quality",
        ]
        for key in expected_keys:
            self.assertIn(key, d)
        self.assertEqual(len(d), len(expected_keys))

    def test_context_slot_dicts_are_deserializable(self):
        ctx = get_knockout_state("wc2026-R16-01", self.bracket)
        # team_a_slot and team_b_slot are dicts — verify they can be
        # round-tripped through BracketSlot.from_dict
        slot_a = BracketSlot.from_dict(ctx.team_a_slot)
        self.assertEqual(slot_a.slot_id, "1A")
        self.assertEqual(slot_a.source_type, "group_rank")

    def test_context_winner_advances_to_resolved(self):
        # wc2026-R32-01 winner advances to wc2026-R16-03
        ctx = get_knockout_state("wc2026-R32-01", self.bracket)
        self.assertEqual(ctx.winner_advances_to, "wc2026-R16-03")

    def test_context_winner_advances_to_none_when_no_next_match(self):
        # wc2026-R16-03 winner does not advance to anything in this bracket
        ctx = get_knockout_state("wc2026-R16-03", self.bracket)
        self.assertIsNone(ctx.winner_advances_to)

    def test_bracket_slot_asdict(self):
        slot = BracketSlot("1A", "group_rank", group="A", rank=1)
        d = dataclasses.asdict(slot)
        self.assertEqual(d["slot_id"], "1A")
        self.assertEqual(d["source_type"], "group_rank")
        self.assertEqual(d["group"], "A")
        self.assertEqual(d["rank"], 1)
        self.assertIsNone(d["source_match_id"])
        self.assertIsNone(d["resolved_team"])

    def test_knockout_match_asdict(self):
        match = self.bracket[0]  # wc2026-R16-01
        d = dataclasses.asdict(match)
        self.assertEqual(d["match_id"], "wc2026-R16-01")
        self.assertEqual(d["round"], "R16")
        self.assertEqual(d["team_a"], "FIC_ALPHA")
        self.assertIsInstance(d["team_a_slot"], dict)
        self.assertIsInstance(d["team_b_slot"], dict)


# ---------------------------------------------------------------------------
# 10. No runtime integration with predict_match
# ---------------------------------------------------------------------------


class NoRuntimeIntegrationTests(unittest.TestCase):
    """Verify knockout module does not import or touch runtime modules."""

    def test_knockout_module_does_not_import_predict_match(self):
        """The knockout module must not import predict_match or its callers."""
        import oracle_core.knockout as ko
        src = Path(ko.__file__).read_text(encoding="utf-8")
        # Docstring mentions predict_match as an invariant — that's fine.
        # We check for actual import statements only.
        self.assertNotIn("from oracle_core.model", src)
        self.assertNotIn("import oracle_core.model", src)
        self.assertNotIn("from oracle_core import model", src)
        self.assertNotIn("from oracle_core.evaluation", src)
        self.assertNotIn("from oracle_core.logging", src)

    def test_knockout_module_does_not_import_evaluation(self):
        import oracle_core.knockout as ko
        src = Path(ko.__file__).read_text(encoding="utf-8")
        self.assertNotIn("evaluation", src)

    def test_knockout_module_does_not_import_odds(self):
        import oracle_core.knockout as ko
        src = Path(ko.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from oracle_core.odds", src)
        self.assertNotIn("import oracle_core.odds", src)

    def test_prediction_unchanged_by_knockout_state(self):
        """Advancement probabilities are pure — no side effects on prediction."""
        reg = {"team_a_win": 0.45, "draw": 0.30, "team_b_win": 0.25}
        result1 = compute_advancement_probabilities(reg)
        result2 = compute_advancement_probabilities(reg)
        # Deterministic
        self.assertTrue(math.isclose(result1.team_a_advances, result2.team_a_advances))
        self.assertTrue(math.isclose(result1.team_b_advances, result2.team_b_advances))


# ---------------------------------------------------------------------------
# Additional: load_knockout_bracket error cases
# ---------------------------------------------------------------------------


class LoadBracketErrorTests(unittest.TestCase):
    """load_knockout_bracket raises appropriate errors."""

    def test_file_not_found_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_knockout_bracket("/nonexistent/path/bracket.yaml")

    def test_empty_file_raises_valueerror(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("")
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_knockout_bracket(path)
        finally:
            os.unlink(path)

    def test_null_yaml_raises_valueerror(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("null\n")
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_knockout_bracket(path)
        finally:
            os.unlink(path)

    def test_plain_list_bracket(self):
        """load_knockout_bracket accepts a plain YAML list (no 'bracket' key)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("""
- match_id: "test-01"
  round: "QF"
  team_a_slot:
    slot_id: "W-R16-99"
    source_type: "match_winner"
    source_match_id: "wc2026-R16-99"
  team_b_slot:
    slot_id: "W-R16-98"
    source_type: "match_winner"
    source_match_id: "wc2026-R16-98"
  team_a: "TeamOne"
  team_b: "TeamTwo"
  status: "scheduled"
""")
            path = f.name
        try:
            bracket = load_knockout_bracket(path)
            self.assertEqual(len(bracket), 1)
            self.assertEqual(bracket[0].match_id, "test-01")
            self.assertEqual(bracket[0].round, KnockoutRound.QF)
        finally:
            os.unlink(path)
