from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from football_data.domain import DataState, MatchRecord, Provenance
from football_data.providers.base import (
    Capability,
    ProviderDescriptor,
    ProviderUnavailableError,
)


class FakeProvider:
    descriptor = ProviderDescriptor(
        "fake", frozenset({Capability.RESULTS, Capability.FIXTURES}), False, "https://example.test"
    )

    def __init__(self, now):
        self.now = now
        self.calls = 0
        self.fail = False

    def get_matches(self, competition, season):
        self.calls += 1
        if self.fail:
            raise ProviderUnavailableError("offline")
        return (
            MatchRecord(
                "fake:1", competition, self.now, "Team A", "Team B",
                Provenance("fake", "1", self.now, self.now),
            ),
        )


class DataServiceTests(unittest.TestCase):
    def setUp(self):
        from football_data.cache import SQLiteResponseCache
        from football_data.entities import EntityRegistry
        from football_data.service import FootballDataHub
        from football_data.snapshots import SnapshotStore

        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "hub.sqlite3"
        self.now = datetime(2026, 6, 21, tzinfo=timezone.utc)
        self.provider = FakeProvider(self.now)
        self.hub = FootballDataHub(
            cache=SQLiteResponseCache(self.path, max_bytes=1024 * 1024),
            registry=EntityRegistry(self.path),
            snapshots=SnapshotStore(self.path),
            providers=[self.provider],
            cache_ttl_seconds=60,
            clock=lambda: self.now,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_remote_then_fresh_cache(self):
        first = self.hub.sync_matches("PL", "2025", as_of=self.now)
        second = self.hub.sync_matches("PL", "2025", as_of=self.now)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(first.quality.state, DataState.FRESH)
        self.assertEqual(second.quality.state, DataState.CACHED)
        self.assertTrue(first.snapshot_id)

    def test_provider_failure_can_use_explicit_stale_cache(self):
        self.hub.sync_matches("PL", "2025", as_of=self.now)
        self.provider.fail = True
        later = self.now + timedelta(seconds=61)
        self.hub.clock = lambda: later
        result = self.hub.sync_matches(
            "PL", "2025", as_of=later, allow_stale=True
        )
        self.assertEqual(result.quality.state, DataState.STALE)
        self.assertEqual(len(result.records), 1)
        self.assertIn("fake: unavailable", result.quality.provider_errors)

    def test_provider_status_has_no_credentials(self):
        status = self.hub.provider_status()
        self.assertEqual(status[0]["name"], "fake")
        self.assertTrue(status[0]["enabled"])

    def test_cache_timestamp_uses_retrieval_clock_not_historical_cutoff(self):
        cutoff = self.now - timedelta(days=30)

        self.hub.sync_matches("PL", "2025", as_of=cutoff)

        with closing(sqlite3.connect(self.path)) as connection:
            created_at = connection.execute(
                "SELECT created_at FROM cache_entries"
            ).fetchone()[0]
        self.assertEqual(created_at, self.now.timestamp())

    def test_results_observed_after_cutoff_are_excluded_and_reported(self):
        cutoff = self.now - timedelta(days=1)

        result = self.hub.sync_matches("PL", "2025", as_of=cutoff)

        self.assertEqual(result.records, ())
        self.assertEqual(result.quality.state, DataState.BLOCKED)
        self.assertIn("matches observed after cutoff", result.quality.blocked_reasons)


if __name__ == "__main__":
    unittest.main()
