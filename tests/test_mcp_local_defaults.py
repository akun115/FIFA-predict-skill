import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class MCPLocalDefaultTests(unittest.TestCase):
    def test_both_servers_share_plugin_local_state(self):
        config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        expected = {
            "WORLD_CUP_ORACLE_MODELS": "${CLAUDE_PLUGIN_ROOT}/.local/models",
            "WORLD_CUP_ORACLE_TRAINING_DATA": "${CLAUDE_PLUGIN_ROOT}/.local/training",
            "WORLD_CUP_ORACLE_DB": "${CLAUDE_PLUGIN_ROOT}/.local/football-data.sqlite3",
        }
        for server in config["mcpServers"].values():
            self.assertEqual(server.get("env"), expected)


if __name__ == "__main__":
    unittest.main()
