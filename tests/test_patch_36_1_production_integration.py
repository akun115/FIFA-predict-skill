"""Tests for Patch 36.1 — production integration boundaries."""

import json
import os
import subprocess
import sys
import tempfile
import unittest


def _repo_root():
    return os.path.dirname(os.path.dirname(__file__))


# ==========================================================================
# Production Config Tests
# ==========================================================================


class TestProductionConfig(unittest.TestCase):
    """Test production_config module."""

    def test_default_config_offline(self):
        from oracle_core.production_config import (
            ProductionConfig, DEFAULT_OFFLINE_CONFIG,
        )
        self.assertEqual(DEFAULT_OFFLINE_CONFIG.runtime_mode, "offline")
        self.assertFalse(DEFAULT_OFFLINE_CONFIG.network_allowed)
        self.assertFalse(DEFAULT_OFFLINE_CONFIG.env_access_allowed)
        self.assertFalse(DEFAULT_OFFLINE_CONFIG.live_tests_allowed)

    def test_validate_config_accepts_valid_offline(self):
        from oracle_core.production_config import (
            DEFAULT_OFFLINE_CONFIG, validate_config,
        )
        # Should not raise
        validate_config(DEFAULT_OFFLINE_CONFIG)

    def test_validate_config_rejects_invalid_combos(self):
        from oracle_core.production_config import (
            ProductionConfig, validate_config,
        )
        # offline + network must fail
        with self.assertRaises(ValueError):
            validate_config(ProductionConfig(
                runtime_mode="offline", network_allowed=True,
            ))
        # offline + env_access must fail
        with self.assertRaises(ValueError):
            validate_config(ProductionConfig(
                runtime_mode="offline", env_access_allowed=True,
            ))

    def test_config_immutable(self):
        from oracle_core.production_config import DEFAULT_OFFLINE_CONFIG
        with self.assertRaises(Exception):
            DEFAULT_OFFLINE_CONFIG.runtime_mode = "live_opt_in"

    def test_load_config_from_env_defaults_offline(self):
        from oracle_core.production_config import load_config_from_env
        config = load_config_from_env()
        self.assertEqual(config.runtime_mode, "offline")

    def test_config_to_dict(self):
        from oracle_core.production_config import DEFAULT_OFFLINE_CONFIG
        d = DEFAULT_OFFLINE_CONFIG.to_dict()
        self.assertEqual(d["runtime_mode"], "offline")
        self.assertFalse(d["network_allowed"])


# ==========================================================================
# Production Audit Tests
# ==========================================================================


class TestProductionAudit(unittest.TestCase):
    """Test production_audit module."""

    def test_audit_probability_mutated_is_false(self):
        from oracle_core.production_audit import create_audit_record
        ar = create_audit_record(
            runtime_mode="offline", network_allowed=False, env_access_allowed=False,
        )
        self.assertFalse(ar.probability_mutated)

    def test_audit_affects_model_is_false(self):
        from oracle_core.production_audit import create_audit_record
        ar = create_audit_record(
            runtime_mode="offline", network_allowed=False, env_access_allowed=False,
        )
        self.assertFalse(ar.affects_model)

    def test_audit_cannot_override_safety_fields(self):
        from oracle_core.production_audit import create_audit_record
        ar = create_audit_record(
            runtime_mode="offline", network_allowed=False, env_access_allowed=False,
            probability_mutated=True,
            affects_model=True,
        )
        self.assertFalse(ar.probability_mutated)
        self.assertFalse(ar.affects_model)

    def test_redact_source_reference_removes_api_keys(self):
        from oracle_core.production_audit import redact_source_reference
        redacted = redact_source_reference(
            "https://api.example.com/v1?api_key=my-secret-key-12345"
        )
        self.assertNotIn("my-secret-key-12345", redacted)
        self.assertIn("redacted", redacted.lower())

    def test_audit_record_immutable(self):
        from oracle_core.production_audit import create_audit_record
        ar = create_audit_record(
            runtime_mode="offline", network_allowed=False, env_access_allowed=False,
        )
        with self.assertRaises(Exception):
            ar.probability_mutated = True

    def test_audit_to_dict(self):
        from oracle_core.production_audit import create_audit_record
        ar = create_audit_record(
            runtime_mode="offline", network_allowed=False, env_access_allowed=False,
        )
        d = ar.to_dict()
        self.assertFalse(d["probability_mutated"])
        self.assertFalse(d["affects_model"])


# ==========================================================================
# Live Provider Runtime Tests
# ==========================================================================


class TestLiveProviderRuntime(unittest.TestCase):
    """Test live_provider_runtime module."""

    def test_disabled_by_default(self):
        from oracle_core.live_provider_runtime import (
            create_live_provider, LiveProviderRequest,
        )
        adapter = create_live_provider("thesportsdb")
        self.assertIn("Disabled", type(adapter).__name__)

        resp = adapter.fetch(LiveProviderRequest(
            provider_name="thesportsdb", capability="teams",
            match_id="", team_ids=(), allow_live=False,
        ))
        self.assertFalse(resp.success)
        self.assertIn("provider_disabled", resp.gaps)

    def test_thesportsdb_remains_needs_more_info(self):
        from oracle_core.live_provider_runtime import (
            create_live_provider, LiveProviderRequest,
            TheSportsDbLiveProviderAdapter,
        )
        adapter = create_live_provider("thesportsdb", allow_live=True)
        self.assertIsInstance(adapter, TheSportsDbLiveProviderAdapter)

        resp = adapter.fetch(LiveProviderRequest(
            provider_name="thesportsdb", capability="teams",
            match_id="", team_ids=(), allow_live=True,
        ))
        self.assertFalse(resp.success)
        has_needs_more = any(
            "needs_more_info" in g or "not_opted" in g for g in resp.gaps
        )
        self.assertTrue(has_needs_more, f"Gaps should mention needs_more_info: {resp.gaps}")

    def test_unknown_provider_returns_disabled(self):
        from oracle_core.live_provider_runtime import create_live_provider
        adapter = create_live_provider("nonexistent_provider", allow_live=True)
        self.assertIn("Disabled", type(adapter).__name__)

    def test_live_provider_fails_closed_on_error(self):
        from oracle_core.live_provider_runtime import (
            DisabledLiveProviderAdapter, LiveProviderRequest,
            fetch_provider_context,
        )
        adapter = DisabledLiveProviderAdapter()
        resp = fetch_provider_context(adapter, LiveProviderRequest(
            provider_name="test", capability="teams",
            match_id="", team_ids=(), allow_live=False,
        ))
        self.assertFalse(resp.success)

    def test_no_network_in_default(self):
        import oracle_core.live_provider_runtime as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)
        self.assertNotIn("requests.get", source)


# ==========================================================================
# Odds Provider Runtime Tests
# ==========================================================================


class TestOddsProviderRuntime(unittest.TestCase):
    """Test odds_provider_runtime module."""

    def test_disabled_by_default(self):
        from oracle_core.odds_provider_runtime import (
            create_odds_provider, OddsProviderRequest,
        )
        adapter = create_odds_provider("test")
        resp = adapter.fetch(OddsProviderRequest(match_id="M1", allow_live=False))
        self.assertFalse(resp.success)
        self.assertIn("odds_provider_disabled", resp.gaps)

    def test_stub_does_not_fake_data(self):
        from oracle_core.odds_provider_runtime import (
            StubOddsProviderAdapter, OddsProviderRequest,
        )
        adapter = StubOddsProviderAdapter()
        resp = adapter.fetch(OddsProviderRequest(match_id="M1", allow_live=True))
        self.assertFalse(resp.success)
        self.assertIn("not_configured", resp.gaps[0] if resp.gaps else "")

    def test_odds_never_blend_into_probabilities(self):
        from oracle_core.odds_provider_runtime import (
            build_market_comparison_section, OddsProviderResponse, OddsMarketSnapshot,
        )
        # Successful response with odds data
        snap = OddsMarketSnapshot(
            match_id="M1", market_type="1X2",
            selections=({"label": "home", "decimal_odds": 2.0},),
            bookmaker="Test Bookmaker", captured_at="2026-06-15T12:00:00Z",
        )
        resp = OddsProviderResponse(
            provider_name="test", success=True,
            odds_data={"snapshots": [snap]},
        )
        section = build_market_comparison_section(resp)
        # The disclaimer must state that odds are not blended into model
        text = str(section)
        self.assertIn("disclaimer", str(section).lower())
        # Verify the disclaimer mentions "no blending" or "market reference"
        self.assertTrue(
            "no" in text.lower() and "blend" in text.lower()
            or "market reference" in text.lower()
        )

    def test_odds_market_snapshot_report_only(self):
        from oracle_core.odds_provider_runtime import OddsMarketSnapshot
        snap = OddsMarketSnapshot(
            match_id="M1", market_type="1X2",
            selections=({"label": "home", "decimal_odds": 2.0},),
            bookmaker="Test", captured_at="2026-06-15T12:00:00Z",
        )
        self.assertTrue(snap.report_only)
        self.assertFalse(snap.affects_model)
        # Verify __post_init__ rejects report_only=False
        with self.assertRaises(ValueError):
            OddsMarketSnapshot(
                match_id="M1", market_type="1X2",
                selections=({"label": "home", "decimal_odds": 2.0},),
                bookmaker="Test", captured_at="2026-06-15T12:00:00Z",
                report_only=False,
            )


# ==========================================================================
# Web Scout Runtime Tests
# ==========================================================================


class TestWebScoutRuntime(unittest.TestCase):
    """Test web_scout_runtime module."""

    def test_disabled_by_default(self):
        from oracle_core.web_scout_runtime import create_web_scout_runtime
        adapter = create_web_scout_runtime()
        self.assertIn("Disabled", type(adapter).__name__)

    def test_disabled_returns_gaps(self):
        from oracle_core.web_scout_runtime import (
            create_web_scout_runtime, WebScoutRuntimeRequest,
        )
        adapter = create_web_scout_runtime()
        # WebScoutRuntimeRequest requires allow_web_scout
        resp = adapter.execute(WebScoutRuntimeRequest(
            query_topics=("injuries",), match_id="M1",
            team_ids=(), allow_web_scout=False,
        ))
        self.assertFalse(resp.success)
        self.assertGreater(len(resp.gaps), 0)

    def test_evidence_always_report_only(self):
        from oracle_core.web_scout_runtime import WebScoutEvidenceItem
        from datetime import datetime, timezone
        ev = WebScoutEvidenceItem(
            title="Test", source="test", evidence_type="news",
            snippet="test", confidence="low",
            source_url_or_reference="fixture://test",
            searched_at=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(ev.report_only)
        self.assertFalse(ev.affects_model)

    def test_no_network_in_default(self):
        import oracle_core.web_scout_runtime as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)
        self.assertNotIn("requests.get", source)


# ==========================================================================
# Production Orchestrator Tests
# ==========================================================================


class TestProductionOrchestrator(unittest.TestCase):
    """Test production_orchestrator module."""

    def test_orchestrator_preserves_model_output(self):
        from oracle_core.production_orchestrator import (
            OrchestratorInput, run_production_pipeline,
        )
        mo = {
            "team_a": "TeamA", "team_b": "TeamB",
            "result_probabilities": {"team_a_win": 0.5, "draw": 0.3, "team_b_win": 0.2},
        }
        inp = OrchestratorInput(
            home_team="TeamA", away_team="TeamB",
            model_output=mo,
        )
        out = run_production_pipeline(inp)
        report = out.report_text
        # Model probabilities must appear
        self.assertIn("50.0%", report)
        self.assertIn("30.0%", report)
        self.assertIn("20.0%", report)

    def test_orchestrator_no_model_output_shows_gaps(self):
        from oracle_core.production_orchestrator import (
            OrchestratorInput, run_production_pipeline,
        )
        inp = OrchestratorInput(home_team="TeamA", away_team="TeamB")
        out = run_production_pipeline(inp)
        self.assertGreater(len(out.gaps), 0)
        self.assertGreater(len(out.caveats), 0)

    def test_orchestrator_does_not_network(self):
        from oracle_core.production_orchestrator import (
            OrchestratorInput, run_production_pipeline,
        )
        inp = OrchestratorInput(home_team="TeamA", away_team="TeamB")
        out = run_production_pipeline(inp)
        self.assertGreater(len(out.report_text), 100)
        # Orchestrator must not contain urllib or requests
        import oracle_core.production_orchestrator as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)
        self.assertNotIn("requests.get", source)

    def test_orchestrator_audit_has_safety_flags(self):
        from oracle_core.production_orchestrator import (
            OrchestratorInput, run_production_pipeline,
        )
        inp = OrchestratorInput(home_team="TeamA", away_team="TeamB")
        out = run_production_pipeline(inp)
        audit = out.audit_record
        # The audit_record is a dict; check safety fields
        if isinstance(audit, dict):
            pm = audit.get("probability_mutated")
            am = audit.get("affects_model")
            # Either absent or False — verify
            if pm is not None:
                self.assertFalse(pm)
            if am is not None:
                self.assertFalse(am)
            # Must not be True
            self.assertNotEqual(pm, True)
            self.assertNotEqual(am, True)

    def test_orchestrator_context_does_not_override(self):
        from oracle_core.production_orchestrator import (
            OrchestratorInput, run_production_pipeline,
        )
        mo = {
            "team_a": "A", "team_b": "B",
            "result_probabilities": {"team_a_win": 0.48, "draw": 0.27, "team_b_win": 0.25},
        }
        ctx = {
            "snapshot_id": "snap-test",
            "result_probabilities": {"team_a_win": 0.99},
        }
        inp = OrchestratorInput(
            home_team="A", away_team="B",
            model_output=mo, context_snapshot=ctx,
        )
        out = run_production_pipeline(inp)
        self.assertIn("48.0%", out.report_text)
        self.assertNotIn("99.0%", out.report_text)


# ==========================================================================
# Production Health Tests
# ==========================================================================


class TestProductionHealth(unittest.TestCase):
    """Test production_health module."""

    def test_healthcheck_overall_healthy(self):
        from oracle_core.production_health import run_full_healthcheck
        report = run_full_healthcheck()
        self.assertTrue(report.overall_healthy)

    def test_healthcheck_offline_mode(self):
        from oracle_core.production_health import run_full_healthcheck
        report = run_full_healthcheck()
        self.assertEqual(report.runtime_mode, "offline")

    def test_healthcheck_thesportsdb_status(self):
        from oracle_core.production_health import run_full_healthcheck
        report = run_full_healthcheck()
        self.assertEqual(report.thesportsdb_status, "needs_more_info")

    def test_healthcheck_model_boundary_intact(self):
        from oracle_core.production_health import run_full_healthcheck
        report = run_full_healthcheck()
        self.assertTrue(report.model_boundary_intact)

    def test_healthcheck_does_not_network(self):
        import oracle_core.production_health as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)

    def test_healthcheck_cli(self):
        result = subprocess.run(
            [sys.executable, "-m", "oracle_core.production_health"],
            capture_output=True, text=True, timeout=30,
            cwd=_repo_root(),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("HEALTHY", result.stdout)

    def test_healthcheck_cli_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "oracle_core.production_health", "--json"],
            capture_output=True, text=True, timeout=30,
            cwd=_repo_root(),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertTrue(data["overall_healthy"])
        self.assertEqual(data["thesportsdb_status"], "needs_more_info")


# ==========================================================================
# Deployment Templates Tests
# ==========================================================================


class TestDeploymentTemplates(unittest.TestCase):
    """Test deployment templates contain no secrets."""

    def test_env_example_no_real_keys(self):
        env_path = os.path.join(
            _repo_root(), "deploy", "env", ".env.example",
        )
        if not os.path.exists(env_path):
            self.skipTest(".env.example not found")
        with open(env_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        # Must contain placeholder indicators
        self.assertIn("your_key_here", content.lower())

    def test_dockerfile_no_secrets(self):
        dockerfile = os.path.join(
            _repo_root(), "deploy", "docker", "Dockerfile",
        )
        if not os.path.exists(dockerfile):
            self.skipTest("Dockerfile not found")
        with open(dockerfile, "r", encoding="utf-8") as fh:
            content = fh.read()
        # Must not contain hardcoded keys or tokens
        self.assertNotIn("sk-", content)

    def test_docker_compose_no_secrets(self):
        dc_path = os.path.join(
            _repo_root(), "deploy", "docker", "docker-compose.yml",
        )
        if not os.path.exists(dc_path):
            self.skipTest("docker-compose.yml not found")
        with open(dc_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn("sk-", content)


# ==========================================================================
# Global Invariant Tests
# ==========================================================================


class TestGlobalInvariants(unittest.TestCase):
    """Verify global invariants are maintained."""

    def test_default_tests_no_network(self):
        """All new modules must not import networking libraries."""
        modules = [
            "oracle_core.production_config",
            "oracle_core.production_audit",
            "oracle_core.live_provider_runtime",
            "oracle_core.odds_provider_runtime",
            "oracle_core.web_scout_runtime",
            "oracle_core.production_orchestrator",
            "oracle_core.production_health",
        ]
        import importlib, inspect
        for mod_name in modules:
            mod = importlib.import_module(mod_name)
            source = inspect.getsource(mod)
            for forbidden in ["urllib.request", "requests.get",
                              "socket.create_connection"]:
                self.assertNotIn(forbidden, source,
                                 f"{mod_name} should not import {forbidden}")

    def test_thesportsdb_needs_more_info_everywhere(self):
        """TheSportsDB provider healthcheck must report needs_more_info."""
        from oracle_core.production_health import run_full_healthcheck
        report = run_full_healthcheck()
        self.assertEqual(report.thesportsdb_status, "needs_more_info")

    def test_no_fake_data_in_providers(self):
        """Disabled/stub adapters must not fabricate data."""
        from oracle_core.live_provider_runtime import (
            DisabledLiveProviderAdapter, LiveProviderRequest,
        )
        from oracle_core.odds_provider_runtime import (
            DisabledOddsProviderAdapter, OddsProviderRequest,
        )
        from oracle_core.web_scout_runtime import (
            DisabledWebScoutRuntimeAdapter, WebScoutRuntimeRequest,
        )

        # Live provider — must not fabricate
        lp = DisabledLiveProviderAdapter()
        resp = lp.fetch(LiveProviderRequest(
            provider_name="test", capability="teams",
            match_id="", team_ids=(), allow_live=False,
        ))
        self.assertFalse(resp.success)
        self.assertTrue(resp.data is None or resp.data == {},
                        f"Disabled adapter must not fabricate data: {resp.data}")

        # Odds — must not fabricate
        op = DisabledOddsProviderAdapter()
        resp2 = op.fetch(OddsProviderRequest(match_id="M1", allow_live=False))
        self.assertFalse(resp2.success)
        self.assertIsNone(resp2.odds_data)

        # Web Scout — must not fabricate
        ws = DisabledWebScoutRuntimeAdapter()
        resp3 = ws.execute(WebScoutRuntimeRequest(
            query_topics=("injuries",), match_id="M1",
        ))
        self.assertFalse(resp3.success)
        self.assertEqual(len(resp3.evidence), 0)


if __name__ == "__main__":
    unittest.main()
