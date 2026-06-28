import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def load_server():
    path = Path(__file__).parents[1] / "mcp-server" / "server.py"
    spec = importlib.util.spec_from_file_location("oracle_data_mcp_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DataMCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_server()

    def test_data_handlers_exist(self):
        for name in (
            "provider_status_tool",
            "sync_match_context_tool",
            "resolve_football_entity_tool",
            "get_data_quality_tool",
            "get_prediction_snapshot_tool",
            "cache_status_tool",
            "purge_cache_tool",
        ):
            self.assertTrue(callable(getattr(self.module, name)), name)

    def test_status_works_without_token_and_redacts_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "hub.sqlite3")
            with patch.dict(
                os.environ, {"FOOTBALL_DATA_ORG_TOKEN": "secret-value"}, clear=True
            ):
                payload = json.loads(self.module.provider_status_tool(database))
            self.assertNotIn("secret-value", repr(payload))
            self.assertEqual(payload["settings"]["max_cache_bytes"], 500 * 1024 * 1024)
            self.assertEqual(
                {item["name"] for item in payload["providers"]},
                {"openfootball", "football-data.org"},
            )

    def test_cache_tools_only_change_evictable_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "hub.sqlite3")
            before = json.loads(self.module.cache_status_tool(database))
            purged = json.loads(self.module.purge_cache_tool(database_path=database))
            self.assertEqual(before["entry_count"], 0)
            self.assertEqual(purged["removed"], 0)


if __name__ == "__main__":
    unittest.main()
