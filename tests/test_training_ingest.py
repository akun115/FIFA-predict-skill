import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "international_results_sample.csv"


class TrainingIngestTests(unittest.TestCase):
    def test_cutoff_rejections_and_hashes_are_deterministic(self):
        from oracle_training.ingest import ingest_csv

        raw = FIXTURE.read_bytes()
        result = ingest_csv(
            raw, as_of=date(2026, 6, 21), source_url="https://example.test/results.csv"
        )
        self.assertEqual(
            [match.date.isoformat() for match in result.matches],
            ["2002-01-04", "2022-12-18"],
        )
        self.assertEqual(result.manifest.rejections["before_start"], 1)
        self.assertEqual(result.manifest.rejections["future"], 1)
        self.assertEqual(result.manifest.rejections["missing_score"], 1)
        self.assertEqual(result.manifest.rejections["negative_score"], 1)
        self.assertEqual(result.manifest.rejections["duplicate"], 1)
        self.assertEqual(result.manifest.rejections["conflict"], 2)
        self.assertEqual(result.manifest.source_sha256, hashlib.sha256(raw).hexdigest())
        again = ingest_csv(
            raw, as_of=date(2026, 6, 21), source_url="https://example.test/results.csv"
        )
        self.assertEqual(result.manifest.normalized_sha256, again.manifest.normalized_sha256)

    def test_snapshot_is_compressed_and_immutable(self):
        from oracle_training.ingest import ingest_csv, write_snapshot

        result = ingest_csv(
            FIXTURE.read_bytes(),
            as_of=date(2026, 6, 21),
            source_url="https://example.test/results.csv",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = write_snapshot(result, Path(directory))
            self.assertTrue((output / "matches.json.gz").is_file())
            manifest = json.loads(
                (output / "data-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["normalized_sha256"], result.manifest.normalized_sha256)
            self.assertEqual(write_snapshot(result, Path(directory)), output)


if __name__ == "__main__":
    unittest.main()
