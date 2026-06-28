import unittest
from datetime import date


class TrainingTypeTests(unittest.TestCase):
    def test_historical_match_rejects_negative_score(self):
        from oracle_training.types import HistoricalMatch, TournamentCategory

        with self.assertRaisesRegex(ValueError, "non-negative"):
            HistoricalMatch(
                date(2022, 1, 1), "A", "B", -1, 0, "Friendly", True,
                TournamentCategory.FRIENDLY, 1, "source:1",
            )

    def test_tournament_categories_have_stable_values(self):
        from oracle_training.types import TournamentCategory

        self.assertEqual(TournamentCategory.FRIENDLY.value, "friendly")
        self.assertEqual(TournamentCategory.WORLD_CUP.value, "world_cup")


if __name__ == "__main__":
    unittest.main()
