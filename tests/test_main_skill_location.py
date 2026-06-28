import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class MainSkillLocationTests(unittest.TestCase):
    def test_main_skill_uses_plugin_skill_directory(self):
        self.assertTrue(
            (ROOT / "skills" / "world-cup-oracle" / "SKILL.md").is_file()
        )
        self.assertFalse((ROOT / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
