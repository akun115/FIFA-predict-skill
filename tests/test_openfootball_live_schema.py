import unittest
from datetime import datetime, timezone


class Client:
    def get_json(self, url, *, headers=None):
        return {
            "matches": [
                {
                    "round": "Matchday 1",
                    "date": "2025-08-16",
                    "time": "12:30",
                    "team1": "Aston Villa FC",
                    "team2": "Newcastle United FC",
                    "score": [0, 0],
                }
            ]
        }


class OpenFootballLiveSchemaTests(unittest.TestCase):
    def test_list_score_and_explicit_time_are_supported(self):
        from football_data.providers.openfootball import OpenFootballProvider

        provider = OpenFootballProvider(
            Client(), clock=lambda: datetime(2026, 6, 21, tzinfo=timezone.utc)
        )
        record = provider.get_matches("PL", "2025")[0]
        self.assertEqual((record.home_score, record.away_score), (0, 0))
        self.assertEqual((record.kickoff.hour, record.kickoff.minute), (12, 30))
        self.assertNotIn("date_only_kickoff", record.provenance.warnings)


if __name__ == "__main__":
    unittest.main()
