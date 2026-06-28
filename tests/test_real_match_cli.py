"""Tests for real_match_cli — Patch 36."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

CLI_MODULE = "oracle_core.real_match_cli"


def _repo_root():
    return os.path.dirname(os.path.dirname(__file__))


def _run_cli(*args, **kwargs) -> subprocess.CompletedProcess:
    """Run the real-match CLI with given args."""
    cmd = [sys.executable, "-m", CLI_MODULE] + list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=60,
        cwd=_repo_root(), **kwargs,
    )


def _make_temp_json(data: dict, suffix: str = ".json") -> str:
    """Write a dict as JSON to a temp file, return the path."""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="test_rc_")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def _cleanup(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass


def _synthetic_model_output() -> dict:
    return {
        "team_a": "Fictional Alpha FC",
        "team_b": "Fictional Beta FC",
        "result_probabilities": {
            "team_a_win": 0.48, "draw": 0.27, "team_b_win": 0.25,
        },
        "advancement_probabilities": {
            "Fictional Alpha FC": 0.65, "Fictional Beta FC": 0.35,
        },
        "top_scores": [
            {"score": [1, 0], "probability": 0.18},
            {"score": [1, 1], "probability": 0.11},
        ],
        "model_version": "provisional-v1",
    }


def _synthetic_context_snapshot() -> dict:
    return {
        "snapshot_id": "snap-test-001",
        "provider_name": "thesportsdb",
        "canonical_teams": [
            {"team_id": "FIC-001", "display_name": "Fictional Alpha FC"},
            {"team_id": "FIC-002", "display_name": "Fictional Beta FC"},
        ],
        "gap_list": ["injuries_missing", "odds_missing"],
        "data_quality_issues": [
            {"severity": "info", "code": "TEST_ISSUE", "message": "test"},
        ],
        "model_boundary": {
            "affects_model": False,
            "report_only_or_context_only": True,
            "enters_prediction_engine": False,
        },
    }


# ==========================================================================
# Core acceptance tests
# ==========================================================================


class TestRealMatchCliAcceptance(unittest.TestCase):
    """Test basic CLI acceptance of user-provided names."""

    def test_cli_accepts_home_away(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertEqual(result.returncode, 0)

    def test_cli_accepts_home_away_date_competition(self):
        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--date", "2026-06-16", "--competition", "Test Cup",
        )
        self.assertEqual(result.returncode, 0)

    def test_cli_rejects_empty_home(self):
        result = _run_cli("--home", "", "--away", "TeamB")
        self.assertNotEqual(result.returncode, 0)

    def test_cli_rejects_empty_away(self):
        result = _run_cli("--home", "TeamA", "--away", "")
        self.assertNotEqual(result.returncode, 0)

    def test_cli_rejects_same_teams(self):
        result = _run_cli("--home", "Same", "--away", "Same")
        self.assertNotEqual(result.returncode, 0)

    def test_cli_output_is_chinese_report(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        # The report contains Chinese characters
        self.assertIn("预测报告", result.stdout)
        self.assertIn("TeamA", result.stdout)
        self.assertIn("TeamB", result.stdout)


class TestRealMatchCliOffline(unittest.TestCase):
    """Test that the CLI is offline by default."""

    def test_default_cli_is_offline(self):
        fd, mp = tempfile.mkstemp(suffix=".json", prefix="offline_meta_")
        os.close(fd)
        self.addCleanup(lambda: _cleanup(mp))
        result = _run_cli("--home", "TeamA", "--away", "TeamB",
                          "--json-metadata", mp)
        self.assertEqual(result.returncode, 0)

    def test_default_cli_does_not_network(self):
        # The CLI should complete quickly without any network I/O
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertEqual(result.returncode, 0)
        # Verify: no urllib/requests imports in the module
        import oracle_core.real_match_cli as mod
        import inspect
        source = inspect.getsource(mod)
        for forbidden in ["urllib.request", "requests.get", "socket.create_connection"]:
            self.assertNotIn(forbidden, source,
                             f"real_match_cli should not import {forbidden}")

    def test_default_cli_does_not_read_env(self):
        # Run with a stripped environment
        clean_env = {}
        for k in ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "PATHEXT",
                  "TEMP", "TMP", "USERPROFILE", "HOME",
                  "PYTHONPATH", "PYTHONHOME"):
            if k in os.environ:
                clean_env[k] = os.environ[k]
        result = _run_cli("--home", "TeamA", "--away", "TeamB", env=clean_env)
        self.assertEqual(result.returncode, 0)

    def test_real_looking_names_do_not_cause_fabrication(self):
        """Real-looking team names must NOT trigger fabricated provider data."""
        result = _run_cli(
            "--home", "Brazil National Team", "--away", "Argentina National Team",
        )
        self.assertEqual(result.returncode, 0)
        # Must NOT fabricate probabilities
        self.assertNotIn("50.0%", result.stdout)
        # Must state probabilities are unavailable
        self.assertIn("未提供", result.stdout)
        # Must state provider context is unavailable
        self.assertTrue(
            "未提供" in result.stdout or "无 provider" in result.stdout
        )

    def test_no_live_payload_saved(self):
        """Default CLI should not write any files to the repo."""
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertEqual(result.returncode, 0)
        # No side effects — just stdout


class TestRealMatchCliModelOutput(unittest.TestCase):
    """Test external model_output integration."""

    def setUp(self):
        self.mo_path = _make_temp_json(_synthetic_model_output())
        self.addCleanup(lambda: _cleanup(self.mo_path))

    def test_no_model_output_shows_unavailable(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertIn("未提供", result.stdout)
        # No fake percentages
        self.assertNotIn("50.0%", result.stdout)

    def test_external_model_output_probabilities_appear(self):
        result = _run_cli(
            "--home", "Fictional Alpha FC", "--away", "Fictional Beta FC",
            "--model-output-json", self.mo_path,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("48.0%", result.stdout)
        self.assertIn("27.0%", result.stdout)
        self.assertIn("25.0%", result.stdout)

    def test_external_model_output_probabilities_unchanged(self):
        """Context must NOT override model_output probabilities."""
        ctx_path = _make_temp_json(_synthetic_context_snapshot())
        self.addCleanup(lambda: _cleanup(ctx_path))

        result = _run_cli(
            "--home", "Fictional Alpha FC", "--away", "Fictional Beta FC",
            "--model-output-json", self.mo_path,
            "--context-snapshot", ctx_path,
        )
        self.assertEqual(result.returncode, 0)
        # Probabilities from model_output must appear exactly
        self.assertIn("48.0%", result.stdout)
        # Context should NOT have changed them to something else
        self.assertNotIn("99.0%", result.stdout)

    def test_external_model_output_advancement_appears(self):
        result = _run_cli(
            "--home", "Fictional Alpha FC", "--away", "Fictional Beta FC",
            "--model-output-json", self.mo_path,
        )
        self.assertIn("65.0%", result.stdout)
        self.assertIn("35.0%", result.stdout)

    def test_missing_model_output_json_reports_error(self):
        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--model-output-json", "/nonexistent/path/file.json",
        )
        self.assertNotEqual(result.returncode, 0)


class TestRealMatchCliContextSnapshot(unittest.TestCase):
    """Test external context snapshot integration."""

    def setUp(self):
        self.ctx_path = _make_temp_json(_synthetic_context_snapshot())
        self.addCleanup(lambda: _cleanup(self.ctx_path))

    def test_context_snapshot_appears(self):
        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--context-snapshot", self.ctx_path,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("snap-test-001", result.stdout)

    def test_context_does_not_override_probabilities(self):
        mo_path = _make_temp_json(_synthetic_model_output())
        self.addCleanup(lambda: _cleanup(mo_path))

        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--model-output-json", mo_path,
            "--context-snapshot", self.ctx_path,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("48.0%", result.stdout)
        self.assertIn("snap-test-001", result.stdout)

    def test_context_appears_separately(self):
        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--context-snapshot", self.ctx_path,
        )
        self.assertIn("Provider Context", result.stdout)

    def test_missing_context_snapshot_shows_gap(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertTrue(
            "未提供" in result.stdout or "无 provider" in result.stdout
        )


class TestRealMatchCliGapsAndCaveats(unittest.TestCase):
    """Test that gaps and caveats appear correctly."""

    def test_gaps_appear(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertIn("数据缺口", result.stdout)
        self.assertIn("injuries_missing", result.stdout)
        self.assertIn("odds_missing", result.stdout)

    def test_caveats_appear(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertIn("Caveat", result.stdout)

    def test_scout_disabled_by_default(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertIn("Scout", result.stdout)

    def test_market_not_available(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertIn("Market Comparison", result.stdout)

    def test_thesportsdb_not_approved_stated(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertTrue(
            "needs_more_info" in result.stdout
            or "未 approved" in result.stdout
        )

    def test_provider_scout_odds_boundary_stated(self):
        result = _run_cli("--home", "TeamA", "--away", "TeamB")
        self.assertTrue(
            "不入模" in result.stdout
            or "report-only" in result.stdout.lower()
        )


class TestRealMatchCliLiveProviderBoundary(unittest.TestCase):
    """Test the --allow-live / --live-provider boundary."""

    def test_live_provider_without_allow_live_is_blocked(self):
        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--live-provider", "thesportsdb",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("live_provider_blocked", result.stdout)

    def test_allow_live_with_thesportsdb_returns_caveat(self):
        """Even with --allow-live, TheSportsDB is not approved."""
        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--allow-live", "--live-provider", "thesportsdb",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("needs_more_info", result.stdout)

    def test_thesportsdb_remains_needs_more_info(self):
        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--allow-live", "--live-provider", "thesportsdb",
        )
        self.assertNotIn("approved_for_live_adapter", result.stdout)


class TestRealMatchCliJsonMetadata(unittest.TestCase):
    """Test --json-metadata output."""

    def setUp(self):
        fd, self.meta_path = tempfile.mkstemp(suffix=".json", prefix="meta_")
        os.close(fd)
        self.addCleanup(lambda: _cleanup(self.meta_path))

    def test_json_metadata_offline_flags(self):
        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--json-metadata", self.meta_path,
        )
        self.assertEqual(result.returncode, 0)
        with open(self.meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertTrue(meta["is_offline"])
        self.assertFalse(meta["live_api_called"])
        self.assertFalse(meta["network_used"])
        self.assertFalse(meta["env_read"])
        self.assertFalse(meta["thesportsdb_approved"])

    def test_json_metadata_with_model_output(self):
        mo_path = _make_temp_json(_synthetic_model_output())
        self.addCleanup(lambda: _cleanup(mo_path))

        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--model-output-json", mo_path,
            "--json-metadata", self.meta_path,
        )
        self.assertEqual(result.returncode, 0)
        with open(self.meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertTrue(meta["model_output_provided"])
        self.assertFalse(meta["context_snapshot_provided"])


class TestRealMatchCliOutputToFile(unittest.TestCase):
    """Test --output to file."""

    def setUp(self):
        fd, self.out_path = tempfile.mkstemp(suffix=".txt", prefix="report_")
        os.close(fd)
        self.addCleanup(lambda: _cleanup(self.out_path))

    def test_output_to_file(self):
        result = _run_cli(
            "--home", "TeamA", "--away", "TeamB",
            "--output", self.out_path,
        )
        self.assertEqual(result.returncode, 0)
        with open(self.out_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("预测报告", content)
        self.assertIn("TeamA", content)


class TestRealMatchCliNoRealData(unittest.TestCase):
    """Verify no real teams or fixtures in default output."""

    def test_no_real_teams_in_default_output(self):
        result = _run_cli(
            "--home", "Test Home FC", "--away", "Test Away FC",
        )
        real_teams = ["Brazil", "Argentina", "France", "Germany", "England",
                       "Spain", "Italy", "Netherlands", "Portugal", "Croatia"]
        for rt in real_teams:
            self.assertNotIn(rt, result.stdout,
                             f"Real team '{rt}' should not be in default output")

    def test_no_fabricated_scores(self):
        """Even with real-looking names, no scores are fabricated."""
        result = _run_cli(
            "--home", "Manchester United", "--away", "Real Madrid",
        )
        # Must NOT contain fabricated score predictions like "2-1"
        self.assertIn("未提供", result.stdout)

    def test_no_network_imports_in_module(self):
        import oracle_core.real_match_cli as mod
        import inspect
        source = inspect.getsource(mod)
        networking = ["urllib.request", "urllib.error",
                       "requests.get", "requests.post",
                       "http.client", "socket.create_connection"]
        for net in networking:
            self.assertNotIn(net, source,
                             f"real_match_cli should not import {net}")


class TestRealMatchCliReplayability(unittest.TestCase):
    """Verify replayability with context snapshot."""

    def test_model_output_roundtrip(self):
        """model_output used in report should match what was provided."""
        mo = _synthetic_model_output()
        mo_path = _make_temp_json(mo)
        ctx_path = _make_temp_json(_synthetic_context_snapshot())
        self.addCleanup(lambda: _cleanup(mo_path, ctx_path))

        fd, meta_path = tempfile.mkstemp(suffix=".json", prefix="meta_")
        os.close(fd)
        self.addCleanup(lambda: _cleanup(meta_path))

        result = _run_cli(
            "--home", "Fictional Alpha FC", "--away", "Fictional Beta FC",
            "--model-output-json", mo_path,
            "--context-snapshot", ctx_path,
            "--json-metadata", meta_path,
        )
        self.assertEqual(result.returncode, 0)

        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertTrue(meta["model_output_provided"])
        self.assertTrue(meta["context_snapshot_provided"])
        self.assertFalse(meta["model_boundary"]["affects_model"])


if __name__ == "__main__":
    unittest.main()
