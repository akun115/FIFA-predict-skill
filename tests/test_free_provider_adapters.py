"""Patch 22 — Free provider adapter skeleton tests.

All tests are offline.  No real API calls.  No network.  No real data.
No skipped tests.
"""

from __future__ import annotations

import ast
import pathlib
import unittest
from datetime import datetime, timezone

from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderConfigurationError,
    ProviderError,
    ProviderFetchResult,
    ProviderUnavailableError,
)
from oracle_core.data_service_validator import (
    validate_provider_fetch_result,
    has_blocking_issues,
)

from oracle_core.free_provider_adapters import (
    ApiFootballProviderAdapter,
    DisabledNetworkTransport,
    FakeHttpTransport,
    FootballDataOrgProviderAdapter,
    FreeProviderConfig,
    HttpRequest,
    HttpResponse,
    HttpTransport,
    ProviderCapabilityNotSupportedError,
)

from tests.provider_contract_helpers import (
    assert_fetch_result_envelope_valid,
    assert_fetch_result_provenance_valid,
    assert_no_forbidden_model_output_keys,
    assert_no_narrative_prediction,
    assert_provider_capabilities_complete,
    assert_provider_descriptor_valid,
    assert_provider_does_not_import_prediction_runtime,
    assert_provider_result_passes_validator,
)


# ==========================================================================
# Import boundary
# ==========================================================================


class FreeProviderImportBoundaryTests(unittest.TestCase):
    def test_01_adapter_module_no_prediction_imports(self):
        mod_path = (pathlib.Path(__file__).parent.parent
                    / "oracle_core" / "free_provider_adapters.py")
        assert_provider_does_not_import_prediction_runtime(mod_path)

    def test_02_prediction_modules_no_free_provider_import(self):
        engine_root = pathlib.Path(__file__).parent.parent / "oracle_core"
        for mod_name in ("engine.py", "types.py", "knockout.py",
                          "tournament.py", "odds.py", "evaluation.py"):
            mp = engine_root / mod_name
            if not mp.exists():
                continue
            source = mp.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("free_provider_adapters", alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertNotIn("free_provider_adapters", node.module)


# ==========================================================================
# HTTP transport
# ==========================================================================


class HttpTransportTests(unittest.TestCase):
    def test_01_disabled_transport_fails_closed(self):
        t = DisabledNetworkTransport()
        with self.assertRaises(ProviderError):
            t.send(HttpRequest(url="fixture://test"))

    def test_02_fake_transport_returns_known_path(self):
        t = FakeHttpTransport({"test": '{"ok": true}'})
        resp = t.send(HttpRequest(url="test"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.body_text, '{"ok": true}')
        self.assertIsNotNone(resp.fetched_at.tzinfo)

    def test_03_fake_transport_404_on_unknown(self):
        t = FakeHttpTransport()
        resp = t.send(HttpRequest(url="nonexistent"))
        self.assertEqual(resp.status_code, 404)

    def test_04_fake_transport_add_response(self):
        t = FakeHttpTransport()
        t.add("new_path", '{"added": 1}')
        resp = t.send(HttpRequest(url="new_path"))
        self.assertEqual(resp.status_code, 200)

    def test_05_fake_transport_deterministic(self):
        t = FakeHttpTransport({"a": '{"v":1}'})
        r1 = t.send(HttpRequest(url="a"))
        r2 = t.send(HttpRequest(url="a"))
        self.assertEqual(r1.body_text, r2.body_text)
        self.assertEqual(r1.fetched_at, r2.fetched_at)

    def test_06_http_response_naive_datetime_raises(self):
        with self.assertRaises(ValueError):
            HttpResponse(body_text="x", fetched_at=datetime(2026, 6, 15, 12, 0, 0))


# ==========================================================================
# FreeProviderConfig
# ==========================================================================


class FreeProviderConfigTests(unittest.TestCase):
    def test_01_default_config_offline(self):
        c = FreeProviderConfig()
        self.assertFalse(c.live_mode)
        self.assertFalse(c.enabled)

    def test_02_require_api_key_raises_when_live_mode_false(self):
        c = FreeProviderConfig(live_mode=False)
        with self.assertRaises(ProviderError):
            c.require_api_key()

    def test_03_require_api_key_raises_when_no_env_var_configured(self):
        c = FreeProviderConfig(live_mode=True, api_key_env_var="")
        with self.assertRaises(ProviderError):
            c.require_api_key()

    def test_04_config_is_frozen(self):
        c = FreeProviderConfig()
        with self.assertRaises(Exception):
            c.live_mode = True  # type: ignore[misc]


# ==========================================================================
# FootballDataOrgProviderAdapter
# ==========================================================================


class FootballDataOrgAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = FootballDataOrgProviderAdapter()

    # ── Descriptor ──

    def test_01_descriptor_valid(self):
        assert_provider_descriptor_valid(self.provider,
                                          expected_name="football-data.org")

    def test_02_capabilities_conservative(self):
        """Only TEAMS, MATCHES, GROUP_STANDINGS — not odds/lineups/injuries."""
        caps = self.provider.descriptor.capabilities
        self.assertIn(ProviderCapability.TEAMS, caps)
        self.assertIn(ProviderCapability.MATCHES, caps)
        self.assertIn(ProviderCapability.GROUP_STANDINGS, caps)
        self.assertNotIn(ProviderCapability.ODDS, caps)
        self.assertNotIn(ProviderCapability.LINEUPS, caps)
        self.assertNotIn(ProviderCapability.INJURIES, caps)
        self.assertNotIn(ProviderCapability.SUSPENSIONS, caps)
        self.assertNotIn(ProviderCapability.PREMATCH_SIGNALS, caps)

    # ── Supported fetch methods ──

    def test_03_fetch_teams_result_type(self):
        r = self.provider.fetch_teams()
        self.assertIsInstance(r, ProviderFetchResult)

    def test_04_fetch_matches_result_type(self):
        r = self.provider.fetch_matches()
        self.assertIsInstance(r, ProviderFetchResult)

    def test_05_fetch_standings_result_type(self):
        r = self.provider.fetch_group_standings()
        self.assertIsInstance(r, ProviderFetchResult)

    # ── Unsupported capabilities return empty ──

    def test_06_unsupported_odds_returns_empty(self):
        r = self.provider.fetch_odds()
        self.assertTrue(r.is_empty or r.payload == {})

    def test_07_unsupported_lineups_returns_empty(self):
        r = self.provider.fetch_lineups()
        self.assertTrue(r.is_empty or r.payload == {})

    def test_08_unsupported_injuries_returns_empty(self):
        r = self.provider.fetch_injuries()
        self.assertTrue(r.is_empty or r.payload == {})


# ==========================================================================
# ApiFootballProviderAdapter
# ==========================================================================


class ApiFootballAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = ApiFootballProviderAdapter()

    # ── Descriptor ──

    def test_01_descriptor_valid(self):
        assert_provider_descriptor_valid(self.provider,
                                          expected_name="api-football")

    def test_02_capabilities_include_odds_and_lineups(self):
        caps = self.provider.descriptor.capabilities
        self.assertIn(ProviderCapability.TEAMS, caps)
        self.assertIn(ProviderCapability.MATCHES, caps)
        self.assertIn(ProviderCapability.GROUP_STANDINGS, caps)
        self.assertIn(ProviderCapability.ODDS, caps)
        self.assertIn(ProviderCapability.LINEUPS, caps)
        # Injuries/suspensions NOT supported
        self.assertNotIn(ProviderCapability.INJURIES, caps)
        self.assertNotIn(ProviderCapability.SUSPENSIONS, caps)

    # ── Supported fetch methods ──

    def test_03_fetch_teams(self):
        self.assertIsInstance(self.provider.fetch_teams(), ProviderFetchResult)

    def test_04_fetch_matches(self):
        self.assertIsInstance(self.provider.fetch_matches(), ProviderFetchResult)

    def test_05_fetch_standings(self):
        self.assertIsInstance(self.provider.fetch_group_standings(), ProviderFetchResult)

    def test_06_fetch_odds(self):
        r = self.provider.fetch_odds()
        self.assertIsInstance(r, ProviderFetchResult)

    def test_07_fetch_lineups(self):
        r = self.provider.fetch_lineups()
        self.assertIsInstance(r, ProviderFetchResult)

    # ── Unsupported ──

    def test_08_unsupported_injuries_returns_empty(self):
        r = self.provider.fetch_injuries()
        self.assertTrue(r.is_empty or r.payload == {})


# ==========================================================================
# Enabled provider with FakeHttpTransport
# ==========================================================================


class EnabledProviderWithFakeTransportTests(unittest.TestCase):
    """When a provider is enabled with FakeHttpTransport, it returns data."""

    def _fake_transport(self):
        from oracle_core.free_provider_adapters import (
            _FIC_TEAMS_JSON, _FIC_MATCHES_JSON, _FIC_STANDINGS_JSON,
            _FIC_ODDS_JSON, _FIC_LINEUPS_JSON,
        )
        return FakeHttpTransport({
            "fixture://football-data.org/teams": _FIC_TEAMS_JSON,
            "fixture://football-data.org/matches": _FIC_MATCHES_JSON,
            "fixture://football-data.org/standings": _FIC_STANDINGS_JSON,
            "fixture://api-football/teams": _FIC_TEAMS_JSON,
            "fixture://api-football/fixtures": _FIC_MATCHES_JSON,
            "fixture://api-football/standings": _FIC_STANDINGS_JSON,
            "fixture://api-football/odds": _FIC_ODDS_JSON,
            "fixture://api-football/lineups": _FIC_LINEUPS_JSON,
        })

    # ── FootballDataOrg (enabled) ──

    def test_01_fdo_fetch_teams_has_payload(self):
        p = FootballDataOrgProviderAdapter(
            config=FreeProviderConfig(enabled=True),
            transport=self._fake_transport(),
        )
        r = p.fetch_teams()
        self.assertFalse(r.is_empty)
        self.assertIn("teams", r.payload)

    def test_02_fdo_fetch_matches_has_payload(self):
        p = FootballDataOrgProviderAdapter(
            config=FreeProviderConfig(enabled=True),
            transport=self._fake_transport(),
        )
        r = p.fetch_matches()
        self.assertFalse(r.is_empty)
        self.assertIn("matches", r.payload)

    def test_03_fdo_source_reference_is_fixture(self):
        p = FootballDataOrgProviderAdapter(
            config=FreeProviderConfig(enabled=True),
            transport=self._fake_transport(),
        )
        r = p.fetch_teams()
        self.assertTrue(r.source_reference.startswith("fixture://"))

    # ── ApiFootball (enabled) ──

    def test_04_api_fetch_odds_has_payload(self):
        p = ApiFootballProviderAdapter(
            config=FreeProviderConfig(enabled=True),
            transport=self._fake_transport(),
        )
        r = p.fetch_odds()
        self.assertFalse(r.is_empty)
        self.assertIn("odds", r.payload)

    def test_05_api_fetch_lineups_has_payload(self):
        p = ApiFootballProviderAdapter(
            config=FreeProviderConfig(enabled=True),
            transport=self._fake_transport(),
        )
        r = p.fetch_lineups()
        self.assertFalse(r.is_empty)
        self.assertIn("lineups", r.payload)

    def test_06_api_source_reference_is_fixture(self):
        p = ApiFootballProviderAdapter(
            config=FreeProviderConfig(enabled=True),
            transport=self._fake_transport(),
        )
        r = p.fetch_teams()
        self.assertTrue(r.source_reference.startswith("fixture://"))


# ==========================================================================
# Contract harness — all supported capabilities
# ==========================================================================


class FreeProviderContractTests(unittest.TestCase):
    """All supported fetch results pass contract harness and validator."""

    @classmethod
    def setUpClass(cls):
        from oracle_core.free_provider_adapters import (
            _FIC_TEAMS_JSON, _FIC_MATCHES_JSON, _FIC_STANDINGS_JSON,
            _FIC_ODDS_JSON, _FIC_LINEUPS_JSON,
        )
        t = FakeHttpTransport({
            "fixture://football-data.org/teams": _FIC_TEAMS_JSON,
            "fixture://football-data.org/matches": _FIC_MATCHES_JSON,
            "fixture://football-data.org/standings": _FIC_STANDINGS_JSON,
            "fixture://api-football/teams": _FIC_TEAMS_JSON,
            "fixture://api-football/fixtures": _FIC_MATCHES_JSON,
            "fixture://api-football/standings": _FIC_STANDINGS_JSON,
            "fixture://api-football/odds": _FIC_ODDS_JSON,
            "fixture://api-football/lineups": _FIC_LINEUPS_JSON,
        })
        cfg = FreeProviderConfig(enabled=True)
        cls.fdo = FootballDataOrgProviderAdapter(config=cfg, transport=t)
        cls.api = ApiFootballProviderAdapter(config=cfg, transport=t)

    def _check(self, provider, cap):
        method = getattr(provider, f"fetch_{cap.value}")
        r = method()
        if r.is_empty:
            return  # unsupported → skip contract
        assert_fetch_result_envelope_valid(provider, cap, r)
        assert_fetch_result_provenance_valid(provider, r)
        assert_no_forbidden_model_output_keys(r)
        assert_no_narrative_prediction(r)
        assert_provider_result_passes_validator(r)

    # FootballDataOrg — TEAMS, MATCHES, STANDINGS
    def test_01_fdo_teams(self): self._check(self.fdo, ProviderCapability.TEAMS)
    def test_02_fdo_matches(self): self._check(self.fdo, ProviderCapability.MATCHES)
    def test_03_fdo_standings(self): self._check(self.fdo, ProviderCapability.GROUP_STANDINGS)

    # ApiFootball — TEAMS, MATCHES, STANDINGS, ODDS, LINEUPS
    def test_04_api_teams(self): self._check(self.api, ProviderCapability.TEAMS)
    def test_05_api_matches(self): self._check(self.api, ProviderCapability.MATCHES)
    def test_06_api_standings(self): self._check(self.api, ProviderCapability.GROUP_STANDINGS)
    def test_07_api_odds(self): self._check(self.api, ProviderCapability.ODDS)
    def test_08_api_lineups(self): self._check(self.api, ProviderCapability.LINEUPS)


# ==========================================================================
# Fixture data integrity
# ==========================================================================


class FixtureDataIntegrityTests(unittest.TestCase):
    """All synthetic fixture payloads are fictional and safe."""

    @classmethod
    def setUpClass(cls):
        from oracle_core.free_provider_adapters import (
            _FIC_TEAMS_JSON, _FIC_MATCHES_JSON, _FIC_STANDINGS_JSON,
            _FIC_ODDS_JSON, _FIC_LINEUPS_JSON,
        )
        cls.all_json = " ".join([
            _FIC_TEAMS_JSON, _FIC_MATCHES_JSON, _FIC_STANDINGS_JSON,
            _FIC_ODDS_JSON, _FIC_LINEUPS_JSON,
        ])

    def test_01_no_real_team_names(self):
        real = ("Brazil", "Argentina", "France", "Germany", "England", "Spain")
        for name in real:
            self.assertNotIn(name, self.all_json)

    def test_02_no_real_player_names(self):
        real = ("Messi", "Ronaldo", "Mbappé", "Neymar", "Kane")
        for name in real:
            self.assertNotIn(name, self.all_json)

    def test_03_uses_FIC_prefix(self):
        self.assertIn("FIC-", self.all_json)

    def test_04_uses_fictional_names(self):
        for term in ("Fictional", "Fake"):
            self.assertIn(term, self.all_json)

    def test_05_no_real_api_urls(self):
        self.assertNotIn("https://api.football-data.org", self.all_json)
        self.assertNotIn("https://v3.football.api-sports.io", self.all_json)

    def test_06_no_api_keys(self):
        self.assertNotIn("X-Auth-Token", self.all_json)
        self.assertNotIn("x-apisports-key", self.all_json)


# ==========================================================================
# Patch 22.1 — Full 9-method coverage (FootballDataOrg)
# ==========================================================================


_ALL_CAPS = tuple(ProviderCapability)


class FootballDataOrgAllMethodsTests(unittest.TestCase):
    """All 9 ProviderCapability methods exist and behave correctly."""

    @classmethod
    def setUpClass(cls):
        cls.provider = FootballDataOrgProviderAdapter()
        t = FakeHttpTransport({
            "fixture://football-data.org/teams": '{"teams":[]}',
            "fixture://football-data.org/matches": '{"matches":[]}',
            "fixture://football-data.org/standings": '{"standings":[]}',
        })
        cls.enabled_provider = FootballDataOrgProviderAdapter(
            config=FreeProviderConfig(enabled=True), transport=t)
        cls.SUPPORTED = {ProviderCapability.TEAMS, ProviderCapability.MATCHES,
                         ProviderCapability.GROUP_STANDINGS}

    def _check(self, cap):
        method = getattr(self.provider, f"fetch_{cap.value}")
        r = method()
        self.assertIsInstance(r, ProviderFetchResult,
                              f"fetch_{cap.value}() must return ProviderFetchResult")
        self.assertEqual(r.capability, cap,
                         f"fetch_{cap.value}() capability mismatch")
        return r

    def test_01_teams(self): self._check(ProviderCapability.TEAMS)
    def test_02_matches(self): self._check(ProviderCapability.MATCHES)
    def test_03_standings(self): self._check(ProviderCapability.GROUP_STANDINGS)
    def test_04_bracket(self): self._check(ProviderCapability.KNOCKOUT_BRACKET)
    def test_05_odds(self): self._check(ProviderCapability.ODDS)
    def test_06_lineups(self): self._check(ProviderCapability.LINEUPS)
    def test_07_injuries(self): self._check(ProviderCapability.INJURIES)
    def test_08_suspensions(self): self._check(ProviderCapability.SUSPENSIONS)
    def test_09_signals(self): self._check(ProviderCapability.PREMATCH_SIGNALS)

    def test_10_supported_not_empty(self):
        for cap in self.SUPPORTED:
            r = getattr(self.enabled_provider, f"fetch_{cap.value}")()
            self.assertFalse(r.is_empty,
                             f"Supported {cap.value} should not be empty")

    def test_11_unsupported_are_empty(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            self.assertTrue(r.is_empty or r.payload == {},
                            f"Unsupported {cap.value} should be empty")

    def test_12_unsupported_have_warnings(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            self.assertTrue(r.warnings,
                            f"Unsupported {cap.value} should have warnings")

    def test_13_unsupported_completeness_not_available(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            comp = r.completeness
            self.assertFalse(comp.get("available", True),
                             f"Unsupported {cap.value} completeness should show not available")

    def test_14_unsupported_no_real_source(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            self.assertTrue(
                r.source_reference.startswith("fixture://"),
                f"Unsupported {cap.value} source must use fixture://, got {r.source_reference!r}")

    def test_15_unsupported_no_forbidden_keys(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            assert_no_forbidden_model_output_keys(r)

    def test_16_unsupported_no_narrative(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            assert_no_narrative_prediction(r)


# ==========================================================================
# Patch 22.1 — Full 9-method coverage (ApiFootball)
# ==========================================================================


class ApiFootballAllMethodsTests(unittest.TestCase):
    """All 9 ProviderCapability methods for ApiFootball."""

    @classmethod
    def setUpClass(cls):
        cls.provider = ApiFootballProviderAdapter()
        t = FakeHttpTransport({
            "fixture://api-football/teams": '{"teams":[]}',
            "fixture://api-football/fixtures": '{"matches":[]}',
            "fixture://api-football/standings": '{"standings":[]}',
            "fixture://api-football/odds": '{"odds":[]}',
            "fixture://api-football/lineups": '{"lineups":[]}',
        })
        cls.enabled_provider = ApiFootballProviderAdapter(
            config=FreeProviderConfig(enabled=True), transport=t)
        cls.SUPPORTED = {ProviderCapability.TEAMS, ProviderCapability.MATCHES,
                         ProviderCapability.GROUP_STANDINGS,
                         ProviderCapability.ODDS, ProviderCapability.LINEUPS}

    def _check(self, cap):
        method = getattr(self.provider, f"fetch_{cap.value}")
        r = method()
        self.assertIsInstance(r, ProviderFetchResult,
                              f"fetch_{cap.value}() must return ProviderFetchResult")
        self.assertEqual(r.capability, cap)
        return r

    def test_01_teams(self): self._check(ProviderCapability.TEAMS)
    def test_02_matches(self): self._check(ProviderCapability.MATCHES)
    def test_03_standings(self): self._check(ProviderCapability.GROUP_STANDINGS)
    def test_04_bracket(self): self._check(ProviderCapability.KNOCKOUT_BRACKET)
    def test_05_odds(self): self._check(ProviderCapability.ODDS)
    def test_06_lineups(self): self._check(ProviderCapability.LINEUPS)
    def test_07_injuries(self): self._check(ProviderCapability.INJURIES)
    def test_08_suspensions(self): self._check(ProviderCapability.SUSPENSIONS)
    def test_09_signals(self): self._check(ProviderCapability.PREMATCH_SIGNALS)

    def test_10_supported_not_empty(self):
        for cap in self.SUPPORTED:
            r = getattr(self.enabled_provider, f"fetch_{cap.value}")()
            self.assertFalse(r.is_empty,
                             f"Supported {cap.value} should not be empty")

    def test_11_unsupported_are_empty(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            self.assertTrue(r.is_empty or r.payload == {},
                            f"Unsupported {cap.value} should be empty")

    def test_12_unsupported_have_warnings(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            self.assertTrue(r.warnings,
                            f"Unsupported {cap.value} should have warnings")

    def test_13_unsupported_completeness_not_available(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            self.assertFalse(r.completeness.get("available", True))

    def test_14_unsupported_no_real_source(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            self.assertTrue(r.source_reference.startswith("fixture://"))

    def test_15_unsupported_no_forbidden_keys(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            assert_no_forbidden_model_output_keys(r)

    def test_16_unsupported_no_narrative(self):
        for cap in _ALL_CAPS:
            if cap in self.SUPPORTED:
                continue
            r = getattr(self.provider, f"fetch_{cap.value}")()
            assert_no_narrative_prediction(r)


# ==========================================================================
# Patch 22.1 — Fail-closed error semantics
# ==========================================================================


class FailClosedErrorSemanticsTests(unittest.TestCase):
    """Correct error types for each failure scenario."""

    def test_01_disabled_transport_raises_unavailable(self):
        t = DisabledNetworkTransport()
        with self.assertRaises(ProviderUnavailableError):
            t.send(HttpRequest(url="fixture://test"))

    def test_02_disabled_transport_is_provider_error(self):
        t = DisabledNetworkTransport()
        with self.assertRaises(ProviderError):
            t.send(HttpRequest(url="fixture://test"))

    def test_03_live_mode_false_require_key_raises_configuration(self):
        c = FreeProviderConfig(live_mode=False)
        with self.assertRaises(ProviderConfigurationError):
            c.require_api_key()

    def test_04_no_env_var_raises_configuration(self):
        c = FreeProviderConfig(live_mode=True, api_key_env_var="")
        with self.assertRaises(ProviderConfigurationError):
            c.require_api_key()

    def test_05_missing_key_raises_configuration(self):
        c = FreeProviderConfig(live_mode=True,
                               api_key_env_var="NONEXISTENT_ENV_VAR_FOR_TEST")
        with self.assertRaises(ProviderConfigurationError):
            c.require_api_key()

    def test_06_adapter_with_disabled_transport_returns_empty_not_raises(self):
        """Adapter with DisabledNetworkTransport returns empty result, not exception."""
        p = FootballDataOrgProviderAdapter(
            config=FreeProviderConfig(enabled=True),
            transport=DisabledNetworkTransport(),
        )
        r = p.fetch_teams()
        self.assertIsInstance(r, ProviderFetchResult)
        self.assertTrue(r.is_empty)

    def test_07_disabled_provider_returns_empty(self):
        """enabled=False → empty result with warning."""
        p = FootballDataOrgProviderAdapter(config=FreeProviderConfig(enabled=False))
        r = p.fetch_teams()
        self.assertTrue(r.warnings)


if __name__ == "__main__":
    unittest.main()
