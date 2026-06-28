import math
import unittest


def artifact():
    return {
        "schema_version": 1,
        "version": "elo-default-v1",
        "training_cutoff": "2026-06-21",
        "intercept": math.log(1.2),
        "home_advantage": 0.0,
        "rho": 0.0,
        "elo_coefficient": 0.5,
        "elo_ratings": {"A": 1700.0, "B": 1300.0},
        "elo_scale": 400.0,
        "attack": {"A": 0.0, "B": 0.0},
        "defense": {"A": 0.0, "B": 0.0},
        "category_effects": {"other": 0.0},
        "min_expected_goals": 0.1,
        "max_expected_goals": 5.0,
    }


class FittedModelEloDefaultTests(unittest.TestCase):
    def test_omitted_elo_difference_uses_artifact_ratings(self):
        from oracle_core.fitted import FittedNationalModel

        model = FittedNationalModel.from_dict(artifact())
        automatic = model.predict(
            "A", "B", neutral_site=True, category="other"
        )
        disabled = model.predict(
            "A", "B", neutral_site=True, category="other", elo_difference=0.0
        )

        self.assertGreater(
            automatic.expected_goals[0], disabled.expected_goals[0]
        )
        self.assertLess(
            automatic.expected_goals[1], disabled.expected_goals[1]
        )


if __name__ == "__main__":
    unittest.main()
