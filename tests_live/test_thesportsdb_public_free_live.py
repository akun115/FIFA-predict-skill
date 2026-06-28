"""TheSportsDB public-free live smoke test — opt-in only.

NOT discovered by default ``python -m unittest discover tests -v``.
Requires explicit opt-in:

    WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS=1 \
    python -m unittest discover tests_live -v

TheSportsDB public test key "123" is the official free/test key,
NOT a private user secret.
"""

from __future__ import annotations

import os
import unittest

from tests.live_provider_harness import (
    require_live_provider_enabled,
    build_live_provider_config_from_env,
)
from oracle_core.free_provider_adapters import (
    TheSportsDbProviderAdapter,
    StdlibHttpTransport,
)
from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderConfigurationError,
)
from tests.provider_contract_helpers import (
    assert_fetch_result_envelope_valid,
    assert_no_forbidden_model_output_keys,
    assert_no_narrative_prediction,
)


class TheSportsDbPublicFreeLiveSmokeTest(unittest.TestCase):
    """Minimal live smoke test for TheSportsDB public-free API."""

    @classmethod
    def setUpClass(cls):
        env = os.environ
        require_live_provider_enabled(env)
        config = build_live_provider_config_from_env(env, "thesportsdb")
        cls.provider = TheSportsDbProviderAdapter(
            config=config,
            transport=StdlibHttpTransport(),
        )

    def test_01_fetch_teams_returns_result(self):
        r = self.provider.fetch_teams()
        self.assertEqual(r.provider_name, "thesportsdb")

    def test_02_fetch_teams_envelope_valid(self):
        r = self.provider.fetch_teams()
        assert_fetch_result_envelope_valid(
            self.provider, ProviderCapability.TEAMS, r)

    def test_03_fetch_teams_no_forbidden_keys(self):
        r = self.provider.fetch_teams()
        assert_no_forbidden_model_output_keys(r)

    def test_04_fetch_teams_no_narrative(self):
        r = self.provider.fetch_teams()
        assert_no_narrative_prediction(r)

    def test_05_fetch_teams_source_redacted(self):
        r = self.provider.fetch_teams()
        self.assertIn("<public_test_key>", r.source_reference)
        self.assertNotIn("123", r.source_reference)

    # ── fetch_matches ──

    def test_06_fetch_matches_returns_result(self):
        r = self.provider.fetch_matches()
        self.assertEqual(r.provider_name, "thesportsdb")

    def test_07_fetch_matches_envelope_valid(self):
        r = self.provider.fetch_matches()
        assert_fetch_result_envelope_valid(
            self.provider, ProviderCapability.MATCHES, r)

    def test_08_fetch_matches_no_forbidden_keys(self):
        r = self.provider.fetch_matches()
        assert_no_forbidden_model_output_keys(r)

    def test_09_fetch_matches_no_narrative(self):
        r = self.provider.fetch_matches()
        assert_no_narrative_prediction(r)

    def test_10_fetch_matches_source_redacted(self):
        r = self.provider.fetch_matches()
        self.assertIn("<public_test_key>", r.source_reference)
        self.assertNotIn("123", r.source_reference)
