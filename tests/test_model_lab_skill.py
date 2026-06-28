import unittest
from pathlib import Path

import yaml


class ModelLabSkillTests(unittest.TestCase):
    def test_skill_has_required_tools_and_guardrails(self):
        path = (
            Path(__file__).parents[1]
            / "skills"
            / "oracle-model-lab"
            / "SKILL.md"
        )
        text = path.read_text(encoding="utf-8")
        metadata = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(metadata["name"], "oracle-model-lab")
        for term in ("model_status", "train_model", "backtest_model", "promote_model", "as_of"):
            self.assertIn(term, text)
        self.assertIn("不得在普通预测中触发训练", text)
        self.assertIn("不得自动发布", text)


if __name__ == "__main__":
    unittest.main()
