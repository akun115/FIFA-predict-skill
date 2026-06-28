import unittest

from oracle_core.scoring import score_prediction, summarize_calibration


class ScoringTests(unittest.TestCase):
    def test_perfect_prediction_has_zero_scores(self):
        scores = score_prediction(
            {"team_a_win": 1.0, "draw": 0.0, "team_b_win": 0.0},
            "team_a_win",
        )
        self.assertEqual(scores["brier"], 0.0)
        self.assertEqual(scores["rps"], 0.0)
        self.assertAlmostEqual(scores["log_loss"], 0.0)

    def test_invalid_probabilities_are_rejected(self):
        with self.assertRaises(ValueError):
            score_prediction(
                {"team_a_win": 0.8, "draw": 0.3, "team_b_win": -0.1},
                "draw",
            )

    def test_calibration_summary_reports_small_sample(self):
        rows = [
            {
                "probabilities": {
                    "team_a_win": 0.6,
                    "draw": 0.2,
                    "team_b_win": 0.2,
                },
                "actual_result": "team_a_win",
            }
        ]
        summary = summarize_calibration(rows)
        self.assertEqual(summary["sample_size"], 1)
        self.assertEqual(summary["status"], "insufficient_data")
        self.assertAlmostEqual(summary["mean_scores"]["brier"], 0.24)

    def test_thirty_predictions_are_report_only(self):
        rows = [
            {
                "probabilities": {
                    "team_a_win": 0.5,
                    "draw": 0.3,
                    "team_b_win": 0.2,
                },
                "actual_result": "draw",
            }
            for _ in range(30)
        ]
        summary = summarize_calibration(rows)
        self.assertEqual(summary["status"], "report_only")
        self.assertEqual(summary["sample_size"], 30)
        self.assertIn("calibration_bins", summary)
        self.assertNotIn("new_weights", summary)


if __name__ == "__main__":
    unittest.main()
