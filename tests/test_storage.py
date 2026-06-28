import tempfile
import unittest
from pathlib import Path

from oracle_core.storage import KnowledgeStore


class StorageTests(unittest.TestCase):
    def test_duplicate_result_is_idempotent_and_elo_is_zero_sum(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore.initialize(
                Path(tmp), teams={"A": {"elo": 1600}, "B": {"elo": 1500}}
            )
            first = store.record_result(
                "m1", "2026-06-21", "group", "A", "B", [2, 1], neutral_site=True
            )
            second = store.record_result(
                "m1", "2026-06-21", "group", "A", "B", [2, 1], neutral_site=True
            )
            teams = store.load_teams()

            self.assertEqual(first["status"], "recorded")
            self.assertEqual(second["status"], "already_recorded")
            self.assertAlmostEqual(
                (teams["A"]["elo"] - 1600) + (teams["B"]["elo"] - 1500),
                0.0,
                places=8,
            )
            self.assertEqual(len(store.load_results()), 1)

    def test_conflicting_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore.initialize(Path(tmp))
            store.record_result(
                "m1", "2026-06-21", "group", "A", "B", [2, 1], neutral_site=True
            )
            with self.assertRaises(ValueError):
                store.record_result(
                    "m1", "2026-06-21", "group", "A", "B", [0, 1], neutral_site=True
                )

    def test_settlement_scores_matching_prediction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore.initialize(
                Path(tmp), teams={"A": {"elo": 1600}, "B": {"elo": 1500}}
            )
            store.record_prediction(
                "m1",
                "A",
                "B",
                {"team_a_win": 0.6, "draw": 0.2, "team_b_win": 0.2},
                [1.4, 0.9],
                {"model_version": "provisional-v1"},
            )
            store.record_result(
                "m1", "2026-06-21", "group", "A", "B", [2, 1], neutral_site=True
            )
            settled = store.load_predictions()[0]

            self.assertEqual(settled["actual_result"], "team_a_win")
            self.assertEqual(settled["actual_score"], [2, 1])
            self.assertIn("brier", settled["scores"])

    def test_prediction_replacement_requires_explicit_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore.initialize(Path(tmp))
            first = {"team_a_win": 0.5, "draw": 0.3, "team_b_win": 0.2}
            second = {"team_a_win": 0.4, "draw": 0.3, "team_b_win": 0.3}
            store.record_prediction("m1", "A", "B", first, [1.2, 0.8], {})
            with self.assertRaises(ValueError):
                store.record_prediction("m1", "A", "B", second, [1.1, 0.9], {})
            result = store.record_prediction(
                "m1", "A", "B", second, [1.1, 0.9], {}, replace=True
            )
            self.assertEqual(result["status"], "replaced")
            self.assertEqual(len(store.load_predictions()[0]["audit"]), 1)


if __name__ == "__main__":
    unittest.main()
