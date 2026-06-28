import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class MainSkillFittedStatusTests(unittest.TestCase):
    def test_skill_distinguishes_fitted_and_provisional_runtime(self):
        text = (ROOT / "skills" / "world-cup-oracle" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("fitted", text)
        self.assertIn("provisional", text)
        self.assertIn("category", text)
        self.assertIn("current.json", text)
        self.assertNotIn("默认模型版本为 `provisional-v1`", text)


if __name__ == "__main__":
    unittest.main()

