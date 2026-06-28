import unittest
from datetime import date

from tests.test_training_pipeline import matches


class TrainingBreakdownTests(unittest.TestCase):
    def test_backtest_reports_year_and_category_breakdowns(self):
        from oracle_training.pipeline import backtest_matches

        report = backtest_matches(
            matches(), as_of=date(2012, 12, 31), first_test_year=2010
        )

        self.assertEqual(set(report["by_year"]), {"2010", "2011", "2012"})
        self.assertEqual(set(report["by_category"]), {"friendly"})
        self.assertEqual(
            set(report["by_year"]["2010"]),
            {"mean", "elo", "dixon_coles", "dixon_coles_elo"},
        )
        self.assertEqual(report["by_year"]["2010"]["mean"]["sample_count"], 3)
        self.assertEqual(
            report["by_category"]["friendly"]["mean"]["sample_count"], 9
        )


if __name__ == "__main__":
    unittest.main()
