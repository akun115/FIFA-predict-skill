import gzip
import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path


def write_snapshot(root, cutoff, digest):
    match = {
        "date": "2022-01-01",
        "home_team": "A",
        "away_team": "B",
        "home_score": 1,
        "away_score": 0,
        "tournament": "Friendly",
        "neutral": True,
        "category": "friendly",
        "source_row": 2,
        "source_id": f"row-{digest}",
    }
    payload = json.dumps(
        [match], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    normalized_sha256 = hashlib.sha256(payload).hexdigest()
    path = root / "snapshots" / f"snapshot-{cutoff}-{normalized_sha256[:12]}"
    path.mkdir(parents=True)
    (path / "matches.json.gz").write_bytes(
        gzip.compress(payload, mtime=0)
    )
    (path / "data-manifest.json").write_text(
        json.dumps(
            {
                "as_of": cutoff,
                "normalized_sha256": normalized_sha256,
                "source_url": "https://example.test/results.csv",
            }
        ),
        encoding="utf-8",
    )
    return path


class SnapshotPipelineTests(unittest.TestCase):
    def test_latest_snapshot_never_crosses_requested_cutoff(self):
        from oracle_training.pipeline import resolve_snapshot

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            earlier = write_snapshot(root, "2025-12-31", "a" * 64)
            write_snapshot(root, "2026-06-21", "b" * 64)

            resolved = resolve_snapshot(
                "latest", training_root=root, as_of=date(2025, 12, 31)
            )

            self.assertEqual(resolved, earlier)

    def test_explicit_snapshot_after_cutoff_is_rejected(self):
        from oracle_training.pipeline import resolve_snapshot

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            later = write_snapshot(root, "2026-06-21", "b" * 64)

            with self.assertRaisesRegex(ValueError, "later than requested cutoff"):
                resolve_snapshot(
                    str(later), training_root=root, as_of=date(2025, 12, 31)
                )

    def test_load_snapshot_reconstructs_typed_matches(self):
        from oracle_training.pipeline import load_snapshot
        from oracle_training.types import TournamentCategory

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = write_snapshot(root, "2025-12-31", "a" * 64)

            matches, manifest = load_snapshot(snapshot)

            self.assertEqual(matches[0].category, TournamentCategory.FRIENDLY)
            self.assertEqual(matches[0].date, date(2022, 1, 1))
            self.assertEqual(len(manifest["normalized_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()


