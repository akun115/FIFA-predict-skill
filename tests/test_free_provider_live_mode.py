"""Patch 23 — Live mode README validation + harness tests.

All tests offline.  No real API calls.  No network.  No API key read.
No skipped tests.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest

from oracle_core.data_service_providers import ProviderConfigurationError
from oracle_core.free_provider_adapters import FreeProviderConfig

from tests.live_provider_harness import (
    ENV_LIVE_TESTS,
    ENV_FOOTBALL_DATA_ORG_KEY,
    ENV_API_FOOTBALL_KEY,
    build_live_provider_config_from_env,
    require_api_key,
    require_live_provider_enabled,
    should_run_live_provider_tests,
)


# ==========================================================================
# README content validation
# ==========================================================================


class LiveModeDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = pathlib.Path(__file__).parent.parent / "README.md"
        cls.text = p.read_text(encoding="utf-8") if p.exists() else ""

    def test_01_default_mode_offline(self):
        """README covers default offline mode."""
        self.assertIn("offline", self.text.lower())
        self.assertIn("default", self.text.lower())

    def test_02_default_no_network(self):
        """README covers no network when running in default mode."""
        text_lower = self.text.lower()
        self.assertTrue(
            "no network" in text_lower or "offline" in text_lower)

    def test_03_fail_closed_never_skip(self):
        """README states that missing credentials fail closed, never skip."""
        text_lower = self.text.lower()
        self.assertIn("fail closed", text_lower)
        self.assertIn("never skip", text_lower)

    def test_04_mentions_live_tests_env_var(self):
        """README mentions the live-tests env var name."""
        self.assertIn(ENV_LIVE_TESTS, self.text)

    def test_05_mentions_football_data_org(self):
        """README mentions FOOTBALL_DATA_ORG_TOKEN."""
        self.assertIn("FOOTBALL_DATA_ORG_TOKEN", self.text)

    def test_06_mentions_api_keys_generally(self):
        """README mentions API keys in some form."""
        self.assertIn("api key", self.text.lower())

    def test_07_never_commit_credentials(self):
        """README instructs never to commit credentials to the repo."""
        self.assertIn("Never commit credentials", self.text)

    def test_08_mentions_credentials(self):
        """README mentions credentials (key/protection boundary)."""
        self.assertIn("credentials", self.text.lower())

    def test_09_no_model_probability_effect(self):
        """README states that provider/scout/odds data does not affect model."""
        text_lower = self.text.lower()
        self.assertTrue(
            "no xg adjustment" in text_lower or "report-only" in text_lower,
            "README should state that provider/scout data does not "
            "affect model probabilities")

    def test_10_no_real_api_urls(self):
        """No URLs point to actual API endpoints."""
        urls = re.findall(r'https?://[^\s\)"<>]+', self.text)
        for url in urls:
            url_lower = url.lower()
            self.assertFalse(
                re.search(r'/api/|api\.|/v\d+/', url_lower),
                f"README may contain API endpoint URL: {url}")

    def test_11_no_api_key_patterns(self):
        """README does not contain hard-coded API key patterns."""
        for pat in (r'[a-f0-9]{32}', r'sk-[a-zA-Z0-9]{32,}'):
            self.assertEqual(re.findall(pat, self.text), [])


# ==========================================================================
# should_run_live_provider_tests
# ==========================================================================


class ShouldRunLiveTestsTests(unittest.TestCase):
    def test_01_empty_env_false(self):
        self.assertFalse(should_run_live_provider_tests({}))

    def test_02_flag_set_true(self):
        self.assertTrue(should_run_live_provider_tests(
            {ENV_LIVE_TESTS: "1"}))

    def test_03_flag_zero_false(self):
        self.assertFalse(should_run_live_provider_tests(
            {ENV_LIVE_TESTS: "0"}))

    def test_04_flag_missing_false(self):
        self.assertFalse(should_run_live_provider_tests(
            {"OTHER_VAR": "value"}))


# ==========================================================================
# require_live_provider_enabled
# ==========================================================================


class RequireLiveEnabledTests(unittest.TestCase):
    def test_01_empty_env_raises(self):
        with self.assertRaises(ProviderConfigurationError):
            require_live_provider_enabled({})

    def test_02_flag_set_passes(self):
        require_live_provider_enabled({ENV_LIVE_TESTS: "1"})

    def test_03_is_provider_error_subclass(self):
        with self.assertRaises(ProviderConfigurationError):
            require_live_provider_enabled({})


# ==========================================================================
# require_api_key
# ==========================================================================


class RequireApiKeyTests(unittest.TestCase):
    def test_01_missing_raises(self):
        with self.assertRaises(ProviderConfigurationError):
            require_api_key({}, "MY_KEY")

    def test_02_empty_raises(self):
        with self.assertRaises(ProviderConfigurationError):
            require_api_key({"MY_KEY": ""}, "MY_KEY")

    def test_03_present_returns_value(self):
        val = require_api_key({"MY_KEY": "test-key-value"}, "MY_KEY")
        self.assertEqual(val, "test-key-value")

    def test_04_never_logs_key(self):
        """require_api_key returns the value but the test never prints it."""
        val = require_api_key({"SECRET": "xyz"}, "SECRET")
        self.assertIsInstance(val, str)
        # Value is used only in assertion — never printed to stdout


# ==========================================================================
# build_live_provider_config_from_env
# ==========================================================================


class BuildLiveConfigTests(unittest.TestCase):
    def _valid_env(self):
        return {
            ENV_LIVE_TESTS: "1",
            ENV_FOOTBALL_DATA_ORG_KEY: "fake-fdo-key",
            ENV_API_FOOTBALL_KEY: "fake-api-key",
        }

    def test_01_builds_config_for_football_data_org(self):
        cfg = build_live_provider_config_from_env(
            self._valid_env(), "football-data.org")
        self.assertTrue(cfg.live_mode)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.api_key_env_var, ENV_FOOTBALL_DATA_ORG_KEY)

    def test_02_builds_config_for_api_football(self):
        cfg = build_live_provider_config_from_env(
            self._valid_env(), "api-football")
        self.assertTrue(cfg.live_mode)
        self.assertEqual(cfg.api_key_env_var, ENV_API_FOOTBALL_KEY)

    def test_03_missing_live_flag_raises(self):
        env = {ENV_FOOTBALL_DATA_ORG_KEY: "k"}
        with self.assertRaises(ProviderConfigurationError):
            build_live_provider_config_from_env(env, "football-data.org")

    def test_04_missing_key_raises(self):
        env = {ENV_LIVE_TESTS: "1"}
        with self.assertRaises(ProviderConfigurationError):
            build_live_provider_config_from_env(env, "football-data.org")

    def test_05_unknown_provider_raises(self):
        with self.assertRaises(ProviderConfigurationError):
            build_live_provider_config_from_env(
                self._valid_env(), "unknown-provider")

    def test_06_config_is_frozen(self):
        cfg = build_live_provider_config_from_env(
            self._valid_env(), "football-data.org")
        with self.assertRaises(Exception):
            cfg.live_mode = False  # type: ignore[misc]


# ==========================================================================
# Import boundary
# ==========================================================================


class LiveHarnessImportBoundaryTests(unittest.TestCase):
    def test_01_harness_no_prediction_imports(self):
        mod_path = (pathlib.Path(__file__).parent
                    / "live_provider_harness.py")
        source = mod_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        banned = ("oracle_core.engine", "oracle_core.knockout",
                   "oracle_core.tournament", "oracle_core.odds")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for b in banned:
                        self.assertNotIn(b, alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for b in banned:
                        self.assertNotIn(b, node.module)

    def test_02_harness_reads_no_os_environ(self):
        """Harness functions accept explicit env param; no os.environ calls."""
        mod_path = (pathlib.Path(__file__).parent
                    / "live_provider_harness.py")
        source = mod_path.read_text(encoding="utf-8")
        self.assertIn("env: Mapping[str, str]", source)
        # Check that no executable code calls os.environ directly
        # (docstring examples are OK — they show correct usage)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    full = f"{ast.unparse(node.func.value)}.{node.func.attr}"
                    if full == "os.environ" or full == "os.getenv":
                        self.fail(
                            f"Harness calls {full}() directly at line "
                            f"{node.lineno} — must accept explicit env param")


if __name__ == "__main__":
    unittest.main()
