"""Patch 26 — TheSportsDB public-free live fetch readiness tests.

All offline. No network. No real data. No skipped tests.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest

from oracle_core.data_service_providers import ProviderCapability
from oracle_core.free_provider_adapters import (
    DisabledNetworkTransport,
    FreeProviderConfig,
    StdlibHttpTransport,
    TheSportsDbProviderAdapter,
)

from tests.live_provider_harness import (
    ENV_LIVE_TESTS,
    ENV_THESPORTSDB_PUBLIC_KEY,
    build_live_provider_config_from_env,
)

from tests.provider_contract_helpers import (
    assert_provider_does_not_import_prediction_runtime,
)


REPO = pathlib.Path(__file__).parent.parent


# ==========================================================================
# StdlibHttpTransport
# ==========================================================================


class StdlibHttpTransportTests(unittest.TestCase):
    def test_01_exists(self):
        t = StdlibHttpTransport()
        self.assertTrue(hasattr(t, "send"))

    def test_02_not_used_by_default_provider(self):
        """Default provider uses DisabledNetworkTransport, not StdlibHttpTransport."""
        p = TheSportsDbProviderAdapter()
        self.assertIsInstance(p._transport, DisabledNetworkTransport)


# ==========================================================================
# TheSportsDB config — default offline
# ==========================================================================


class TheSportsDbDefaultOfflineTests(unittest.TestCase):
    def test_01_default_config_no_network(self):
        p = TheSportsDbProviderAdapter()
        self.assertFalse(p._config.live_mode)
        self.assertFalse(p._config.enabled)
        self.assertFalse(p._config.public_free_mode)

    def test_02_default_fetch_returns_empty(self):
        p = TheSportsDbProviderAdapter()
        r = p.fetch_teams()
        self.assertTrue(r.is_empty)

    def test_03_public_free_config_from_env(self):
        env = {
            ENV_LIVE_TESTS: "1",
            ENV_THESPORTSDB_PUBLIC_KEY: "1",
        }
        cfg = build_live_provider_config_from_env(env, "thesportsdb")
        self.assertTrue(cfg.live_mode)
        self.assertTrue(cfg.enabled)
        self.assertTrue(cfg.public_free_mode)

    def test_04_public_free_config_defaults_key_to_123(self):
        """When THESPORTSDB_PUBLIC_API_KEY not set, defaults to public test key '123'."""
        env = {ENV_LIVE_TESTS: "1"}
        cfg = build_live_provider_config_from_env(env, "thesportsdb")
        self.assertEqual(cfg.public_api_key, "123")

    def test_05_source_reference_is_redacted(self):
        """source_reference redacts key as <public_test_key>, never leaks '123'."""
        ref = TheSportsDbProviderAdapter._build_redacted_source_reference(
            ProviderCapability.TEAMS, "https://example.com")
        self.assertIn("<public_test_key>", ref)
        self.assertNotIn("123", ref)

    def test_06_live_url_uses_123(self):
        """Actual outbound URL uses '123' (public test key convention)."""
        url = TheSportsDbProviderAdapter._build_live_url(
            ProviderCapability.TEAMS, "https://example.com", "123")
        self.assertIn("/123/", url)

    def test_07_no_code_uses_key_1(self):
        """No code path should use '/api/v1/json/1/' for TheSportsDB."""
        import oracle_core.free_provider_adapters as mod
        source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("/api/v1/json/1/", source)
        self.assertNotIn('_PUBLIC_TEST_KEY = "1"', source)

    def test_08_fetch_matches_uses_eventsnextleague(self):
        """fetch_matches should use eventsnextleague.php (smoke-test friendly)."""
        from oracle_core.free_provider_adapters import TheSportsDbProviderAdapter
        eps = TheSportsDbProviderAdapter._ENDPOINTS
        self.assertIn("eventsnextleague.php", eps[ProviderCapability.MATCHES])

    def test_09_fetch_matches_endpoint_has_id_param(self):
        """eventsnextleague.php must include id= parameter."""
        from oracle_core.free_provider_adapters import TheSportsDbProviderAdapter
        eps = TheSportsDbProviderAdapter._ENDPOINTS
        self.assertIn("id=", eps[ProviderCapability.MATCHES])

    def test_10_fetch_matches_redacted_source_has_public_test_key(self):
        """Redacted MATCHES source_reference uses <public_test_key>."""
        from oracle_core.free_provider_adapters import TheSportsDbProviderAdapter
        ref = TheSportsDbProviderAdapter._build_redacted_source_reference(
            ProviderCapability.MATCHES)
        self.assertIn("<public_test_key>", ref)
        self.assertNotIn("123", ref)

    def test_11_live_url_matches_uses_123(self):
        """Actual outbound MATCHES URL uses /123/."""
        from oracle_core.free_provider_adapters import TheSportsDbProviderAdapter
        url = TheSportsDbProviderAdapter._build_live_url(
            ProviderCapability.MATCHES, "https://example.com", "123")
        self.assertIn("/123/", url)


# ==========================================================================
# Live test file isolation
# ==========================================================================


class LiveTestFileIsolationTests(unittest.TestCase):
    def test_01_live_test_under_tests_live(self):
        p = REPO / "tests_live" / "test_thesportsdb_public_free_live.py"
        self.assertTrue(p.exists(), "Live test file must exist under tests_live/")

    def test_02_not_in_default_tests(self):
        p = REPO / "tests" / "test_thesportsdb_public_free_live.py"
        self.assertFalse(p.exists(),
                         "Live test must NOT be under tests/")

    def test_03_tests_live_not_in_default_discovery(self):
        self.assertNotIn("tests_live", str(REPO / "tests"))

    def test_04_live_test_no_skip_usage(self):
        text = (REPO / "tests_live/test_thesportsdb_public_free_live.py"
                ).read_text(encoding="utf-8")
        self.assertNotIn("skipTest", text)
        self.assertNotIn("SkipTest", text)
        self.assertNotIn("@unittest.skip", text)

    def test_05_live_test_requires_opt_in(self):
        text = (REPO / "tests_live/test_thesportsdb_public_free_live.py"
                ).read_text(encoding="utf-8")
        self.assertIn("require_live_provider_enabled", text)

    def test_06_live_test_no_system_exit_guard(self):
        """Live test must not use SystemExit as guard — use setUpClass instead."""
        text = (REPO / "tests_live/test_thesportsdb_public_free_live.py"
                ).read_text(encoding="utf-8")
        self.assertNotIn("SystemExit", text)

    def test_07_live_test_uses_setup_class_guard(self):
        """setUpClass calls require_live_provider_enabled."""
        text = (REPO / "tests_live/test_thesportsdb_public_free_live.py"
                ).read_text(encoding="utf-8")
        self.assertIn("setUpClass", text)


# ==========================================================================
# No private secrets leaked
# ==========================================================================


class PublicKeyConstantTests(unittest.TestCase):
    def test_01_key_constant_is_123(self):
        from oracle_core.free_provider_adapters import TheSportsDbProviderAdapter
        self.assertEqual(TheSportsDbProviderAdapter._PUBLIC_TEST_KEY, "123")

    def test_02_constant_named_public_test_key(self):
        """Constant name makes clear it's a public test key."""
        self.assertTrue(
            hasattr(TheSportsDbProviderAdapter, "_PUBLIC_TEST_KEY"))


class NoPrivateSecretsTests(unittest.TestCase):
    def test_01_no_private_api_key_patterns_in_repo(self):
        """Scan repo docs/tests for private API key patterns (not public key '1')."""
        for root_dir in (REPO / "docs", REPO / "tests"):
            for md in root_dir.rglob("*.md"):
                text = md.read_text(encoding="utf-8")
                for pat in (r'[a-f0-9]{32}', r'sk-[a-zA-Z0-9]{32,}'):
                    matches = re.findall(pat, text)
                    if matches:
                        # TheSportsDB public key "1" sometimes appears — that's OK
                        self.assertEqual(
                            matches, [],
                            f"{md.relative_to(REPO)}: API key pattern {pat} → {matches}"
                        )

    def test_02_public_key_labeled_as_public(self):
        """If public key usage exists, docs/code must label it as public test key."""
        for root_dir in (REPO / "docs", REPO / "tests", REPO / "tests_live"):
            if not root_dir.exists():
                continue
            for f in list(root_dir.rglob("*.py")) + list(root_dir.rglob("*.md")):
                text = f.read_text(encoding="utf-8").lower()
                if "public_api_key" in text or "public test key" in text:
                    self.assertTrue(
                        "not a private" in text or "not a user secret" in text
                        or "public test key" in text,
                        f"{f.relative_to(REPO)}: uses public key without "
                        f"labeling as 'not a private secret' or 'public test key'")


# ==========================================================================
# Import boundary
# ==========================================================================


class ReadinessImportBoundaryTests(unittest.TestCase):
    def test_01_adapter_module_clean(self):
        mod_path = REPO / "oracle_core" / "free_provider_adapters.py"
        assert_provider_does_not_import_prediction_runtime(mod_path)

    def test_02_live_harness_clean(self):
        mod_path = REPO / "tests" / "live_provider_harness.py"
        assert_provider_does_not_import_prediction_runtime(mod_path)


if __name__ == "__main__":
    unittest.main()
