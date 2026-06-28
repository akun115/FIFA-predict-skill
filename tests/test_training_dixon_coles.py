import math
import unittest
from datetime import date, timedelta

from oracle_training.types import HistoricalMatch, TournamentCategory


def make_match(index, home, away, home_score, away_score):
    day = date(2020, 1, 1) + timedelta(days=index)
    return HistoricalMatch(
        day, home, away, home_score, away_score, "Friendly", True,
        TournamentCategory.FRIENDLY, index + 1, f"m:{index}",
    )


class DixonColesTrainingTests(unittest.TestCase):
    def test_time_weight_decays_and_friendly_multiplier_is_separate(self):
        from oracle_training.dixon_coles import match_weight

        cutoff = date(2022, 1, 1)
        recent = match_weight(
            make_match(700, "A", "B", 1, 0), cutoff,
            decay_per_year=0.5, friendly_weight=0.4,
        )
        old = match_weight(
            make_match(0, "A", "B", 1, 0), cutoff,
            decay_per_year=0.5, friendly_weight=0.4,
        )
        self.assertGreater(recent, old)
        self.assertLessEqual(recent, 0.4)

    def test_synthetic_fit_recovers_strength_direction(self):
        from oracle_training.dixon_coles import FitConfig, fit_dixon_coles

        matches = []
        teams = ("A", "B", "C", "D")
        index = 0
        for _ in range(6):
            for opponent in teams[1:]:
                matches.append(make_match(index, "A", opponent, 3, 0))
                index += 1
            for opponent in teams[1:3]:
                matches.append(make_match(index, opponent, "D", 2, 0))
                index += 1
        candidate = fit_dixon_coles(
            tuple(matches),
            cutoff=date(2022, 1, 1),
            version="synthetic-v1",
            config=FitConfig(decay_per_year=0.0, friendly_weight=1.0, l2=0.2),
        )
        self.assertTrue(candidate.converged)
        self.assertTrue(math.isfinite(candidate.objective))
        self.assertGreater(candidate.model["attack"]["A"], candidate.model["attack"]["D"])
        self.assertGreater(candidate.model["defense"]["A"], candidate.model["defense"]["D"])
        self.assertAlmostEqual(sum(candidate.model["attack"].values()), 0.0, places=7)
        self.assertAlmostEqual(sum(candidate.model["defense"].values()), 0.0, places=7)

    def test_include_elo_fits_a_real_coefficient(self):
        from oracle_training.dixon_coles import FitConfig, fit_dixon_coles

        matches = []
        for index in range(12):
            matches.append(make_match(index, "A", "B", 2, 0))
        for index in range(12, 24):
            matches.append(make_match(index, "B", "A", 2, 0))

        candidate = fit_dixon_coles(
            tuple(matches),
            cutoff=date(2022, 1, 1),
            version="synthetic-elo-v1",
            config=FitConfig(
                decay_per_year=0.0,
                friendly_weight=1.0,
                l2=0.2,
                include_elo=True,
            ),
        )

        self.assertGreater(abs(candidate.model["elo_coefficient"]), 1e-4)


if __name__ == "__main__":
    unittest.main()
