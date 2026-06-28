"""End-to-end smoke test: get_tournament_state → predict_match → verify output + log.

Verifies the complete World Cup prediction workflow using real knowledge data
(Groups A/B/C schedule from knowledge/L1-events/schedule.yaml) and a fixture
fitted model for the fitted-path variant.

Covers:
  1. get_tournament_state(pre_match) for Scotland vs Brazil
  2. predict_match with tournament_context_json=<step 1 output>
  3. prediction_log written with tournament_context_available=true
  4. Prediction.to_dict() output contains tournament_context
  5. limitations: form/availability + tournament context not modeled
  6. result_probabilities, expected_goals, top_scores, over_under unchanged by context
  7. prediction_log tournament_context_available=false when no context passed
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
import unittest

from tests.test_mcp_server import load_server


# ---------------------------------------------------------------------------
# Reusable fitted-model fixture — includes Scotland for clean "fitted" status
# ---------------------------------------------------------------------------

def _fitted_model_fixture() -> dict:
    return {
        "schema_version": 1,
        "version": "smoke-test-v1",
        "training_cutoff": "2026-06-25",
        "intercept": math.log(1.2),
        "home_advantage": 0.1,
        "rho": -0.02,
        "elo_coefficient": 0.3,
        "elo_ratings": {
            "Brazil": 1950.0,
            "Scotland": 1650.0,
        },
        "elo_scale": 400.0,
        "attack": {
            "Brazil": 0.4,
            "Scotland": -0.1,
        },
        "defense": {
            "Brazil": 0.3,
            "Scotland": -0.1,
        },
        "category_effects": {"other": 0.0, "world_cup": 0.1},
        "min_expected_goals": 0.1,
        "max_expected_goals": 5.0,
    }


# ---------------------------------------------------------------------------
# Smoke test class
# ---------------------------------------------------------------------------

class ForecastWorkflowSmokeTests(unittest.TestCase):
    """Complete pipeline: tournament_state → predict_match → output + log verification."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_server()
        cls.log_tmp = tempfile.TemporaryDirectory()
        os.environ["WORLD_CUP_ORACLE_LOG_DIR"] = cls.log_tmp.name

    @classmethod
    def tearDownClass(cls):
        cls.log_tmp.cleanup()
        os.environ.pop("WORLD_CUP_ORACLE_LOG_DIR", None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_pre_match_state(self) -> str:
        """Call get_tournament_state for Scotland vs Brazil in pre_match mode."""
        return self.module.get_tournament_state_tool(
            match_id="wc2026-grpC-sco-bra",
            state_mode="pre_match",
        )

    def _predict(self, **kwargs) -> dict:
        """Call predict_match for Scotland vs Brazil (world_cup, neutral)."""
        return json.loads(self.module.predict_match_tool(
            "Scotland", "Brazil",
            neutral_site=True,
            category="world_cup",
            **kwargs
        ))

    def _last_log_entry(self) -> dict | None:
        """Return the most recent prediction log entry as a dict."""
        log_dir = Path(self.log_tmp.name)
        files = sorted(log_dir.glob("predictions-*.jsonl"))
        if not files:
            return None
        lines = files[-1].read_text(encoding="utf-8").strip().split("\n")
        return json.loads(lines[-1])

    # ------------------------------------------------------------------
    # Step 1: get_tournament_state(pre_match)
    # ------------------------------------------------------------------

    def test_01_get_tournament_state_pre_match_standings(self):
        """Pre-match standings exclude target + simultaneous matches."""
        state = json.loads(self._get_pre_match_state())

        self.assertEqual(state["state_mode"], "pre_match")
        self.assertEqual(state["match_id"], "wc2026-grpC-sco-bra")

        # Both matchday-3 Group C matches excluded
        self.assertIn("wc2026-grpC-sco-bra", state["excluded_matches"])
        self.assertIn("wc2026-grpC-mar-hai", state["excluded_matches"])
        self.assertEqual(len(state["excluded_matches"]), 2)

        # Standings from 4 completed matches (matchdays 1+2)
        table = state["group_standings_before_match"]
        self.assertEqual(table["group"], "C")
        rows = {r["team"]: r for r in table["table"]}
        self.assertEqual(rows["Brazil"]["played"], 2)
        self.assertEqual(rows["Brazil"]["points"], 4)
        self.assertEqual(rows["Morocco"]["played"], 2)
        self.assertEqual(rows["Morocco"]["points"], 4)
        self.assertEqual(rows["Scotland"]["played"], 2)
        self.assertEqual(rows["Scotland"]["points"], 3)
        self.assertEqual(rows["Haiti"]["played"], 2)
        self.assertEqual(rows["Haiti"]["points"], 0)

    def test_02_incentives_scotland_must_win_brazil_draw_sufficient(self):
        """Scotland (3rd, 3pts) must win; Brazil (1st, 4pts) draws suffices for top2."""
        state = json.loads(self._get_pre_match_state())

        self.assertEqual(
            state["team_a_incentive"]["primary_incentive"],
            "must_win_for_top2",
        )
        self.assertEqual(
            state["team_b_incentive"]["primary_incentive"],
            "draw_sufficient_for_top2",
        )

    # ------------------------------------------------------------------
    # Step 2: predict_match with tournament_context_json
    # ------------------------------------------------------------------

    def test_03_predict_includes_tournament_context_field(self):
        """predict_match output includes non-null tournament_context when JSON passed."""
        state_json = self._get_pre_match_state()
        result = self._predict(tournament_context_json=state_json)

        tc = result["tournament_context"]
        self.assertIsNotNone(tc)
        self.assertEqual(tc["state_mode"], "pre_match")
        self.assertIsNotNone(tc.get("team_a_incentive"))
        self.assertIsNotNone(tc.get("team_b_incentive"))

    def test_04_no_context_returns_null_tournament_context(self):
        """Without tournament_context_json, tournament_context is null."""
        result = self._predict()
        self.assertIsNone(result["tournament_context"])

    # ------------------------------------------------------------------
    # Step 3: prediction_log auto-written
    # ------------------------------------------------------------------

    def test_05_prediction_log_written_with_context_true(self):
        """Prediction log entry records tournament_context_available=True."""
        state_json = self._get_pre_match_state()
        self._predict(tournament_context_json=state_json)

        entry = self._last_log_entry()
        self.assertIsNotNone(entry)
        self.assertTrue(entry["tournament_context_available"])
        self.assertEqual(entry["team_a"], "Scotland")
        self.assertEqual(entry["team_b"], "Brazil")
        self.assertEqual(entry["category"], "world_cup")
        self.assertEqual(entry["neutral_site"], True)
        # Verify key probability fields present
        self.assertIn("result_probabilities", entry)
        self.assertIn("over_under", entry)
        self.assertIn("score_matrix_hash", entry)

    def test_06_prediction_log_without_context_records_false(self):
        """Prediction log entry records tournament_context_available=False."""
        self._predict()  # no context

        entry = self._last_log_entry()
        self.assertIsNotNone(entry)
        self.assertFalse(entry["tournament_context_available"])

    # ------------------------------------------------------------------
    # Step 4: Prediction.to_dict() contains tournament_context
    # ------------------------------------------------------------------

    def test_07_to_dict_includes_tournament_context(self):
        """Prediction serialized via to_dict() carries tournament_context."""
        state_json = self._get_pre_match_state()
        result = self._predict(tournament_context_json=state_json)

        self.assertIn("tournament_context", result)
        tc = result["tournament_context"]
        self.assertEqual(tc["state_mode"], "pre_match")
        self.assertEqual(
            tc["team_a_incentive"]["primary_incentive"],
            "must_win_for_top2",
        )

    # ------------------------------------------------------------------
    # Step 5: limitations contain both required messages
    # ------------------------------------------------------------------

    def test_08_provisional_path_baseline_limitation(self):
        """Provisional path includes baseline disclaimer about backtesting."""
        result = self._predict()
        joined = " ".join(result["limitations"])
        self.assertIn("Tactical and psychological", joined)

    def test_09_limitations_tournament_context_note(self):
        """Limitations include 'not quantitatively modeled' when context passed."""
        state_json = self._get_pre_match_state()
        result = self._predict(tournament_context_json=state_json)
        joined = " ".join(result["limitations"])
        self.assertIn("not quantitatively modeled", joined)

    def test_10_both_notes_fitted_path_with_context(self):
        """Fitted path: BOTH form/availability AND tournament context notes present."""
        from oracle_training.registry import ModelRegistry

        with tempfile.TemporaryDirectory() as models_dir:
            registry = ModelRegistry(Path(models_dir))
            registry.save_candidate(
                _fitted_model_fixture(),
                {"normalized_sha256": "d" * 64},
                {"gates": {"integrity": True, "log_loss": True}},
            )
            registry.promote("smoke-test-v1", confirm=True)

            state_json = self._get_pre_match_state()
            result = json.loads(self.module.predict_match_tool(
                "Scotland", "Brazil",
                neutral_site=True,
                category="world_cup",
                models_root=models_dir,
                tournament_context_json=state_json,
            ))

        joined = " ".join(result["limitations"])
        self.assertIn("form/availability", joined)
        self.assertIn("not quantitatively modeled", joined)

    # ------------------------------------------------------------------
    # Step 6: result_probabilities, expected_goals, top_scores, over_under unchanged
    # ------------------------------------------------------------------

    def test_11_all_probabilities_unchanged_with_vs_without_context(self):
        """Tournament context does NOT modify any probability output."""
        without = self._predict()
        state_json = self._get_pre_match_state()
        with_ctx = self._predict(tournament_context_json=state_json)

        self.assertEqual(
            without["result_probabilities"],
            with_ctx["result_probabilities"],
        )
        self.assertEqual(without["expected_goals"], with_ctx["expected_goals"])
        self.assertEqual(without["over_under"], with_ctx["over_under"])
        self.assertEqual(without["top_scores"], with_ctx["top_scores"])

    # ------------------------------------------------------------------
    # Step 7 (bonus): full workflow with fitted path
    # ------------------------------------------------------------------

    def test_12_fitted_path_with_tournament_context(self):
        """Fitted model path accepts tournament_context and returns fitted status."""
        from oracle_training.registry import ModelRegistry

        with tempfile.TemporaryDirectory() as models_dir:
            registry = ModelRegistry(Path(models_dir))
            registry.save_candidate(
                _fitted_model_fixture(),
                {"normalized_sha256": "c" * 64},
                {"gates": {"integrity": True, "log_loss": True}},
            )
            registry.promote("smoke-test-v1", confirm=True)

            result = json.loads(self.module.predict_match_tool(
                "Scotland", "Brazil",
                neutral_site=True,
                category="world_cup",
                models_root=models_dir,
                tournament_context_json=self._get_pre_match_state(),
            ))

        self.assertEqual(result["model_status"], "fitted")
        self.assertIsNotNone(result["tournament_context"])
        tc = result["tournament_context"]
        self.assertEqual(tc["state_mode"], "pre_match")
        self.assertEqual(
            tc["team_a_incentive"]["primary_incentive"],
            "must_win_for_top2",
        )
        # Fitted path still emits both limitation notes
        joined = " ".join(result["limitations"])
        self.assertIn("form/availability", joined)
        self.assertIn("not quantitatively modeled", joined)

    # ------------------------------------------------------------------
    # Sanity checks
    # ------------------------------------------------------------------

    def test_13_all_output_fields_present(self):
        """All expected top-level fields are present in predict_match output."""
        state_json = self._get_pre_match_state()
        result = self._predict(tournament_context_json=state_json)

        expected_fields = [
            "team_a", "team_b", "result_probabilities", "expected_goals",
            "top_scores", "over_under", "model_status", "model_version",
            "data_quality", "assumptions", "limitations", "tournament_context",
        ]
        for field in expected_fields:
            with self.subTest(field=field):
                self.assertIn(field, result)

    def test_14_result_probabilities_sum_to_one(self):
        """Result probabilities always sum to 1.0."""
        result = self._predict()
        probs = result["result_probabilities"]
        self.assertAlmostEqual(sum(probs.values()), 1.0)

    def test_15_over_under_has_all_five_thresholds(self):
        """Over/under contains all 5 thresholds: over/under pairs for 0.5..4.5."""
        result = self._predict()
        expected_keys = {
            "over_0_5", "under_0_5",
            "over_1_5", "under_1_5",
            "over_2_5", "under_2_5",
            "over_3_5", "under_3_5",
            "over_4_5", "under_4_5",
        }
        self.assertEqual(set(result["over_under"].keys()), expected_keys)

    def test_16_tournament_state_deterministic(self):
        """Repeated calls to get_tournament_state produce identical output."""
        state1 = json.loads(self._get_pre_match_state())
        state2 = json.loads(self._get_pre_match_state())

        self.assertEqual(state1["state_mode"], state2["state_mode"])
        self.assertEqual(state1["excluded_matches"], state2["excluded_matches"])
        self.assertEqual(
            state1["team_a_incentive"]["primary_incentive"],
            state2["team_a_incentive"]["primary_incentive"],
        )
        self.assertEqual(
            state1["team_b_incentive"]["primary_incentive"],
            state2["team_b_incentive"]["primary_incentive"],
        )


if __name__ == "__main__":
    unittest.main()
