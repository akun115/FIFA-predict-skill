import json
import unittest
from datetime import datetime, timezone
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures"


class FixtureClient:
    def __init__(self, filename):
        self.payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
        self.calls = []

    def get_json(self, url, *, headers=None):
        self.calls.append((url, headers or {}))
        return self.payload


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 21, tzinfo=timezone.utc)

    def test_openfootball_normalizes_date_only_result(self):
        from football_data.providers.openfootball import OpenFootballProvider

        client = FixtureClient("openfootball_matches.json")
        provider = OpenFootballProvider(client, clock=lambda: self.now)
        records = provider.get_matches("PL", "2025")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual((record.home_team, record.away_team), ("Team A", "Team B"))
        self.assertEqual((record.home_score, record.away_score), (2, 1))
        self.assertEqual(record.kickoff.hour, 12)
        self.assertIn("date_only_kickoff", record.provenance.warnings)
        self.assertEqual(record.provenance.observed_at.hour, 23)

    def test_football_data_org_requires_token_before_http(self):
        from football_data.providers.base import ProviderConfigurationError
        from football_data.providers.football_data_org import FootballDataOrgProvider

        client = FixtureClient("football_data_org_matches.json")
        provider = FootballDataOrgProvider(client, token="", clock=lambda: self.now)
        with self.assertRaises(ProviderConfigurationError):
            provider.get_matches("PL", "2025")
        self.assertEqual(client.calls, [])

    def test_football_data_org_normalizes_v4_match(self):
        from football_data.providers.football_data_org import FootballDataOrgProvider

        client = FixtureClient("football_data_org_matches.json")
        provider = FootballDataOrgProvider(client, token="secret", clock=lambda: self.now)
        record = provider.get_matches("PL", "2025")[0]
        self.assertEqual(record.match_id, "football-data.org:12345")
        self.assertEqual(record.kickoff.tzinfo, timezone.utc)
        self.assertEqual(record.provenance.observed_at.hour, 17)
        self.assertNotIn("secret", repr(record.to_dict()))
        self.assertEqual(client.calls[0][1]["X-Auth-Token"], "secret")

    def test_schema_error_rejects_whole_response(self):
        from football_data.providers.base import ProviderSchemaError
        from football_data.providers.football_data_org import FootballDataOrgProvider

        client = FixtureClient("football_data_org_matches.json")
        client.payload["matches"][0].pop("utcDate")
        provider = FootballDataOrgProvider(client, token="secret", clock=lambda: self.now)
        with self.assertRaises(ProviderSchemaError):
            provider.get_matches("PL", "2025")


if __name__ == "__main__":
    unittest.main()
