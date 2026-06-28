import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class ModelLabPluginConfigTests(unittest.TestCase):
    def test_second_mcp_server_is_auto_registered(self):
        config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server = config["mcpServers"]["world-cup-oracle-model-lab"]
        self.assertIn("model_server.py", " ".join(server["args"]))
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", json.dumps(server))

    def test_manifest_and_environment_document_model_lab(self):
        manifest = json.loads(
            (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["version"], "2.2.0")
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("WORLD_CUP_ORACLE_MODELS=\n", text)
        self.assertIn("WORLD_CUP_ORACLE_TRAINING_DATA=\n", text)


if __name__ == "__main__":
    unittest.main()
