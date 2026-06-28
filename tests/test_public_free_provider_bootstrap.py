"""Patch 25 — Public-free bootstrap + provider strategy tests.

All offline. No network. No real data. No skipped tests.
All doc-based assertions replaced with README-based assertions.
"""

from __future__ import annotations

import pathlib
import unittest

from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderFetchResult,
)

from oracle_core.free_provider_adapters import (
    TheSportsDbProviderAdapter,
    FakeHttpTransport,
    FreeProviderConfig,
)

from tests.provider_contract_helpers import (
    assert_fetch_result_envelope_valid,
    assert_no_forbidden_model_output_keys,
    assert_no_narrative_prediction,
    assert_provider_descriptor_valid,
    assert_provider_does_not_import_prediction_runtime,
)


README = pathlib.Path(__file__).parent.parent / "README.md"


# ==========================================================================
# README — Free provider strategy
# ==========================================================================


class FreeFirstStrategyClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_01_mentions_thesportsdb_as_free_provider(self):
        self.assertIn("TheSportsDB", self.readme)

    def test_02_covers_fail_closed_strategy(self):
        self.assertIn("fail-closed", self.readme.lower())

    def test_03_covers_report_only_strategy(self):
        self.assertIn("report-only", self.readme.lower())

    def test_04_paid_providers_not_configured(self):
        self.assertIn("external credentials", self.readme.lower())


# ==========================================================================
# README — TheSportsDB status
# ==========================================================================


class TheSportsDbDossierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_01_says_needs_more_info(self):
        self.assertIn("needs_more_info", self.readme.lower())

    def test_02_approved_for_live_adapter_only_in_negative_context(self):
        idx = self.readme.lower().find("approved_for_live_adapter")
        if idx >= 0:
            nearby = self.readme.lower()[max(0, idx - 60):idx + 60]
            self.assertTrue(
                any(w in nearby for w in ("not", "no", "never")),
                "approved_for_live_adapter must only appear in negative context")


# ==========================================================================
# TheSportsDbProviderAdapter
# ==========================================================================


class TheSportsDbProviderAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = TheSportsDbProviderAdapter()

    def test_01_descriptor_valid(self):
        assert_provider_descriptor_valid(self.__class__.provider,
                                          expected_name="thesportsdb")

    def test_02_capabilities_conservative(self):
        caps = self.__class__.provider.descriptor.capabilities
        self.assertIn(ProviderCapability.TEAMS, caps)
        self.assertIn(ProviderCapability.MATCHES, caps)
        for c in (ProviderCapability.GROUP_STANDINGS, ProviderCapability.ODDS,
                   ProviderCapability.LINEUPS, ProviderCapability.INJURIES,
                   ProviderCapability.SUSPENSIONS,
                   ProviderCapability.KNOCKOUT_BRACKET,
                   ProviderCapability.PREMATCH_SIGNALS):
            self.assertNotIn(c, caps, f"{c.value} should not be supported")

    def test_03_fetch_teams_result_type(self):
        self.assertIsInstance(
            self.__class__.provider.fetch_teams(), ProviderFetchResult)

    def test_04_fetch_matches_result_type(self):
        self.assertIsInstance(
            self.__class__.provider.fetch_matches(), ProviderFetchResult)

    def test_05_unsupported_return_empty(self):
        for cap in (ProviderCapability.GROUP_STANDINGS, ProviderCapability.ODDS):
            r = getattr(self.__class__.provider, f"fetch_{cap.value}")()
            self.assertTrue(r.is_empty or r.payload == {},
                            f"Unsupported {cap.value} should be empty")

    def test_06_unsupported_have_warnings(self):
        for cap in (ProviderCapability.ODDS, ProviderCapability.INJURIES):
            r = getattr(self.__class__.provider, f"fetch_{cap.value}")()
            self.assertTrue(r.warnings)


# ==========================================================================
# Public free bootstrap — TheSportsDB enabled + FakeHttpTransport
# ==========================================================================


class PublicFreeBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from oracle_core.free_provider_adapters import (
            _THESPORTSDB_TEAMS_JSON, _THESPORTSDB_MATCHES_JSON)
        t = FakeHttpTransport({
            "fixture://thesportsdb/searchteams": _THESPORTSDB_TEAMS_JSON,
            "fixture://thesportsdb/events": _THESPORTSDB_MATCHES_JSON,
        })
        cls.provider = TheSportsDbProviderAdapter(
            config=FreeProviderConfig(enabled=True), transport=t)

    def test_01_fetch_teams_has_payload(self):
        r = self.provider.fetch_teams()
        self.assertFalse(r.is_empty)
        self.assertIn("teams", r.payload)

    def test_02_fetch_matches_has_payload(self):
        r = self.provider.fetch_matches()
        self.assertFalse(r.is_empty)
        self.assertIn("events", r.payload)

    def test_03_source_reference_is_fixture(self):
        r = self.provider.fetch_teams()
        self.assertTrue(r.source_reference.startswith("fixture://"))

    def test_04_contract_envelope(self):
        r = self.provider.fetch_teams()
        assert_fetch_result_envelope_valid(
            self.provider, ProviderCapability.TEAMS, r)

    def test_05_contract_matches(self):
        r = self.provider.fetch_matches()
        assert_fetch_result_envelope_valid(
            self.provider, ProviderCapability.MATCHES, r)

    def test_06_no_forbidden_keys(self):
        for cap in (ProviderCapability.TEAMS, ProviderCapability.MATCHES):
            r = getattr(self.provider, f"fetch_{cap.value}")()
            assert_no_forbidden_model_output_keys(r)

    def test_07_no_narrative_prediction(self):
        for cap in (ProviderCapability.TEAMS, ProviderCapability.MATCHES):
            r = getattr(self.provider, f"fetch_{cap.value}")()
            assert_no_narrative_prediction(r)


# ==========================================================================
# TheSportsDB mapper — fixture integrity
# ==========================================================================


class TheSportsDbMapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from oracle_core.free_provider_adapters import (
            _THESPORTSDB_TEAMS_JSON, _THESPORTSDB_MATCHES_JSON)
        cls.json = _THESPORTSDB_TEAMS_JSON + _THESPORTSDB_MATCHES_JSON

    def test_01_no_real_teams(self):
        for name in ("Brazil", "Argentina", "France", "Germany"):
            self.assertNotIn(name, self.json)

    def test_02_no_real_players(self):
        for name in ("Messi", "Ronaldo", "Mbappé"):
            self.assertNotIn(name, self.json)

    def test_03_uses_FIC_prefix(self):
        self.assertIn("FIC-", self.json)

    def test_04_uses_fictional_names(self):
        self.assertIn("Fictional", self.json)
        self.assertIn("Fake Cup", self.json)

    def test_05_no_real_api_urls(self):
        self.assertNotIn("https://www.thesportsdb.com", self.json)


# ==========================================================================
# README — Web scout fallback policy
# ==========================================================================


class WebScoutPolicyDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_01_covers_report_only(self):
        self.assertIn("report-only", self.readme.lower())

    def test_02_covers_no_xg_adjustment(self):
        self.assertIn("xG adjustment", self.readme)

    def test_03_covers_no_odds_blending(self):
        self.assertIn("never blended", self.readme.lower())

    def test_04_covers_snapshot(self):
        self.assertIn("snapshot", self.readme.lower())


# ==========================================================================
# Import boundary
# ==========================================================================


class BootstrapImportBoundaryTests(unittest.TestCase):
    def test_01_free_provider_module_clean(self):
        mod_path = (pathlib.Path(__file__).parent.parent
                    / "oracle_core" / "free_provider_adapters.py")
        assert_provider_does_not_import_prediction_runtime(mod_path)


if __name__ == "__main__":
    unittest.main()
