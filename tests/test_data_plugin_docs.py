import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


class DataPluginDocumentationTests(unittest.TestCase):
    def test_maintenance_skill_has_guardrails_and_tools(self):
        path = ROOT / "skills" / "football-data-maintenance" / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        metadata = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(metadata["name"], "football-data-maintenance")
        for term in (
            "provider_status",
            "sync_match_context",
            "cache_status",
            "fresh",
            "cached",
            "stale",
            "partial",
            "blocked",
        ):
            self.assertIn(term, text)
        self.assertTrue("不得编造" in text or "Never invent" in text)
        self.assertNotIn("current model remains provisional", text.lower())

    def test_environment_example_has_no_values(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("FOOTBALL_DATA_ORG_TOKEN=\n", text)
        self.assertIn("WORLD_CUP_ORACLE_CACHE_MB=500", text)
        self.assertNotIn("secret-value", text)

    def test_manifest_version_describes_data_hub_and_model_lab(self):
        manifest = json.loads(
            (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["version"], "2.2.0")
        description = manifest["description"].lower()
        self.assertIn("data", description)
        self.assertIn("model", description)
        self.assertNotIn("calibrated", description)


if __name__ == "__main__":
    unittest.main()
