import unittest
from datetime import date

from oracle_training.types import HistoricalMatch, TournamentCategory


def match(day, home, away, score, *, neutral=False, category=TournamentCategory.FRIENDLY):
    return HistoricalMatch(
        day, home, away, score[0], score[1], category.value, neutral,
        category, 1, f"{day}:{home}:{away}",
    )


class EloTests(unittest.TestCase):
    def test_ratings_are_captured_before_each_update(self):
        from oracle_training.elo import build_pre_match_elo

        matches = (
            match(date(2020, 1, 1), "A", "B", (2, 0)),
            match(date(2020, 2, 1), "A", "B", (1, 1)),
        )
        rows = build_pre_match_elo(matches, initial_rating=1500, k_factor=20)
        self.assertEqual((rows[0].home_elo, rows[0].away_elo), (1500, 1500))
        self.assertGreater(rows[1].home_elo, 1500)
        self.assertLess(rows[1].away_elo, 1500)

    def test_neutral_match_has_no_home_advantage_and_probabilities_normalize(self):
        from oracle_training.elo import build_pre_match_elo

        row = build_pre_match_elo(
            (match(date(2020, 1, 1), "A", "B", (1, 0), neutral=True),),
            home_advantage=100,
        )[0]
        self.assertAlmostEqual(row.probabilities["team_a_win"], row.probabilities["team_b_win"])
        self.assertAlmostEqual(sum(row.probabilities.values()), 1.0)

    def test_input_must_be_chronological(self):
        from oracle_training.elo import build_pre_match_elo

        matches = (
            match(date(2020, 2, 1), "A", "B", (1, 0)),
            match(date(2020, 1, 1), "A", "B", (1, 0)),
        )
        with self.assertRaisesRegex(ValueError, "chronological"):
            build_pre_match_elo(matches)


if __name__ == "__main__":
    unittest.main()
