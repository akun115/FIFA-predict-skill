import math
import unittest

from oracle_core.model import ModelConfig, TeamSnapshot, predict_match


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.a = TeamSnapshot("A", 1800, 75, 72, form=0.1, availability=0.0)
        self.b = TeamSnapshot("B", 1700, 70, 68, form=-0.1, availability=-0.05)

    def test_prediction_is_deterministic_and_normalized(self):
        first = predict_match(self.a, self.b, neutral_site=True)
        second = predict_match(self.a, self.b, neutral_site=True)

        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(first.result_probabilities.values()), 1.0, places=10)
        self.assertAlmostEqual(sum(first.score_probabilities.values()), 1.0, places=10)
        self.assertTrue(all(math.isfinite(value) for value in first.expected_goals))
        self.assertTrue(all(value >= 0 for value in first.score_probabilities.values()))

    def test_same_team_prediction_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "teams must differ"):
            predict_match(self.a, self.a, neutral_site=True)

    def test_neutral_site_swap_is_mirrored(self):
        ab = predict_match(self.a, self.b, neutral_site=True)
        ba = predict_match(self.b, self.a, neutral_site=True)

        self.assertAlmostEqual(
            ab.result_probabilities["team_a_win"],
            ba.result_probabilities["team_b_win"],
            places=10,
        )
        self.assertAlmostEqual(ab.expected_goals[0], ba.expected_goals[1], places=10)
        for (goals_a, goals_b), probability in ab.score_probabilities.items():
            self.assertAlmostEqual(probability, ba.score_probabilities[(goals_b, goals_a)], places=10)

    def test_attack_and_opponent_defense_change_expected_goals(self):
        baseline = predict_match(self.a, self.b, neutral_site=True)
        stronger_attack = TeamSnapshot("A", 1800, 85, 72, form=0.1, availability=0.0)
        weaker_defense = TeamSnapshot("B", 1700, 70, 58, form=-0.1, availability=-0.05)

        attack_result = predict_match(stronger_attack, self.b, neutral_site=True)
        defense_result = predict_match(self.a, weaker_defense, neutral_site=True)

        self.assertGreater(attack_result.expected_goals[0], baseline.expected_goals[0])
        self.assertGreater(defense_result.expected_goals[0], baseline.expected_goals[0])

    def test_explicit_home_advantage_only_affects_named_home_team(self):
        neutral = predict_match(self.a, self.b, neutral_site=True)
        home = predict_match(self.a, self.b, neutral_site=False, home_team="A")

        self.assertGreater(home.expected_goals[0], neutral.expected_goals[0])
        self.assertAlmostEqual(home.expected_goals[1], neutral.expected_goals[1], places=10)

    def test_tail_tolerance_expands_score_grid(self):
        result = predict_match(
            TeamSnapshot("A", 2200, 100, 60, form=1.0, availability=0.5),
            TeamSnapshot("B", 1200, 40, 30, form=-1.0, availability=-0.5),
            neutral_site=True,
            config=ModelConfig(tail_tolerance=1e-10),
        )

        self.assertGreater(max(score[0] for score in result.score_probabilities), 6)
        self.assertAlmostEqual(sum(result.score_probabilities.values()), 1.0, places=10)

    def test_over_under_probabilities_sum_to_one(self):
        result = predict_match(self.a, self.b, neutral_site=True)
        thresholds = (0.5, 1.5, 2.5, 3.5, 4.5)
        for t in thresholds:
            over_key = f"over_{str(t).replace('.', '_')}"
            under_key = f"under_{str(t).replace('.', '_')}"
            self.assertIn(over_key, result.over_under)
            self.assertIn(under_key, result.over_under)
            self.assertAlmostEqual(
                result.over_under[over_key] + result.over_under[under_key],
                1.0,
                places=10,
                msg=f"over/under {t} should sum to 1.0",
            )

    def test_over_2_5_matches_manual_aggregation(self):
        result = predict_match(self.a, self.b, neutral_site=True)
        manual_over = sum(
            p for (a, b), p in result.score_probabilities.items() if a + b > 2.5
        )
        self.assertAlmostEqual(result.over_under["over_2_5"], manual_over, places=10)

    def test_over_under_monotonic(self):
        result = predict_match(self.a, self.b, neutral_site=True)
        self.assertGreaterEqual(
            result.over_under["over_0_5"], result.over_under["over_2_5"]
        )
        self.assertGreaterEqual(
            result.over_under["over_2_5"], result.over_under["over_4_5"]
        )


if __name__ == "__main__":
    unittest.main()
