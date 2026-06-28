import unittest
from datetime import date, timedelta

from oracle_training.types import HistoricalMatch, TournamentCategory


class ManyTeamOptimizerTests(unittest.TestCase):
    def test_many_team_fit_does_not_false_converge_at_initial_point(self):
        from oracle_training.dixon_coles import FitConfig, fit_dixon_coles

        teams = [f"T{index:03d}" for index in range(80)]
        rows = []
        source_row = 1
        for round_index in range(3):
            for index, home in enumerate(teams):
                away = teams[(index + 1) % len(teams)]
                rows.append(HistoricalMatch(
                    date(2020, 1, 1) + timedelta(days=source_row),
                    home,
                    away,
                    3 if index % 7 == 0 else index % 2,
                    0 if index % 5 else 2,
                    "Friendly",
                    True,
                    TournamentCategory.FRIENDLY,
                    source_row,
                    f"many:{source_row}",
                ))
                source_row += 1

        candidate = fit_dixon_coles(
            tuple(rows),
            cutoff=date(2022, 1, 1),
            version="many-team-v1",
            config=FitConfig(decay_per_year=0.0, friendly_weight=1.0),
        )

        self.assertGreater(candidate.model["optimizer"]["iterations"], 1)
        self.assertGreater(
            max(candidate.model["attack"].values())
            - min(candidate.model["attack"].values()),
            0.01,
        )


if __name__ == "__main__":
    unittest.main()
