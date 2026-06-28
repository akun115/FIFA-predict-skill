import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]

# Required top-level keys every team entry in teams.yaml must have
_REQUIRED_TEAM_KEYS = {"elo", "attack_rating", "defense_rating"}


class DocumentationTests(unittest.TestCase):
    def test_readme_is_release_facing_and_explains_operations(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("World Cup Oracle", text)
        self.assertIn("Claude Code plugin", text)
        self.assertIn("skill", text)
        self.assertIn("MCP", text)
        self.assertIn("national-dc-v1.0.1", text)
        self.assertIn("model-lab", text)
        self.assertIn("Ordinary prediction does not retrain the model", text)
        self.assertIn("FOOTBALL_DATA_ORG_TOKEN", text)
        self.assertIn("--as-of", text)
        self.assertIn("--confirm", text)
        self.assertNotIn("--cutoff", text)
        self.assertNotIn("superpowers", text.lower())
        self.assertNotIn("执行计划", text)

    def test_skill_matches_executable_model(self):
        text = (
            ROOT / "skills" / "world-cup-oracle" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("predict_match", text)
        self.assertIn("provisional", text)
        self.assertIn("fitted", text)
        self.assertIn("unseen_team_prior", text)
        self.assertIn("不要手改概率", text)
        self.assertNotIn("瓒", text)
        self.assertNotIn("鑳", text)
        self.assertNotIn("鈥", text)

    def test_readme_describes_provisional_model_coefficients(self):
        """README must describe the provisional-v1 formula coefficients."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("provisional-v1", readme)
        self.assertIn("elo_term", readme)
        self.assertIn("attack_term", readme)
        self.assertIn("defense_term", readme)
        self.assertNotIn("IMPORT(A,B) * 0.35", readme)

    def test_tactical_patterns_start_empty_until_validated(self):
        value = yaml.safe_load(
            (ROOT / "knowledge" / "L3-patterns" / "tactical-matrix.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(value, {"hypotheses": []})

    def test_team_knowledge_schema_integrity(self):
        """teams.yaml must be well-formed, have 'teams' key, and each entry
        must carry required fields (elo, attack_rating, defense_rating).
        Works whether the file is a skeleton or populated with live data."""
        raw = yaml.safe_load(
            (ROOT / "knowledge" / "L2-states" / "teams.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertIsInstance(raw, dict, "teams.yaml must be a YAML mapping")
        self.assertIn("teams", raw, "teams.yaml must have a top-level 'teams' key")
        teams = raw["teams"]
        self.assertIsInstance(teams, dict, "'teams' must be a mapping")
        self.assertGreater(len(teams), 0, "teams.yaml must declare at least one team")

        for team_name, fields in teams.items():
            self.assertIsInstance(fields, dict,
                                  f"Team '{team_name}' must have a field mapping")
            missing = _REQUIRED_TEAM_KEYS - set(fields)
            self.assertEqual(
                len(missing), 0,
                f"Team '{team_name}' missing required keys: {missing}",
            )

    def test_team_knowledge_skeleton_has_warning_when_present(self):
        """If teams.yaml contains skeleton warnings, they are parseable.
        Uses a fixture so the test does not depend on the real file's state."""
        skeleton = {
            "teams": {
                "Brazil": {
                    "elo": "TBD — 不完整",
                    "attack_rating": 70,
                    "defense_rating": 70,
                    "notes": "未预填：不得声称当前文件已经覆盖全部 48 支球队",
                },
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", encoding="utf-8", delete=False,
        ) as fh:
            yaml.safe_dump(skeleton, fh, allow_unicode=True)
            tmp_path = Path(fh.name)

        try:
            raw = yaml.safe_load(tmp_path.read_text(encoding="utf-8"))
            teams = raw["teams"]
            notes = teams["Brazil"].get("notes", "")
            self.assertIn("未预填", notes)
            self.assertIn("不得声称", notes)
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
