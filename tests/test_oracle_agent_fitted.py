import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class OracleAgentFittedTests(unittest.TestCase):
    def test_agent_preserves_runtime_status_and_category(self):
        text = (ROOT / "agents" / "oracle-agent.md").read_text(encoding="utf-8")

        for term in ("fitted", "provisional", "unseen_team_prior", "category"):
            self.assertIn(term, text)
        self.assertIn("不得", text)
        self.assertIn("predict_match", text)


if __name__ == "__main__":
    unittest.main()
