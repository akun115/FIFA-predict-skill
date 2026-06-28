import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


class PluginStructureTests(unittest.TestCase):
    def test_manifest_and_mcp_config_are_valid(self):
        manifest = json.loads(
            (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        mcp = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "world-cup-oracle")
        self.assertNotIn("4 skills", manifest["description"])
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", json.dumps(mcp))

    def test_every_agent_has_valid_frontmatter(self):
        agents = sorted((ROOT / "agents").glob("*.md"))
        self.assertEqual(len(agents), 6)
        for path in agents:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), path.name)
            frontmatter = yaml.safe_load(text.split("---", 2)[1])
            self.assertTrue(frontmatter.get("name"), path.name)
            self.assertTrue(frontmatter.get("description"), path.name)
            self.assertEqual(frontmatter.get("model"), "inherit", path.name)
            self.assertIn("Write", frontmatter.get("disallowedTools", ""), path.name)

    def test_oracle_requires_code_generated_probabilities(self):
        text = (ROOT / "agents" / "oracle-agent.md").read_text(encoding="utf-8")
        for term in ("predict_match", "不得自行编造", "手算", "修改任何概率"):
            self.assertIn(term, text)

    def test_duplicate_server_requirements_and_unused_calibration_wrapper_are_absent(self):
        self.assertFalse((ROOT / "mcp-server" / "requirements.txt").exists())
        self.assertFalse(
            (ROOT / "mcp-server" / "tools" / "calibrate_weights.py").exists()
        )


if __name__ == "__main__":
    unittest.main()
