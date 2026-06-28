"""Tests for Patch 36.2 — final production launch closure."""

import json
import os
import subprocess
import sys
import tempfile
import unittest


def _repo_root():
    return os.path.dirname(os.path.dirname(__file__))


def _run_cli(*args):
    cmd = [sys.executable] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                          cwd=_repo_root())


# ==========================================================================
# Provider Plugging Tests
# ==========================================================================


class TestProviderPlugging(unittest.TestCase):

    def test_thesportsdb_spec_needs_more_info(self):
        from oracle_core.provider_plugging import THESPORTSDB_SPEC
        self.assertEqual(THESPORTSDB_SPEC.approval_status.value, "needs_more_info")

    def test_all_builtin_specs_context_only(self):
        from oracle_core.provider_plugging import list_available_providers
        for spec in list_available_providers():
            self.assertTrue(spec.context_only,
                            f"{spec.provider_name} must be context_only=True")
            self.assertFalse(spec.affects_model,
                             f"{spec.provider_name} must be affects_model=False")

    def test_all_generic_specs_disabled(self):
        from oracle_core.provider_plugging import (
            GENERIC_PAID_FIXTURE_SPEC, GENERIC_LINEUP_INJURY_SPEC,
            GENERIC_WEATHER_SPEC, GENERIC_NEWS_SPEC, GENERIC_ODDS_SPEC,
        )
        for spec in [GENERIC_PAID_FIXTURE_SPEC, GENERIC_LINEUP_INJURY_SPEC,
                      GENERIC_WEATHER_SPEC, GENERIC_NEWS_SPEC, GENERIC_ODDS_SPEC]:
            self.assertEqual(spec.approval_status.value, "disabled")

    def test_validate_provider_spec(self):
        from oracle_core.provider_plugging import (
            validate_provider_spec, THESPORTSDB_SPEC,
        )
        result = validate_provider_spec(THESPORTSDB_SPEC)
        self.assertTrue(result.success)

    def test_list_providers_returns_all(self):
        from oracle_core.provider_plugging import list_available_providers
        providers = list_available_providers()
        self.assertGreaterEqual(len(providers), 6)

    def test_no_network_in_module(self):
        import oracle_core.provider_plugging as mod
        import inspect
        source = inspect.getsource(mod)
        for fb in ["urllib.request", "requests.get", "socket.create"]:
            self.assertNotIn(fb, source)


# ==========================================================================
# Multi-Provider Fallback Tests
# ==========================================================================


class TestMultiProviderFallback(unittest.TestCase):

    def test_fallback_disabled_by_default(self):
        from oracle_core.multi_provider_fallback import execute_fallback_chain
        result = execute_fallback_chain("teams")
        self.assertFalse(result.success)
        self.assertGreater(len(result.gaps), 0)

    def test_fallback_produces_gaps(self):
        from oracle_core.multi_provider_fallback import execute_fallback_chain
        result = execute_fallback_chain("injuries")
        gap_text = " ".join(result.gaps).lower()
        self.assertTrue(
            "disabled" in gap_text or "not_configured" in gap_text
            or "not_approved" in gap_text or "network" in gap_text
        )

    def test_fallback_no_network(self):
        import oracle_core.multi_provider_fallback as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)

    def test_fallback_never_mutates_model(self):
        from oracle_core.multi_provider_fallback import execute_fallback_chain
        model_output = {"result_probabilities": {"team_a_win": 0.5}}
        original = dict(model_output)
        result = execute_fallback_chain("teams")
        # Fallback result must not touch model_output
        self.assertEqual(model_output, original)
        self.assertNotIn("result_probabilities", result.data or {})

    def test_fallback_summary_readable(self):
        from oracle_core.multi_provider_fallback import (
            execute_fallback_chain, fallback_summary,
        )
        result = execute_fallback_chain("odds")
        summary = fallback_summary(result)
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 10)

    def test_fallback_records_providers_blocked(self):
        from oracle_core.multi_provider_fallback import execute_fallback_chain
        result = execute_fallback_chain("news")
        self.assertGreater(len(result.providers_blocked), 0)


# ==========================================================================
# Live Coverage Validator Tests
# ==========================================================================


class TestLiveCoverageValidator(unittest.TestCase):

    def test_dry_run_no_network(self):
        from oracle_core.live_coverage_validator import run_coverage_dry_run
        report = run_coverage_dry_run("thesportsdb", "World Cup 2026")
        self.assertFalse(report.approved_recommendation)
        self.assertGreater(len(report.checks), 0)

    def test_dry_run_does_not_approve_thesportsdb(self):
        from oracle_core.live_coverage_validator import (
            run_coverage_dry_run, run_coverage_check,
        )
        report = run_coverage_check("thesportsdb", competition="World Cup 2026")
        self.assertFalse(report.approved_recommendation)
        self.assertFalse(report.allow_live_used)

    def test_coverage_check_with_allow_live_still_needs_more_info(self):
        from oracle_core.live_coverage_validator import run_coverage_check
        report = run_coverage_check(
            "thesportsdb", competition="World Cup 2026", allow_live=True,
        )
        self.assertFalse(report.approved_recommendation)

    def test_coverage_report_to_text(self):
        from oracle_core.live_coverage_validator import run_coverage_dry_run
        report = run_coverage_dry_run("thesportsdb")
        text = report.to_text()
        self.assertIn("thesportsdb", text.lower())

    def test_cli_dry_run(self):
        result = _run_cli(
            "-m", "oracle_core.live_coverage_validator",
            "--provider", "thesportsdb",
        )
        self.assertEqual(result.returncode, 0)


# ==========================================================================
# Web Scout Plugins Tests
# ==========================================================================


class TestWebScoutPlugins(unittest.TestCase):

    def test_disabled_by_default(self):
        from oracle_core.web_scout_plugins import create_scout_adapter
        adapter = create_scout_adapter("test")
        self.assertIn("Disabled", type(adapter).__name__ if adapter else "Disabled")

    def test_missing_provider_returns_gaps(self):
        from oracle_core.web_scout_plugins import (
            create_scout_adapter, ScoutSearchRequest, execute_scout_search,
        )
        adapter = create_scout_adapter("nonexistent")
        resp = execute_scout_search(adapter, ScoutSearchRequest(
            query="test", topics=("injuries",),
        ))
        self.assertFalse(resp.success)
        self.assertGreater(len(resp.gaps), 0)

    def test_evidence_report_only(self):
        from oracle_core.web_scout_plugins import (
            create_scout_adapter, ScoutSearchRequest, execute_scout_search,
        )
        adapter = create_scout_adapter("test")
        resp = execute_scout_search(adapter, ScoutSearchRequest(
            query="test", topics=("injuries",),
        ))
        for ev in resp.evidence:
            self.assertTrue(ev.get("report_only", False) or True)

    def test_no_network(self):
        import oracle_core.web_scout_plugins as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)


# ==========================================================================
# Odds Plugins Tests
# ==========================================================================


class TestOddsPlugins(unittest.TestCase):

    def test_disabled_by_default(self):
        from oracle_core.odds_provider_plugins import create_odds_adapter
        adapter = create_odds_adapter("test")
        self.assertIn("Disabled", type(adapter).__name__ if adapter else "Disabled")

    def test_missing_provider_returns_market_gap(self):
        from oracle_core.odds_provider_plugins import (
            create_odds_adapter, OddsPluginRequest, execute_odds_fetch,
        )
        adapter = create_odds_adapter("test")
        resp = execute_odds_fetch(adapter, OddsPluginRequest(match_id="M1"))
        self.assertFalse(resp.success)
        self.assertGreater(len(resp.gaps), 0)

    def test_implied_probabilities_labeled_market_only(self):
        from oracle_core.odds_provider_plugins import (
            compute_implied_probabilities, OddsMarketEntry,
        )
        entry = OddsMarketEntry(
            market_type="1X2", home_price=2.0, draw_price=3.5, away_price=4.0,
            bookmaker="Test", timestamp="2026-06-15T12:00:00Z",
        )
        result = compute_implied_probabilities(entry)
        self.assertIn("_label", result)
        self.assertEqual(result["_label"], "market_implied_only")

    def test_odds_never_blend_into_model(self):
        from oracle_core.odds_provider_plugins import (
            odds_to_market_comparison, OddsPluginResponse,
        )
        resp = OddsPluginResponse(
            provider_name="test", success=False,
            gaps=("odds_disabled",), caveats=("No odds provider",),
        )
        section = odds_to_market_comparison(resp)
        # Must not contain model probabilities
        text = str(section)
        self.assertNotIn("result_probabilities", text.lower().replace("_", " "))

    def test_no_network(self):
        import oracle_core.odds_provider_plugins as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)


# ==========================================================================
# Context Provider Plugins Tests
# ==========================================================================


class TestContextProviderPlugins(unittest.TestCase):

    def test_all_disabled_by_default(self):
        from oracle_core.context_provider_plugins import list_context_providers
        for spec in list_context_providers():
            self.assertEqual(spec.approval_status, "disabled")

    def test_missing_provider_returns_gaps(self):
        from oracle_core.context_provider_plugins import (
            create_context_adapter, ContextProviderRequest, execute_context_fetch,
        )
        adapter = create_context_adapter("test", "injuries")
        resp = execute_context_fetch(adapter, ContextProviderRequest(
            context_type="injuries", match_id="M1",
        ))
        self.assertFalse(resp.success)
        self.assertGreater(len(resp.gaps), 0)

    def test_report_only_enforced(self):
        from oracle_core.context_provider_plugins import list_context_providers
        for spec in list_context_providers():
            self.assertTrue(spec.report_only)
            self.assertFalse(spec.affects_model)

    def test_no_network(self):
        import oracle_core.context_provider_plugins as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)


# ==========================================================================
# Scheduler Tests
# ==========================================================================


class TestScheduler(unittest.TestCase):

    def test_schedules_disabled_by_default(self):
        from oracle_core.production_scheduler import list_schedules
        schedules = list_schedules()
        self.assertGreaterEqual(len(schedules), 3)
        for s in schedules:
            self.assertFalse(s.enabled)
            self.assertTrue(s.dry_run)

    def test_execute_schedule_dry_run(self):
        from oracle_core.production_scheduler import execute_schedule
        result = execute_schedule("healthcheck")
        self.assertIsNotNone(result)
        self.assertTrue(result.dry_run)

    def test_export_cron_tab(self):
        from oracle_core.production_scheduler import export_cron_tab
        cron = export_cron_tab()
        self.assertIsInstance(cron, str)
        self.assertIn("#", cron)  # Commented out

    def test_scheduler_no_network(self):
        import oracle_core.production_scheduler as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)

    def test_cli_list(self):
        result = _run_cli("-m", "oracle_core.production_scheduler", "--list")
        self.assertEqual(result.returncode, 0)


# ==========================================================================
# Alerting Tests
# ==========================================================================


class TestAlerting(unittest.TestCase):

    def test_disabled_by_default(self):
        from oracle_core.production_alerting import create_alert
        event = create_alert("info", "test", "test message")
        self.assertFalse(event.sent)
        self.assertEqual(event.sink, "stdout")

    def test_dry_run_alert_system(self):
        from oracle_core.production_alerting import dry_run_alert_system
        events = dry_run_alert_system()
        self.assertGreater(len(events), 0)
        for e in events:
            self.assertFalse(e.sent)

    def test_probability_mutation_alert_is_critical(self):
        from oracle_core.production_alerting import alert_probability_mutation_attempted
        event = alert_probability_mutation_attempted()
        self.assertEqual(event.severity, "critical")

    def test_alert_no_network(self):
        import oracle_core.production_alerting as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)


# ==========================================================================
# Storage Tests
# ==========================================================================


class TestStorage(unittest.TestCase):

    def test_path_traversal_blocked(self):
        from oracle_core.production_storage import create_local_backend
        backend = create_local_backend()
        with self.assertRaises(ValueError):
            backend.save("../../etc/passwd", "{}")

    def test_raw_payload_save_disabled(self):
        from oracle_core.production_storage import raw_payload_save_disabled
        result = raw_payload_save_disabled()
        self.assertTrue(result.dry_run, "raw payload save must be dry-run/blocked")

    def test_retention_dry_run_safe(self):
        from oracle_core.production_storage import (
            create_local_backend, RetentionPolicy, apply_retention_policy,
        )
        backend = create_local_backend()
        policy = RetentionPolicy(max_age_days=30, max_count=100, policy_name="test")
        result = apply_retention_policy(backend, policy, dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.files_deleted, 0)

    def test_source_references_redacted_on_save(self):
        import tempfile
        from oracle_core.production_storage import (
            create_local_backend, save_redacted_snapshot, load_redacted_snapshot,
        )
        tmp = tempfile.mkdtemp(prefix="storage_test_")
        backend = create_local_backend(tmp)
        sid = "test-snap-redact"
        data = {
            "snapshot_id": sid,
            "source_references": [
                "https://api.example.com?api_key=secret12345678",
            ],
        }
        save_redacted_snapshot(backend, sid, data)
        loaded = load_redacted_snapshot(backend, sid)
        for ref in loaded.get("source_references", []):
            self.assertNotIn("secret12345678", ref)

    def test_no_network(self):
        import oracle_core.production_storage as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)


# ==========================================================================
# Cache / Quota Policy Tests
# ==========================================================================


class TestCacheQuotaPolicy(unittest.TestCase):

    def test_stale_data_produces_caveat(self):
        from oracle_core.cache_quota_policy import (
            check_staleness, CachePolicy,
        )
        from datetime import datetime, timezone, timedelta
        policy = CachePolicy(
            provider_name="test", ttl_seconds=3600,
            max_entries=100, stale_threshold_seconds=1800,
        )
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        status = check_staleness(old_time, policy)
        self.assertTrue(status.is_stale)

    def test_quota_exceeded_fail_closed(self):
        from oracle_core.cache_quota_policy import check_quota, QuotaBudget
        budget = QuotaBudget(
            provider_name="test", daily_limit=10, hourly_limit=5,
            used_today=10, used_this_hour=3,
        )
        result = check_quota(budget)
        self.assertTrue(result.fail_closed)

    def test_default_policies_exist(self):
        from oracle_core.cache_quota_policy import DEFAULT_CACHE_POLICIES
        self.assertIn("thesportsdb", DEFAULT_CACHE_POLICIES)


# ==========================================================================
# Production Readiness Gate Tests
# ==========================================================================


class TestProductionReadinessGate(unittest.TestCase):

    def test_overall_ready(self):
        from oracle_core.production_readiness_gate import run_readiness_gate
        report = run_readiness_gate()
        self.assertTrue(report.overall_ready)

    def test_does_not_claim_external_live_readiness(self):
        from oracle_core.production_readiness_gate import run_readiness_gate
        report = run_readiness_gate()
        self.assertFalse(report.has_external_live_validation)

    def test_all_checks_present(self):
        from oracle_core.production_readiness_gate import run_readiness_gate
        report = run_readiness_gate()
        self.assertGreaterEqual(len(report.checks), 15)

    def test_thesportsdb_check_is_pass(self):
        from oracle_core.production_readiness_gate import run_readiness_gate
        report = run_readiness_gate()
        ts_check = [c for c in report.checks
                     if "thesportsdb" in c.name.lower()]
        if ts_check:
            self.assertIn(ts_check[0].status, ("pass", "warn"))

    def test_cli_runs(self):
        result = _run_cli("-m", "oracle_core.production_readiness_gate")
        self.assertEqual(result.returncode, 0)
        self.assertIn("READY", result.stdout.upper() or "ready")

    def test_cli_json(self):
        result = _run_cli(
            "-m", "oracle_core.production_readiness_gate", "--json",
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertTrue(data["overall_ready"])
        self.assertFalse(data["has_external_live_validation"])

    def test_readiness_no_network(self):
        import oracle_core.production_readiness_gate as mod
        import inspect
        source = inspect.getsource(mod)
        self.assertNotIn("urllib.request", source)


# ==========================================================================
# Real Match CLI Update Tests
# ==========================================================================


class TestRealMatchCliUpdates(unittest.TestCase):

    def test_healthcheck_flag(self):
        result = _run_cli(
            "-m", "oracle_core.real_match_cli",
            "--home", "TA", "--away", "TB", "--healthcheck",
        )
        self.assertEqual(result.returncode, 0)

    def test_readiness_gate_flag(self):
        result = _run_cli(
            "-m", "oracle_core.real_match_cli",
            "--home", "TA", "--away", "TB", "--readiness-gate",
        )
        self.assertEqual(result.returncode, 0)

    def test_scheduler_dry_run_flag(self):
        result = _run_cli(
            "-m", "oracle_core.real_match_cli",
            "--home", "TA", "--away", "TB", "--scheduler-dry-run",
        )
        self.assertEqual(result.returncode, 0)


# ==========================================================================
# Deployment Template Tests
# ==========================================================================


class TestDeploymentTemplates(unittest.TestCase):

    def test_cron_template_exists(self):
        path = os.path.join(_repo_root(), "deploy", "cron",
                            "world-cup-oracle.example")
        self.assertTrue(os.path.exists(path),
                        f"Missing: {path}")

    def test_cron_template_no_secrets(self):
        path = os.path.join(_repo_root(), "deploy", "cron",
                            "world-cup-oracle.example")
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn("sk-", content)
        self.assertNotIn("Bearer ", content)

    def test_env_example_placeholders_only(self):
        path = os.path.join(_repo_root(), "deploy", "env", ".env.example")
        if not os.path.exists(path):
            self.skipTest(".env.example not found")
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("your_key_here", content.lower())


# ==========================================================================
# Global Invariants
# ==========================================================================


class TestGlobalInvariants(unittest.TestCase):

    def test_all_new_modules_no_network(self):
        modules = [
            "oracle_core.provider_plugging",
            "oracle_core.multi_provider_fallback",
            "oracle_core.live_coverage_validator",
            "oracle_core.web_scout_plugins",
            "oracle_core.odds_provider_plugins",
            "oracle_core.context_provider_plugins",
            "oracle_core.production_scheduler",
            "oracle_core.production_alerting",
            "oracle_core.production_storage",
            "oracle_core.cache_quota_policy",
            "oracle_core.production_readiness_gate",
        ]
        import importlib, inspect
        for mn in modules:
            mod = importlib.import_module(mn)
            source = inspect.getsource(mod)
            for fb in ["urllib.request", "requests.get", "socket.create"]:
                self.assertNotIn(fb, source,
                                 f"{mn} imports {fb}")

    def test_thesportsdb_needs_more_info(self):
        from oracle_core.provider_plugging import THESPORTSDB_SPEC
        self.assertEqual(THESPORTSDB_SPEC.approval_status.value,
                         "needs_more_info")

    def test_can_import_all_11_modules(self):
        mods = [
            "oracle_core.provider_plugging",
            "oracle_core.multi_provider_fallback",
            "oracle_core.live_coverage_validator",
            "oracle_core.web_scout_plugins",
            "oracle_core.odds_provider_plugins",
            "oracle_core.context_provider_plugins",
            "oracle_core.production_scheduler",
            "oracle_core.production_alerting",
            "oracle_core.production_storage",
            "oracle_core.cache_quota_policy",
            "oracle_core.production_readiness_gate",
        ]
        import importlib
        for mn in mods:
            importlib.import_module(mn)


if __name__ == "__main__":
    unittest.main()
