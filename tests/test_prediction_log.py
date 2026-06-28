import json
import math
import os
import tempfile
from pathlib import Path
import unittest

from oracle_core.model import ModelConfig, TeamSnapshot, predict_match


def _artifact_dict():
    return {
        "schema_version": 1,
        "version": "national-dc-test",
        "training_cutoff": "2025-12-31",
        "intercept": math.log(1.3),
        "home_advantage": 0.15,
        "rho": -0.05,
        "elo_coefficient": 0.0,
        "attack": {"A": 0.2, "B": -0.2},
        "defense": {"A": 0.1, "B": -0.1},
        "category_effects": {"friendly": -0.05, "other": 0.0},
        "min_expected_goals": 0.1,
        "max_expected_goals": 5.0,
    }


class PredictionLogEntryTests(unittest.TestCase):
    def test_entry_roundtrips_to_jsonl_and_back(self):
        from oracle_core.logging import PredictionLogEntry

        entry = PredictionLogEntry(
            prediction_id="pred-001",
            predicted_at="2026-06-25T00:00:00Z",
            match_id="wc2026-grpC-sco-bra",
            match_id_source="provided",
            team_a="Scotland",
            team_b="Brazil",
            model_name="national-dc-v1.0.1",
            model_version="national-dc-v1.0.1",
            model_artifact_hash="abc123",
            input_context_hash="def456",
            category="world_cup",
            neutral_site=True,
            expected_goals=(0.71, 2.19),
            result_probabilities={"team_a_win": 0.10, "draw": 0.19, "team_b_win": 0.71},
            over_under={"over_2_5": 0.52, "under_2_5": 0.48},
            top_scores=(
                ((0, 2), 0.13),
                ((0, 1), 0.12),
            ),
            score_matrix_hash="ghi789",
            tournament_context_available=False,
            limitations=("test limitation",),
            source_snapshot_refs={"model": "/path/to/model"},
        )
        line = entry.to_jsonl()
        parsed = json.loads(line)
        self.assertEqual(parsed["prediction_id"], "pred-001")
        self.assertEqual(parsed["team_a"], "Scotland")
        self.assertEqual(parsed["category"], "world_cup")
        self.assertEqual(parsed["neutral_site"], True)
        self.assertEqual(parsed["match_id_source"], "provided")
        self.assertEqual(parsed["match_id"], "wc2026-grpC-sco-bra")
        self.assertEqual(parsed["over_under"]["over_2_5"], 0.52)
        self.assertIn("test limitation", parsed["limitations"])

    def test_category_recorded_world_cup(self):
        from oracle_core.logging import PredictionLogEntry

        entry = PredictionLogEntry(
            prediction_id="p", predicted_at="z", match_id="m", match_id_source="provided",
            team_a="A", team_b="B", model_name="n", model_version="v",
            model_artifact_hash="h", input_context_hash="i",
            category="world_cup", neutral_site=True,
            expected_goals=(1.0, 1.0),
            result_probabilities={"team_a_win": 0.3, "draw": 0.4, "team_b_win": 0.3},
            over_under={}, top_scores=(), score_matrix_hash="s",
            tournament_context_available=False, limitations=(),
            source_snapshot_refs={},
        )
        parsed = json.loads(entry.to_jsonl())
        self.assertEqual(parsed["category"], "world_cup")

    def test_category_default_other(self):
        from oracle_core.logging import PredictionLogEntry

        entry = PredictionLogEntry(
            prediction_id="p", predicted_at="z", match_id="", match_id_source="missing",
            team_a="A", team_b="B", model_name="n", model_version="v",
            model_artifact_hash="h", input_context_hash="i",
            category="other", neutral_site=True,
            expected_goals=(1.0, 1.0),
            result_probabilities={"team_a_win": 0.3, "draw": 0.4, "team_b_win": 0.3},
            over_under={}, top_scores=(), score_matrix_hash="s",
            tournament_context_available=False, limitations=(),
            source_snapshot_refs={},
        )
        parsed = json.loads(entry.to_jsonl())
        self.assertEqual(parsed["category"], "other")
        self.assertEqual(parsed["match_id_source"], "missing")
        self.assertEqual(parsed["match_id"], "")

    def test_match_id_source_provided_vs_missing(self):
        from oracle_core.logging import PredictionLogEntry

        base = dict(
            prediction_id="p", predicted_at="z", team_a="A", team_b="B",
            model_name="n", model_version="v", model_artifact_hash="h",
            input_context_hash="i", category="c", neutral_site=True,
            expected_goals=(1.0, 1.0),
            result_probabilities={"team_a_win": 0.3, "draw": 0.4, "team_b_win": 0.3},
            over_under={}, top_scores=(), score_matrix_hash="s",
            tournament_context_available=False, limitations=(),
            source_snapshot_refs={},
        )
        provided = PredictionLogEntry(match_id="M1", match_id_source="provided", **base)
        missing = PredictionLogEntry(match_id="", match_id_source="missing", **base)
        self.assertEqual(json.loads(provided.to_jsonl())["match_id_source"], "provided")
        self.assertEqual(json.loads(missing.to_jsonl())["match_id_source"], "missing")

    def test_over_under_and_limitations_in_entry(self):
        from oracle_core.logging import PredictionLogEntry

        entry = PredictionLogEntry(
            prediction_id="p", predicted_at="z", match_id="m", match_id_source="provided",
            team_a="A", team_b="B", model_name="n", model_version="v",
            model_artifact_hash="h", input_context_hash="i",
            category="world_cup", neutral_site=True,
            expected_goals=(0.8, 2.1),
            result_probabilities={"team_a_win": 0.10, "draw": 0.18, "team_b_win": 0.72},
            over_under={"over_2_5": 0.55, "under_2_5": 0.45},
            top_scores=(((0, 2), 0.14),),
            score_matrix_hash="s",
            tournament_context_available=False,
            limitations=("Limitation A", "Limitation B"),
            source_snapshot_refs={"key": "val"},
        )
        parsed = json.loads(entry.to_jsonl())
        self.assertEqual(parsed["over_under"]["over_2_5"], 0.55)
        self.assertEqual(parsed["over_under"]["under_2_5"], 0.45)
        self.assertEqual(parsed["limitations"], ["Limitation A", "Limitation B"])

    def test_log_entry_from_real_prediction(self):
        """Construct a PredictionLogEntry from a real engine predict_match call.
        Does NOT require MCP server import."""
        from oracle_core.logging import PredictionLogEntry, _score_hash

        team_a = TeamSnapshot("Scotland", elo=1850, attack=72, defense=68)
        team_b = TeamSnapshot("Brazil", elo=1950, attack=82, defense=75)
        pred = predict_match(team_a, team_b, neutral_site=True)

        entry = PredictionLogEntry(
            prediction_id="pred-test-real-001",
            predicted_at="2026-06-25T00:00:00Z",
            match_id="wc2026-grpC-sco-bra",
            match_id_source="provided",
            team_a=pred.team_a,
            team_b=pred.team_b,
            model_name=pred.model_version,
            model_version=pred.model_version,
            model_artifact_hash="test-hash",
            input_context_hash="test-ctx",
            category="world_cup",
            neutral_site=True,
            expected_goals=pred.expected_goals,
            result_probabilities=dict(pred.result_probabilities),
            over_under=dict(pred.over_under),
            top_scores=pred.top_scores,
            score_matrix_hash=_score_hash(pred.score_probabilities),
            tournament_context_available=False,
            limitations=pred.limitations,
            source_snapshot_refs={"engine": "provisional-v1"},
        )
        parsed = json.loads(entry.to_jsonl())
        self.assertEqual(parsed["category"], "world_cup")
        self.assertEqual(parsed["neutral_site"], True)
        self.assertEqual(parsed["match_id_source"], "provided")
        self.assertIn("over_2_5", parsed["over_under"])
        self.assertIn("under_2_5", parsed["over_under"])
        self.assertAlmostEqual(
            parsed["over_under"]["over_2_5"] + parsed["over_under"]["under_2_5"],
            1.0, places=10,
        )
        self.assertEqual(len(parsed["limitations"]), len(pred.limitations))


class PredictionLoggerWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_creates_file_and_appends(self):
        from oracle_core.logging import PredictionLogEntry, PredictionLogger

        logger = PredictionLogger(self.tmpdir)
        entry = PredictionLogEntry(
            prediction_id="pred-test-001",
            predicted_at="2026-06-25T00:00:00Z",
            match_id="test-match",
            match_id_source="provided",
            team_a="A",
            team_b="B",
            model_name="test",
            model_version="test-v1",
            model_artifact_hash="h1",
            input_context_hash="h2",
            category="world_cup",
            neutral_site=True,
            expected_goals=(1.0, 2.0),
            result_probabilities={"team_a_win": 0.4, "draw": 0.3, "team_b_win": 0.3},
            over_under={"over_2_5": 0.5, "under_2_5": 0.5},
            top_scores=(((1, 2), 0.1),),
            score_matrix_hash="h3",
            tournament_context_available=False,
            limitations=(),
            source_snapshot_refs={},
        )
        logger.write(entry)
        log_files = list(Path(self.tmpdir).glob("predictions-*.jsonl"))
        self.assertEqual(len(log_files), 1)
        lines = log_files[0].read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["prediction_id"], "pred-test-001")
        self.assertEqual(parsed["category"], "world_cup")

    def test_write_is_idempotent_append(self):
        from oracle_core.logging import PredictionLogEntry, PredictionLogger

        logger = PredictionLogger(self.tmpdir)
        base = dict(
            predicted_at="2026-01-01T00:00:00Z", match_id_source="provided",
            team_a="X", team_b="Y", model_name="m", model_version="v",
            model_artifact_hash="h", input_context_hash="i",
            category="c", neutral_site=True,
            expected_goals=(1.0, 1.0),
            result_probabilities={"team_a_win": 0.3, "draw": 0.4, "team_b_win": 0.3},
            over_under={"over_2_5": 0.5, "under_2_5": 0.5},
            top_scores=(((1, 1), 0.1),),
            score_matrix_hash="s", tournament_context_available=False,
            limitations=(), source_snapshot_refs={},
        )
        entry_a = PredictionLogEntry(prediction_id="a", match_id="ma", **base)
        entry_b = PredictionLogEntry(prediction_id="b", match_id="mb", **base)
        logger.write(entry_a)
        logger.write(entry_b)
        log_files = list(Path(self.tmpdir).glob("predictions-*.jsonl"))
        lines = log_files[0].read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 2)
        ids = [json.loads(line)["prediction_id"] for line in lines]
        self.assertEqual(ids, ["a", "b"])

    def test_mcp_predict_match_tool_writes_log(self):
        from tests.test_mcp_server import load_server

        module = load_server()
        os.environ["WORLD_CUP_ORACLE_LOG_DIR"] = self.tmpdir
        try:
            result_json = module.predict_match_tool(
                team_a="Scotland",
                team_b="Brazil",
                neutral_site=True,
                category="world_cup",
            )
            result = json.loads(result_json)
            self.assertIn("result_probabilities", result)
            self.assertIn("over_under", result)
        finally:
            os.environ.pop("WORLD_CUP_ORACLE_LOG_DIR", None)

        log_files = list(Path(self.tmpdir).glob("predictions-*.jsonl"))
        self.assertEqual(len(log_files), 1, f"No log files found in {self.tmpdir}")
        lines = log_files[0].read_text(encoding="utf-8").strip().split("\n")
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["team_a"], "Scotland")
        self.assertEqual(parsed["team_b"], "Brazil")
        self.assertEqual(parsed["category"], "world_cup")
        self.assertEqual(parsed["neutral_site"], True)
        self.assertEqual(parsed["match_id_source"], "missing")
        self.assertIn("score_matrix_hash", parsed)
        self.assertIn("model_artifact_hash", parsed)


if __name__ == "__main__":
    unittest.main()
