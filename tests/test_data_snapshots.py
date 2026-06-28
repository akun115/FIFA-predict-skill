import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        from football_data.snapshots import SnapshotStore

        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "hub.sqlite3"
        self.store = SnapshotStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_quality_precedence_and_missing_fields(self):
        from football_data.domain import DataState
        from football_data.quality import assess_quality

        report = assess_quality(
            required={"fixture", "lineup"}, available={"fixture"}, as_of=datetime.now(timezone.utc)
        )
        self.assertEqual(report.state, DataState.PARTIAL)
        self.assertEqual(report.missing, ("lineup",))

    def test_future_observation_blocks_required_field(self):
        from football_data.domain import DataState
        from football_data.quality import assess_quality

        cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
        report = assess_quality(
            required={"lineup"}, available={"lineup"}, as_of=cutoff,
            observed_at={"lineup": cutoff + timedelta(minutes=1)},
        )
        self.assertEqual(report.state, DataState.BLOCKED)
        self.assertIn("lineup observed after cutoff", report.blocked_reasons)

    def test_snapshot_is_redacted_idempotent_and_immutable(self):
        from football_data.quality import assess_quality
        from football_data.snapshots import SnapshotConflictError

        report = assess_quality(
            required={"fixture"}, available={"fixture"}, as_of=datetime.now(timezone.utc)
        )
        snapshot_id = self.store.record(
            "match-context", {"api_key": "secret", "team": "Brazil"}, report
        )
        self.assertEqual(
            self.store.load(snapshot_id)["payload"]["api_key"], "[redacted]"
        )
        self.assertEqual(
            self.store.record(
                "match-context", {"api_key": "different", "team": "Brazil"}, report
            ),
            snapshot_id,
        )
        with self.assertRaises(SnapshotConflictError):
            self.store.record_with_id(
                snapshot_id, "match-context", {"team": "Mexico"}, report
            )


if __name__ == "__main__":
    unittest.main()
