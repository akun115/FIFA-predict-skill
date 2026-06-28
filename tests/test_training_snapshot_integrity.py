import json
import tempfile
import unittest
from datetime import date
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "international_results_sample.csv"


class SnapshotIntegrityTests(unittest.TestCase):
    def test_load_snapshot_rejects_normalized_hash_mismatch(self):
        from oracle_training.ingest import ingest_csv, write_snapshot
        from oracle_training.pipeline import load_snapshot

        result = ingest_csv(
            FIXTURE.read_bytes(),
            as_of=date(2026, 6, 21),
            source_url="https://example.test/results.csv",
        )
        with tempfile.TemporaryDirectory() as directory:
            snapshot = write_snapshot(result, Path(directory))
            manifest_path = snapshot / "data-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["normalized_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "normalized hash mismatch"):
                load_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()
