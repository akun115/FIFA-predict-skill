import unittest
from datetime import date

from tests.test_training_pipeline import matches


class CandidateGateTests(unittest.TestCase):
    def test_gates_are_bound_to_selected_candidate_family(self):
        from oracle_training.pipeline import backtest_matches

        report = backtest_matches(
            matches(), as_of=date(2012, 12, 31), first_test_year=2010
        )

        selected = report["candidate_model"]
        self.assertIn(selected, {"dixon_coles", "dixon_coles_elo"})
        for metric in ("log_loss", "brier", "rps"):
            expected = (
                report["models"][selected][metric]
                < report["models"]["mean"][metric]
                and report["models"][selected][metric]
                < report["models"]["elo"][metric]
            )
            self.assertEqual(report["gates"][metric], expected)


if __name__ == "__main__":
    unittest.main()
