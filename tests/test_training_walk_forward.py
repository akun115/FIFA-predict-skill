import unittest
from datetime import date

from oracle_training.types import HistoricalMatch, TournamentCategory


def match(year, index=1):
    return HistoricalMatch(
        date(year, 6, min(index, 28)), f"A{index}", f"B{index}", 1, 0,
        "Friendly", True, TournamentCategory.FRIENDLY, index, f"{year}:{index}",
    )


class WalkForwardTests(unittest.TestCase):
    def test_fold_training_is_strictly_before_test(self):
        from oracle_training.walk_forward import annual_folds

        matches = tuple(match(year) for year in range(2002, 2023))
        folds = annual_folds(matches, first_test_year=2010, as_of=date(2022, 12, 31))
        self.assertEqual(folds[0].test_year, 2010)
        self.assertEqual(folds[-1].test_year, 2022)
        for fold in folds:
            self.assertLess(max(item.date for item in fold.training), min(item.date for item in fold.test))

    def test_in_progress_year_is_partial_and_cut_off(self):
        from oracle_training.walk_forward import annual_folds

        matches = (match(2009), match(2026, 1), match(2026, 25))
        folds = annual_folds(matches, first_test_year=2026, as_of=date(2026, 6, 21))
        self.assertTrue(folds[0].partial)
        self.assertEqual(len(folds[0].test), 1)

    def test_proper_scores_for_perfect_prediction(self):
        from oracle_training.metrics import score_1x2

        result = score_1x2(
            {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0},
            "team_a_win",
        )
        self.assertAlmostEqual(result["brier"], 0.0)
        self.assertAlmostEqual(result["rps"], 0.0)
        self.assertLess(result["log_loss"], 1e-10)


if __name__ == "__main__":
    unittest.main()
