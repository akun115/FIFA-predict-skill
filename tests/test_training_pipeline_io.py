import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from oracle_training.ingest import IngestionResult, write_snapshot
from oracle_training.types import DataManifest
from tests.test_training_pipeline import matches


def normalized_sha256():
    payload = json.dumps(
        [match.to_dict() for match in matches()],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def manifest():
    return DataManifest(
        source_url="https://example.test/results.csv",
        source_sha256="1" * 64,
        normalized_sha256=normalized_sha256(),
        as_of="2012-12-31",
        source_rows=len(matches()),
        accepted_rows=len(matches()),
        rejections={},
        min_date="2002-03-01",
        max_date="2012-09-01",
        team_count=3,
        taxonomy_version="test-v1",
    )


class TrainingPipelineIOTests(unittest.TestCase):
    def test_backtest_windows_have_distinct_reports_and_latest_is_used_for_training(self):
        from oracle_training.pipeline import backtest_from_snapshot, train_from_snapshot

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            training_root = root / "training"
            models_root = root / "models"
            write_snapshot(
                IngestionResult(matches(), manifest()),
                training_root / "snapshots",
            )

            earlier = backtest_from_snapshot(
                snapshot="latest",
                as_of="2012-12-31",
                first_test_year=2010,
                training_root=str(training_root),
                models_root=str(models_root),
            )
            latest = backtest_from_snapshot(
                snapshot="latest",
                as_of="2012-12-31",
                first_test_year=2011,
                training_root=str(training_root),
                models_root=str(models_root),
            )
            trained = train_from_snapshot(
                snapshot="latest",
                as_of="2012-12-31",
                backtest_report="latest",
                version="candidate-latest",
                training_root=str(training_root),
                models_root=str(models_root),
            )

            self.assertNotEqual(earlier["report_path"], latest["report_path"])
            self.assertEqual(latest["first_test_year"], 2011)
            saved_report = json.loads(
                (Path(trained["artifact"]) / "backtest-report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(saved_report["first_test_year"], 2011)

    def test_backtest_then_train_writes_immutable_candidate(self):
        from oracle_training.pipeline import backtest_from_snapshot, train_from_snapshot

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            training_root = root / "training"
            models_root = root / "models"
            write_snapshot(
                IngestionResult(matches(), manifest()),
                training_root / "snapshots",
            )

            report = backtest_from_snapshot(
                snapshot="latest",
                as_of="2012-12-31",
                first_test_year=2010,
                training_root=str(training_root),
                models_root=str(models_root),
            )
            trained = train_from_snapshot(
                snapshot="latest",
                as_of="2012-12-31",
                backtest_report="latest",
                version="candidate-v1",
                training_root=str(training_root),
                models_root=str(models_root),
            )

            self.assertTrue(Path(report["report_path"]).is_file())
            self.assertEqual(trained["status"], "candidate")
            artifact = Path(trained["artifact"])
            self.assertTrue((artifact / "model.json").is_file())
            self.assertEqual(
                json.loads((artifact / "data-manifest.json").read_text())[
                    "normalized_sha256"
                ],
                normalized_sha256(),
            )
            self.assertFalse((models_root / "current.json").exists())


if __name__ == "__main__":
    unittest.main()
