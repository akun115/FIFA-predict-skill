import unittest
from datetime import date

from tests.test_training_dixon_coles import make_match


class TrainingEloArtifactTests(unittest.TestCase):
    def test_elo_fit_exports_cutoff_ratings_for_runtime(self):
        from oracle_training.dixon_coles import FitConfig, fit_dixon_coles

        rows = tuple(
            make_match(index, "A", "B", 2, 0) for index in range(12)
        )
        candidate = fit_dixon_coles(
            rows,
            cutoff=date(2022, 1, 1),
            version="elo-artifact-v1",
            config=FitConfig(
                decay_per_year=0.0,
                friendly_weight=1.0,
                include_elo=True,
            ),
        )

        self.assertEqual(set(candidate.model["elo_ratings"]), {"A", "B"})
        self.assertGreater(
            candidate.model["elo_ratings"]["A"],
            candidate.model["elo_ratings"]["B"],
        )
        self.assertEqual(candidate.model["elo_scale"], 400.0)


if __name__ == "__main__":
    unittest.main()
