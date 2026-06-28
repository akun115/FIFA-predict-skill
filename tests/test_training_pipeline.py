import unittest
from datetime import date

from oracle_training.types import HistoricalMatch, TournamentCategory


def matches():
    rows = []
    source_row = 1
    for year in range(2002, 2013):
        for month, home, away, score in (
            (3, "A", "B", (2, 0)),
            (6, "B", "C", (1, 1)),
            (9, "C", "A", (0, 1)),
        ):
            rows.append(
                HistoricalMatch(
                    date(year, month, 1), home, away, score[0], score[1],
                    "Friendly", True, TournamentCategory.FRIENDLY,
                    source_row, f"{year}:{month}",
                )
            )
            source_row += 1
    return tuple(rows)


class TrainingPipelineTests(unittest.TestCase):
    def test_backtest_reports_all_required_models(self):
        from oracle_training.pipeline import backtest_matches

        report = backtest_matches(
            matches(), as_of=date(2012, 12, 31), first_test_year=2010
        )
        self.assertEqual(
            set(report["models"]),
            {"mean", "elo", "dixon_coles", "dixon_coles_elo"},
        )
        self.assertEqual(report["fold_count"], 3)
        self.assertTrue(
            all(
                fold["training_end"] < f"{fold['test_year']}-01-01"
                for fold in report["folds"]
            )
        )
        self.assertIn("gates", report)

    def test_dixon_coles_elo_is_not_an_alias_of_dixon_coles(self):
        from oracle_training.pipeline import backtest_matches

        report = backtest_matches(
            matches(), as_of=date(2012, 12, 31), first_test_year=2010
        )

        self.assertNotEqual(
            report["models"]["dixon_coles"],
            report["models"]["dixon_coles_elo"],
        )


if __name__ == "__main__":
    unittest.main()
