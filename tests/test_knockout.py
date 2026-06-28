"""Tests for oracle_core/knockout.py — advancement probability computation.

Pure schema and computation tests. No runtime integration.
"""

from __future__ import annotations

import dataclasses
import math
import unittest

from oracle_core.knockout import (
    AdvancementProbabilities,
    ExtraTimePenaltyContext,
    KnockoutRound,
    compute_advancement_probabilities,
)


# ---------------------------------------------------------------------------
# 1. Default symmetric ET/PK preserves draw split evenly
# ---------------------------------------------------------------------------


class DefaultSymmetricDrawSplitTests(unittest.TestCase):
    """With symmetric defaults, the draw probability is split evenly."""

    def test_default_splits_draw_evenly_between_teams(self):
        reg = {"team_a_win": 0.45, "draw": 0.30, "team_b_win": 0.25}
        result = compute_advancement_probabilities(reg)

        # Each team gets half the draw share: 0.30/2 = 0.15
        expected_a = 0.45 + 0.15  # = 0.60
        expected_b = 0.25 + 0.15  # = 0.40
        self.assertTrue(math.isclose(result.team_a_advances, expected_a))
        self.assertTrue(math.isclose(result.team_b_advances, expected_b))
        # The draw is split evenly
        draw_share_a = result.team_a_advances - reg["team_a_win"]
        draw_share_b = result.team_b_advances - reg["team_b_win"]
        self.assertTrue(math.isclose(draw_share_a, draw_share_b))


# ---------------------------------------------------------------------------
# 2. No draw means advancement == regulation winners
# ---------------------------------------------------------------------------


class NoDrawAdvancementTests(unittest.TestCase):
    """When draw=0, advancement probabilities equal regulation win probabilities."""

    def test_no_draw_advancement_equals_regulation(self):
        reg = {"team_a_win": 0.60, "draw": 0.0, "team_b_win": 0.40}
        result = compute_advancement_probabilities(reg)

        self.assertTrue(math.isclose(result.team_a_advances, 0.60))
        self.assertTrue(math.isclose(result.team_b_advances, 0.40))
        self.assertTrue(math.isclose(result.decided_in_regulation, 1.0))
        self.assertTrue(math.isclose(result.decided_in_extra_time, 0.0))
        self.assertTrue(math.isclose(result.decided_on_penalties, 0.0))
        self.assertTrue(math.isclose(result.team_a_extra_time_component, 0.0))
        self.assertTrue(math.isclose(result.team_a_penalty_component, 0.0))
        self.assertTrue(math.isclose(result.team_b_extra_time_component, 0.0))
        self.assertTrue(math.isclose(result.team_b_penalty_component, 0.0))

    def test_team_a_clean_win_zero_draw(self):
        reg = {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0}
        result = compute_advancement_probabilities(reg)

        self.assertTrue(math.isclose(result.team_a_advances, 1.0))
        self.assertTrue(math.isclose(result.team_b_advances, 0.0))


# ---------------------------------------------------------------------------
# 3. All draw splits through ET/PK
# ---------------------------------------------------------------------------


class AllDrawSplitsThroughETPKTests(unittest.TestCase):
    """When regulation is 100% draw, advancement is governed by ET/PK parameters."""

    def test_all_draw_splits_via_et_pk_with_symmetric_defaults(self):
        reg = {"team_a_win": 0.0, "draw": 1.0, "team_b_win": 0.0}
        result = compute_advancement_probabilities(reg)

        # Symmetric defaults → 50/50 advancement
        self.assertTrue(math.isclose(result.team_a_advances, 0.5))
        self.assertTrue(math.isclose(result.team_b_advances, 0.5))
        self.assertTrue(math.isclose(result.decided_in_regulation, 0.0))
        self.assertTrue(math.isclose(result.decided_in_extra_time, 0.35))
        self.assertTrue(math.isclose(result.decided_on_penalties, 0.65))

    def test_all_draw_with_asymmetric_et_share(self):
        reg = {"team_a_win": 0.0, "draw": 1.0, "team_b_win": 0.0}
        et = ExtraTimePenaltyContext(
            team_a_extra_time_win_share=0.70,
            team_b_extra_time_win_share=0.30,
        )
        result = compute_advancement_probabilities(reg, et)

        # ET share is 70/30 for team_a, PK is still 50/50
        expected_a = 0.35 * 0.70 + 0.65 * 0.50  # = 0.245 + 0.325 = 0.57
        expected_b = 0.35 * 0.30 + 0.65 * 0.50  # = 0.105 + 0.325 = 0.43
        self.assertTrue(math.isclose(result.team_a_advances, expected_a))
        self.assertTrue(math.isclose(result.team_b_advances, expected_b))


# ---------------------------------------------------------------------------
# 4. team_a ET advantage increases team_a advancement
# ---------------------------------------------------------------------------


class TeamAETAdvantageTests(unittest.TestCase):
    """Increasing team_a's ET win share increases team_a's advancement probability."""

    def test_et_advantage_increases_team_a_advancement(self):
        reg = {"team_a_win": 0.40, "draw": 0.35, "team_b_win": 0.25}

        result_default = compute_advancement_probabilities(reg)

        et_biased = ExtraTimePenaltyContext(
            team_a_extra_time_win_share=0.70,
            team_b_extra_time_win_share=0.30,
        )
        result_biased = compute_advancement_probabilities(reg, et_biased)

        self.assertGreater(
            result_biased.team_a_advances, result_default.team_a_advances
        )
        self.assertLess(
            result_biased.team_b_advances, result_default.team_b_advances
        )
        # ET component for team_a should be larger with advantage
        self.assertGreater(
            result_biased.team_a_extra_time_component,
            result_default.team_a_extra_time_component,
        )


# ---------------------------------------------------------------------------
# 5. team_a PK advantage increases team_a advancement
# ---------------------------------------------------------------------------


class TeamAPKAdvantageTests(unittest.TestCase):
    """Increasing team_a's PK win probability increases team_a's advancement probability."""

    def test_pk_advantage_increases_team_a_advancement(self):
        reg = {"team_a_win": 0.40, "draw": 0.35, "team_b_win": 0.25}

        result_default = compute_advancement_probabilities(reg)

        pk_biased = ExtraTimePenaltyContext(
            team_a_penalty_win_probability=0.70,
            team_b_penalty_win_probability=0.30,
        )
        result_biased = compute_advancement_probabilities(reg, pk_biased)

        self.assertGreater(
            result_biased.team_a_advances, result_default.team_a_advances
        )
        self.assertLess(
            result_biased.team_b_advances, result_default.team_b_advances
        )
        # PK component for team_a should be larger with advantage
        self.assertGreater(
            result_biased.team_a_penalty_component,
            result_default.team_a_penalty_component,
        )


# ---------------------------------------------------------------------------
# 6. Invalid missing key raises ValueError
# ---------------------------------------------------------------------------


class InvalidMissingKeyTests(unittest.TestCase):
    """Missing required keys in regulation_probs raise ValueError."""

    def test_missing_team_a_win_raises_valueerror(self):
        with self.assertRaises(ValueError):
            compute_advancement_probabilities({"draw": 0.30, "team_b_win": 0.25})

    def test_missing_draw_raises_valueerror(self):
        with self.assertRaises(ValueError):
            compute_advancement_probabilities({"team_a_win": 0.45, "team_b_win": 0.25})

    def test_missing_team_b_win_raises_valueerror(self):
        with self.assertRaises(ValueError):
            compute_advancement_probabilities({"team_a_win": 0.45, "draw": 0.30})

    def test_empty_dict_raises_valueerror(self):
        with self.assertRaises(ValueError):
            compute_advancement_probabilities({})


# ---------------------------------------------------------------------------
# 7. Invalid probability sum raises ValueError
# ---------------------------------------------------------------------------


class InvalidProbabilitySumTests(unittest.TestCase):
    """Regulation probabilities that don't sum to 1 raise ValueError."""

    def test_sum_too_low_raises_valueerror(self):
        with self.assertRaises(ValueError):
            compute_advancement_probabilities(
                {"team_a_win": 0.3, "draw": 0.3, "team_b_win": 0.3}
            )

    def test_sum_too_high_raises_valueerror(self):
        with self.assertRaises(ValueError):
            compute_advancement_probabilities(
                {"team_a_win": 0.5, "draw": 0.5, "team_b_win": 0.5}
            )

    def test_negative_value_raises_valueerror(self):
        with self.assertRaises(ValueError):
            compute_advancement_probabilities(
                {"team_a_win": 0.5, "draw": 0.5, "team_b_win": -0.01}
            )

    def test_nan_value_raises_valueerror(self):
        with self.assertRaises(ValueError):
            compute_advancement_probabilities(
                {"team_a_win": float("nan"), "draw": 0.5, "team_b_win": 0.5}
            )

    def test_inf_value_raises_valueerror(self):
        with self.assertRaises(ValueError):
            compute_advancement_probabilities(
                {"team_a_win": float("inf"), "draw": 0.5, "team_b_win": 0.5}
            )


# ---------------------------------------------------------------------------
# 8. Invalid ET share sum raises ValueError
# ---------------------------------------------------------------------------


class InvalidETShareSumTests(unittest.TestCase):
    """ET win shares that don't sum to 1 raise ValueError on construction."""

    def test_et_shares_sum_not_one_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ExtraTimePenaltyContext(
                team_a_extra_time_win_share=0.6,
                team_b_extra_time_win_share=0.6,
            )

    def test_et_share_negative_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ExtraTimePenaltyContext(
                team_a_extra_time_win_share=-0.1,
                team_b_extra_time_win_share=1.1,
            )


# ---------------------------------------------------------------------------
# 9. Invalid PK sum raises ValueError
# ---------------------------------------------------------------------------


class InvalidPKSumTests(unittest.TestCase):
    """PK win probabilities that don't sum to 1 raise ValueError on construction."""

    def test_pk_shares_sum_not_one_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ExtraTimePenaltyContext(
                team_a_penalty_win_probability=0.4,
                team_b_penalty_win_probability=0.4,
            )

    def test_pk_share_negative_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ExtraTimePenaltyContext(
                team_a_penalty_win_probability=-0.5,
                team_b_penalty_win_probability=1.5,
            )


# ---------------------------------------------------------------------------
# 10. Components sum correctly
# ---------------------------------------------------------------------------


class ComponentsSumCorrectlyTests(unittest.TestCase):
    """Internal component fields sum to the top-level advancement values."""

    def test_components_sum_to_advancement_values(self):
        reg = {"team_a_win": 0.48, "draw": 0.28, "team_b_win": 0.24}
        et = ExtraTimePenaltyContext(
            extra_time_resolves_probability=0.40,
            team_a_extra_time_win_share=0.55,
            team_b_extra_time_win_share=0.45,
            team_a_penalty_win_probability=0.48,
            team_b_penalty_win_probability=0.52,
        )
        result = compute_advancement_probabilities(reg, et)

        # team_a components sum to team_a_advances
        a_sum = (
            result.team_a_regulation_component
            + result.team_a_extra_time_component
            + result.team_a_penalty_component
        )
        self.assertTrue(math.isclose(a_sum, result.team_a_advances))

        # team_b components sum to team_b_advances
        b_sum = (
            result.team_b_regulation_component
            + result.team_b_extra_time_component
            + result.team_b_penalty_component
        )
        self.assertTrue(math.isclose(b_sum, result.team_b_advances))

        # Decision decomposition sums to 1
        d_sum = (
            result.decided_in_regulation
            + result.decided_in_extra_time
            + result.decided_on_penalties
        )
        self.assertTrue(math.isclose(d_sum, 1.0))


# ---------------------------------------------------------------------------
# 11. Outputs sum to 1
# ---------------------------------------------------------------------------


class OutputsSumToOneTests(unittest.TestCase):
    """Advancement probabilities for both teams sum to 1."""

    def test_outputs_sum_to_one_with_default_context(self):
        reg = {"team_a_win": 0.55, "draw": 0.25, "team_b_win": 0.20}
        result = compute_advancement_probabilities(reg)
        self.assertTrue(
            math.isclose(result.team_a_advances + result.team_b_advances, 1.0)
        )

    def test_outputs_sum_to_one_with_asymmetric_context(self):
        reg = {"team_a_win": 0.33, "draw": 0.34, "team_b_win": 0.33}
        et = ExtraTimePenaltyContext(
            extra_time_resolves_probability=0.30,
            team_a_extra_time_win_share=0.65,
            team_b_extra_time_win_share=0.35,
            team_a_penalty_win_probability=0.55,
            team_b_penalty_win_probability=0.45,
        )
        result = compute_advancement_probabilities(reg, et)
        self.assertTrue(
            math.isclose(result.team_a_advances + result.team_b_advances, 1.0)
        )

    def test_outputs_sum_to_one_edge_case_high_draw(self):
        reg = {"team_a_win": 0.05, "draw": 0.90, "team_b_win": 0.05}
        result = compute_advancement_probabilities(reg)
        self.assertTrue(
            math.isclose(result.team_a_advances + result.team_b_advances, 1.0)
        )


# ---------------------------------------------------------------------------
# 12. Dataclass serializes cleanly
# ---------------------------------------------------------------------------


class DataclassSerializationTests(unittest.TestCase):
    """Both dataclasses can be serialized via dataclasses.asdict."""

    def test_advancement_probabilities_asdict(self):
        result = AdvancementProbabilities(
            team_a_advances=0.60,
            team_b_advances=0.40,
            decided_in_regulation=0.70,
            decided_in_extra_time=0.105,
            decided_on_penalties=0.195,
            team_a_regulation_component=0.45,
            team_b_regulation_component=0.25,
            team_a_extra_time_component=0.0525,
            team_b_extra_time_component=0.0525,
            team_a_penalty_component=0.0975,
            team_b_penalty_component=0.0975,
        )
        d = dataclasses.asdict(result)

        self.assertEqual(d["team_a_advances"], 0.60)
        self.assertEqual(d["team_b_advances"], 0.40)
        self.assertEqual(d["decided_in_regulation"], 0.70)
        self.assertEqual(len(d), 11)
        # All values should be JSON-serializable floats
        for key, value in d.items():
            with self.subTest(key=key):
                self.assertIsInstance(value, float)

    def test_extra_time_penalty_context_asdict(self):
        ctx = ExtraTimePenaltyContext(
            extra_time_resolves_probability=0.40,
            team_a_extra_time_win_share=0.55,
            team_b_extra_time_win_share=0.45,
            team_a_penalty_win_probability=0.48,
            team_b_penalty_win_probability=0.52,
        )
        d = dataclasses.asdict(ctx)

        self.assertEqual(d["extra_time_resolves_probability"], 0.40)
        self.assertEqual(d["team_a_extra_time_win_share"], 0.55)
        self.assertEqual(d["team_b_extra_time_win_share"], 0.45)
        self.assertEqual(d["team_a_penalty_win_probability"], 0.48)
        self.assertEqual(d["team_b_penalty_win_probability"], 0.52)
        self.assertEqual(len(d), 5)

    def test_roundtrip_compute_and_serialize(self):
        """Full round-trip: compute → serialize → verify."""
        reg = {"team_a_win": 0.45, "draw": 0.30, "team_b_win": 0.25}
        result = compute_advancement_probabilities(reg)
        d = dataclasses.asdict(result)

        # Verify all keys are present
        expected_keys = [
            "team_a_advances",
            "team_b_advances",
            "decided_in_regulation",
            "decided_in_extra_time",
            "decided_on_penalties",
            "team_a_regulation_component",
            "team_b_regulation_component",
            "team_a_extra_time_component",
            "team_b_extra_time_component",
            "team_a_penalty_component",
            "team_b_penalty_component",
        ]
        for key in expected_keys:
            self.assertIn(key, d)
        self.assertEqual(len(d), len(expected_keys))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class KnockoutRoundEnumTests(unittest.TestCase):
    """Verify KnockoutRound enum values."""

    def test_all_rounds_defined(self):
        self.assertEqual(KnockoutRound.R32.value, "R32")
        self.assertEqual(KnockoutRound.R16.value, "R16")
        self.assertEqual(KnockoutRound.QF.value, "QF")
        self.assertEqual(KnockoutRound.SF.value, "SF")
        self.assertEqual(KnockoutRound.THIRD_PLACE.value, "THIRD_PLACE")
        self.assertEqual(KnockoutRound.FINAL.value, "FINAL")
        self.assertEqual(len(KnockoutRound), 6)


# ---------------------------------------------------------------------------
# ExtraTimePenaltyContext defaults
# ---------------------------------------------------------------------------


class ExtraTimePenaltyContextDefaultTests(unittest.TestCase):
    """Verify default construction and validation."""

    def test_default_context_is_valid(self):
        ctx = ExtraTimePenaltyContext()
        self.assertEqual(ctx.extra_time_resolves_probability, 0.35)
        self.assertEqual(ctx.team_a_extra_time_win_share, 0.50)
        self.assertEqual(ctx.team_b_extra_time_win_share, 0.50)
        self.assertEqual(ctx.team_a_penalty_win_probability, 0.50)
        self.assertEqual(ctx.team_b_penalty_win_probability, 0.50)

    def test_et_resolve_out_of_range_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ExtraTimePenaltyContext(extra_time_resolves_probability=1.5)

        with self.assertRaises(ValueError):
            ExtraTimePenaltyContext(extra_time_resolves_probability=-0.1)

    def test_default_context_sums_are_valid(self):
        ctx = ExtraTimePenaltyContext()
        self.assertTrue(
            math.isclose(
                ctx.team_a_extra_time_win_share + ctx.team_b_extra_time_win_share, 1.0
            )
        )
        self.assertTrue(
            math.isclose(
                ctx.team_a_penalty_win_probability
                + ctx.team_b_penalty_win_probability,
                1.0,
            )
        )
