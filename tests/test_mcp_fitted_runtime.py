import json
import math
import tempfile
import unittest

from tests.test_mcp_server import load_server


def model():
    return {
        "schema_version": 1,
        "version": "promoted-v1",
        "training_cutoff": "2026-06-21",
        "intercept": math.log(1.2),
        "home_advantage": 0.1,
        "rho": -0.02,
        "elo_coefficient": 0.3,
        "elo_ratings": {"Brazil": 1800.0, "Mexico": 1600.0},
        "elo_scale": 400.0,
        "attack": {"Brazil": 0.3, "Mexico": -0.3},
        "defense": {"Brazil": 0.2, "Mexico": -0.2},
        "category_effects": {"other": 0.0, "world_cup": 0.1},
        "min_expected_goals": 0.1,
        "max_expected_goals": 5.0,
    }


class MCPFittedRuntimeTests(unittest.TestCase):
    def test_prediction_uses_promoted_fitted_model(self):
        from oracle_training.registry import ModelRegistry

        with tempfile.TemporaryDirectory() as directory:
            registry = ModelRegistry(directory)
            registry.save_candidate(
                model(),
                {"normalized_sha256": "a" * 64},
                {"gates": {"integrity": True, "log_loss": True}},
            )
            registry.promote("promoted-v1", confirm=True)
            module = load_server()

            payload = json.loads(module.predict_match_tool(
                "Brazil",
                "Mexico",
                neutral_site=True,
                models_root=directory,
                category="world_cup",
            ))

        self.assertEqual(payload["model_version"], "promoted-v1")
        self.assertEqual(payload["model_status"], "fitted")
        self.assertEqual(payload["data_quality"]["status"], "fitted_artifact")


class TournamentContextInjectionTests(unittest.TestCase):
    """Verify tournament_context is injected without changing probabilities."""

    def _predict(self, module, **kwargs):
        return json.loads(module.predict_match_tool(
            "Brazil", "Mexico", neutral_site=True, **kwargs
        ))

    def _pre_match_context(self) -> str:
        return json.dumps({
            "state_mode": "pre_match",
            "state_timestamp_utc": "2026-06-26T03:00:00Z",
            "match_id": "test-match",
            "team_a_incentive": {
                "primary_incentive": "must_win_for_top2",
                "intensity": 1.0,
            },
            "team_b_incentive": {
                "primary_incentive": "draw_sufficient_for_top2",
                "intensity": 0.3,
            },
            "excluded_matches": ["simul-1"],
            "simultaneous_group_matches": [
                {"match_id": "simul-1", "team_a": "X", "team_b": "Y"},
            ],
        })

    def test_no_context_returns_null_tournament_context(self):
        module = load_server()
        result = self._predict(module)
        self.assertIsNone(result.get("tournament_context"))

    def test_pre_match_context_injected(self):
        module = load_server()
        result = self._predict(module, tournament_context_json=self._pre_match_context())
        self.assertIsNotNone(result["tournament_context"])
        self.assertEqual(result["tournament_context"]["state_mode"], "pre_match")
        self.assertEqual(
            result["tournament_context"]["team_a_incentive"]["primary_incentive"],
            "must_win_for_top2",
        )

    def test_pre_match_context_adds_neutral_limitation(self):
        module = load_server()
        result = self._predict(module, tournament_context_json=self._pre_match_context())
        joined = " ".join(result["limitations"])
        self.assertIn("not quantitatively modeled", joined)

    def test_current_context_adds_state_mode_warning(self):
        context = json.dumps({
            "state_mode": "current",
            "state_timestamp_utc": "2026-06-26T05:00:00Z",
            "match_id": "test-match",
            "team_a_incentive": {"primary_incentive": "already_qualified_rotation_risk"},
            "team_b_incentive": {"primary_incentive": "third_place_dependent"},
            "excluded_matches": [],
            "simultaneous_group_matches": [],
        })
        module = load_server()
        result = self._predict(module, tournament_context_json=context)
        joined = " ".join(result["limitations"])
        self.assertIn("not 'pre_match'", joined)

    def test_malformed_json_does_not_crash(self):
        module = load_server()
        result = self._predict(module, tournament_context_json="not valid json {{{")
        self.assertIsNone(result.get("tournament_context"))
        joined = " ".join(result["limitations"])
        self.assertIn("could not be parsed", joined)

    def test_empty_string_no_effect(self):
        module = load_server()
        result = self._predict(module, tournament_context_json="")
        self.assertIsNone(result.get("tournament_context"))

    def test_probabilities_unchanged_with_vs_without_context(self):
        import copy
        module = load_server()
        without = self._predict(module)
        with_ctx = self._predict(module, tournament_context_json=self._pre_match_context())
        self.assertEqual(
            without["result_probabilities"],
            with_ctx["result_probabilities"],
        )
        self.assertEqual(without["expected_goals"], with_ctx["expected_goals"])
        self.assertEqual(without["over_under"], with_ctx["over_under"])
        self.assertEqual(
            without["top_scores"],
            with_ctx["top_scores"],
        )

    def test_provisional_path_also_accepts_context(self):
        module = load_server()
        result = json.loads(module.predict_match_tool(
            "Brazil", "Mexico",
            neutral_site=True,
            models_root="/nonexistent",
            tournament_context_json=self._pre_match_context(),
        ))
        self.assertIsNotNone(result["tournament_context"])
        self.assertEqual(result["model_status"], "provisional")
        joined = " ".join(result["limitations"])
        self.assertIn("not quantitatively modeled", joined)


if __name__ == "__main__":
    unittest.main()
