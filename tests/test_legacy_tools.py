import sys
import tempfile
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).parents[1] / "mcp-server"
sys.path.insert(0, str(MCP_ROOT))

from tools.query_kb import query_kb
from tools.update_post_match import update_post_match


class LegacyToolTests(unittest.TestCase):
    def test_query_invalid_layer_returns_structured_error(self):
        result = query_kb("team", "Brazil", layer="L9")
        self.assertEqual(result["error"], "invalid_layer")

    def test_update_wrapper_accepts_injected_knowledge_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = update_post_match(
                match_id="m1",
                date="2026-06-21",
                stage="group",
                home_team="A",
                away_team="B",
                score=[1, 0],
                knowledge_root=tmp,
                neutral_site=True,
            )
            self.assertEqual(result["status"], "recorded")


if __name__ == "__main__":
    unittest.main()
