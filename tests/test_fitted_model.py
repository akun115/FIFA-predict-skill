import math
import unittest


def artifact():
    return {
        "schema_version": 1,
        "version": "national-dc-test",
        "training_cutoff": "2025-12-31",
        "intercept": math.log(1.3),
        "home_advantage": 0.15,
        "rho": -0.05,
        "elo_coefficient": 0.0,
        "attack": {"A": 0.2, "B": -0.2},
        "defense": {"A": 0.1, "B": -0.1},
        "category_effects": {"friendly": -0.05, "other": 0.0},
        "min_expected_goals": 0.1,
        "max_expected_goals": 5.0,
    }


class FittedModelTests(unittest.TestCase):
    def test_same_team_prediction_is_rejected(self):
        from oracle_core.fitted import FittedNationalModel

        with self.assertRaisesRegex(ValueError, "teams must differ"):
            FittedNationalModel.from_dict(artifact()).predict(
                "A", "A", neutral_site=True, category="friendly"
            )

    def test_neutral_swap_mirrors_probabilities(self):
        from oracle_core.fitted import FittedNationalModel

        model = FittedNationalModel.from_dict(artifact())
        first = model.predict("A", "B", neutral_site=True, category="friendly")
        mirrored = model.predict("B", "A", neutral_site=True, category="friendly")
        self.assertAlmostEqual(
            first.result_probabilities["team_a_win"],
            mirrored.result_probabilities["team_b_win"],
        )
        self.assertAlmostEqual(sum(first.result_probabilities.values()), 1.0)
        self.assertEqual(first.model_status, "fitted")

    def test_unseen_team_uses_global_prior_with_status(self):
        from oracle_core.fitted import FittedNationalModel

        result = FittedNationalModel.from_dict(artifact()).predict(
            "A", "Unknown", neutral_site=True, category="other"
        )
        self.assertEqual(result.model_status, "unseen_team_prior")
        self.assertIn("Unknown", result.limitations[0])

    def test_nonfinite_artifact_is_rejected(self):
        from oracle_core.fitted import FittedNationalModel

        bad = artifact()
        bad["intercept"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            FittedNationalModel.from_dict(bad)

    def test_runtime_module_has_no_training_imports(self):
        from pathlib import Path
        import oracle_core.fitted

        text = Path(oracle_core.fitted.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import numpy", text)
        self.assertNotIn("import scipy", text)
        self.assertNotIn("oracle_training", text)

    def test_fitted_predict_mentions_form_availability_limitation(self):
        from oracle_core.fitted import FittedNationalModel

        result = FittedNationalModel.from_dict(artifact()).predict(
            "A", "B", neutral_site=True, category="friendly"
        )
        joined_limits = " ".join(result.limitations)
        self.assertIn("form", joined_limits)
        self.assertIn("availability", joined_limits)
        self.assertEqual(result.model_status, "fitted")

    def test_fitted_over_under_present_and_sums_to_one(self):
        from oracle_core.fitted import FittedNationalModel

        result = FittedNationalModel.from_dict(artifact()).predict(
            "A", "B", neutral_site=True, category="friendly"
        )
        self.assertIn("over_2_5", result.over_under)
        self.assertIn("under_2_5", result.over_under)
        self.assertAlmostEqual(
            result.over_under["over_2_5"] + result.over_under["under_2_5"],
            1.0,
            places=10,
        )


if __name__ == "__main__":
    unittest.main()
