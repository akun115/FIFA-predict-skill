import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_model_server():
    path = ROOT / "mcp-server" / "model_server.py"
    spec = importlib.util.spec_from_file_location("oracle_model_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ModelLabMCPTests(unittest.TestCase):
    def test_cli_has_required_commands(self):
        from oracle_training.cli import build_parser

        parser = build_parser()
        self.assertEqual(
            parser.parse_args(["ingest", "--as-of", "2026-06-21"]).command,
            "ingest",
        )
        self.assertEqual(
            parser.parse_args(
                [
                    "backtest",
                    "--as-of",
                    "2026-06-21",
                    "--first-test-year",
                    "2010",
                ]
            ).command,
            "backtest",
        )
        self.assertEqual(
            parser.parse_args(
                [
                    "train",
                    "--as-of",
                    "2026-06-21",
                    "--version",
                    "candidate-v1",
                ]
            ).command,
            "train",
        )
        self.assertEqual(
            parser.parse_args(["status", "--version", "candidate-v1"]).command,
            "status",
        )
        self.assertTrue(
            parser.parse_args(
                [
                    "promote",
                    "--version",
                    "candidate-v1",
                    "--confirm",
                ]
            ).confirm
        )
        with self.assertRaises(SystemExit):
            parser.parse_args(["status", "--source", "unused"])

    def test_model_server_handlers_exist_and_status_is_structured(self):
        module = load_model_server()
        for name in (
            "model_status_tool",
            "train_model_tool",
            "backtest_model_tool",
            "promote_model_tool",
        ):
            self.assertTrue(callable(getattr(module, name)), name)
        with tempfile.TemporaryDirectory() as directory:
            payload = json.loads(module.model_status_tool(models_root=directory))
        self.assertEqual(payload["status"], "no_promoted_model")

    def test_promotion_requires_confirmation(self):
        module = load_model_server()
        with tempfile.TemporaryDirectory() as directory:
            payload = json.loads(
                module.promote_model_tool(
                    "missing", confirm=False, models_root=directory
                )
            )
        self.assertEqual(payload["status"], "refused")


if __name__ == "__main__":
    unittest.main()
