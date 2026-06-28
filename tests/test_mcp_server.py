import importlib.util
import json
import unittest
from pathlib import Path


def load_server():
    path = Path(__file__).parents[1] / "mcp-server" / "server.py"
    spec = importlib.util.spec_from_file_location("oracle_mcp_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPServerTests(unittest.TestCase):
    def test_server_imports_with_fastmcp(self):
        module = load_server()
        self.assertEqual(module.mcp.name, "world-cup-oracle")
        self.assertTrue(callable(module.predict_match_tool))

    def test_prediction_tool_calls_deterministic_core(self):
        module = load_server()
        first = json.loads(module.predict_match_tool("Brazil", "Mexico", neutral_site=True))
        second = json.loads(module.predict_match_tool("Brazil", "Mexico", neutral_site=True))

        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(first["result_probabilities"].values()), 1.0)
        self.assertEqual(first["model_status"], "provisional")
        self.assertIn("data_quality", first)


if __name__ == "__main__":
    unittest.main()
