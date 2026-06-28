"""Tests for Data Service v1 provider adapter interface + fake provider (Patch 15).

All fixtures are fictional.  No real data.  No network.  No live providers.
No prediction engine integration.  No skipped tests.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

from oracle_core.data_service_providers import (
    DeterministicFakeProvider,
    ProviderAdapter,
    ProviderCapability,
    ProviderConfigurationError,
    ProviderDescriptor,
    ProviderError,
    ProviderFetchResult,
    ProviderSchemaError,
    ProviderUnavailableError,
    _compute_payload_hash,
    _FAKE_BRACKET_PAYLOAD,
    _FAKE_INJURIES_PAYLOAD,
    _FAKE_LINEUPS_PAYLOAD,
    _FAKE_MATCHES_PAYLOAD,
    _FAKE_ODDS_PAYLOAD,
    _FAKE_SIGNALS_PAYLOAD,
    _FAKE_STANDINGS_PAYLOAD,
    _FAKE_SUSPENSIONS_PAYLOAD,
    _FAKE_TEAMS_PAYLOAD,
    _FAKE_NOW,
    _fake_source,
    _make_result,
)


# ==========================================================================
# Import boundary
# ==========================================================================


class ProviderImportBoundaryTests(unittest.TestCase):
    """Provider adapter module must not import prediction engine modules."""

    _PREDICTION_MODULES = (
        "oracle_core.engine",
        "oracle_core.scoring",
        "oracle_core.fitted",
        "oracle_core.knockout",
        "oracle_core.tournament",
        "oracle_core.odds",
    )

    def test_01_provider_module_does_not_import_prediction(self):
        """data_service_providers does not import prediction engine modules."""
        import oracle_core.data_service_providers as mod

        source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for banned in self._PREDICTION_MODULES:
                        self.assertNotIn(
                            banned,
                            alias.name,
                            f"data_service_providers imports {alias.name} (banned: {banned})",
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for banned in self._PREDICTION_MODULES:
                        self.assertNotIn(
                            banned,
                            node.module,
                            f"data_service_providers imports from {node.module} (banned: {banned})",
                        )

    def test_02_prediction_modules_do_not_import_provider_module(self):
        """Prediction engine modules do not import data_service_providers."""
        engine_root = pathlib.Path(__file__).parent.parent / "oracle_core"
        modules_to_check = [
            "engine.py", "types.py", "knockout.py", "tournament.py",
            "odds.py", "evaluation.py", "scoring.py", "fitted.py",
        ]
        for mod_name in modules_to_check:
            mod_path = engine_root / mod_name
            if not mod_path.exists():
                continue
            source = mod_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(
                            "data_service_providers",
                            alias.name,
                            f"{mod_name} imports data_service_providers via {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertNotIn(
                            "data_service_providers",
                            node.module,
                            f"{mod_name} imports from data_service_providers",
                        )


# ==========================================================================
# Provider descriptor
# ==========================================================================


class ProviderDescriptorTests(unittest.TestCase):
    """ProviderDescriptor metadata and serialization."""

    def test_01_descriptor_construction(self):
        desc = ProviderDescriptor(
            name="test_provider",
            adapter_version="2.0.0",
            capabilities=frozenset({ProviderCapability.TEAMS, ProviderCapability.MATCHES}),
        )
        self.assertEqual(desc.name, "test_provider")
        self.assertEqual(desc.adapter_version, "2.0.0")
        self.assertIn(ProviderCapability.TEAMS, desc.capabilities)

    def test_02_descriptor_to_dict(self):
        desc = DeterministicFakeProvider.descriptor
        d = desc.to_dict()
        self.assertEqual(d["name"], "fake_provider_v1")
        self.assertEqual(d["adapter_version"], "1.0.0")
        self.assertEqual(len(d["capabilities"]), len(ProviderCapability))
        self.assertFalse(d["requires_credentials"])

    def test_03_fake_provider_descriptor_has_all_capabilities(self):
        desc = DeterministicFakeProvider.descriptor
        self.assertEqual(
            desc.capabilities,
            frozenset(ProviderCapability),
            "Fake provider should support all capabilities",
        )


# ==========================================================================
# ProviderFetchResult envelope
# ==========================================================================


class ProviderFetchResultTests(unittest.TestCase):
    """ProviderFetchResult construction, validation, and metadata."""

    def test_01_construction_valid(self):
        result = _make_result(
            ProviderCapability.TEAMS,
            _FAKE_TEAMS_PAYLOAD,
        )
        self.assertEqual(result.provider_name, "fake_provider_v1")
        self.assertEqual(result.adapter_version, "1.0.0")
        self.assertEqual(result.capability, ProviderCapability.TEAMS)
        self.assertIsNotNone(result.fetched_at.tzinfo)
        self.assertTrue(result.source_reference.startswith("fixture://"))
        self.assertEqual(len(result.raw_payload_hash), 64)

    def test_02_fetched_at_is_fixed(self):
        r1 = _make_result(ProviderCapability.TEAMS, _FAKE_TEAMS_PAYLOAD)
        r2 = _make_result(ProviderCapability.MATCHES, _FAKE_MATCHES_PAYLOAD)
        self.assertEqual(r1.fetched_at, r2.fetched_at)
        self.assertEqual(r1.fetched_at, _FAKE_NOW)

    def test_03_source_reference_uses_fixture(self):
        result = _make_result(ProviderCapability.ODDS, _FAKE_ODDS_PAYLOAD)
        self.assertIn("fixture://", result.source_reference)
        self.assertNotIn("http://", result.source_reference)
        self.assertNotIn("https://", result.source_reference)

    def test_04_raw_payload_hash_is_deterministic(self):
        r1 = _make_result(ProviderCapability.TEAMS, _FAKE_TEAMS_PAYLOAD)
        r2 = _make_result(ProviderCapability.TEAMS, _FAKE_TEAMS_PAYLOAD)
        self.assertEqual(r1.raw_payload_hash, r2.raw_payload_hash)

    def test_05_different_payloads_have_different_hashes(self):
        r1 = _make_result(ProviderCapability.TEAMS, _FAKE_TEAMS_PAYLOAD)
        r2 = _make_result(ProviderCapability.MATCHES, _FAKE_MATCHES_PAYLOAD)
        self.assertNotEqual(r1.raw_payload_hash, r2.raw_payload_hash)

    def test_06_empty_provider_name_raises(self):
        with self.assertRaises(ValueError):
            ProviderFetchResult(
                provider_name="  ",
                adapter_version="1.0.0",
                capability=ProviderCapability.TEAMS,
                fetched_at=_FAKE_NOW,
                source_reference="fixture://test",
                raw_payload_hash="abc",
            )

    def test_07_naive_datetime_raises(self):
        from datetime import datetime as dt

        with self.assertRaises(ValueError):
            ProviderFetchResult(
                provider_name="test",
                adapter_version="1.0.0",
                capability=ProviderCapability.TEAMS,
                fetched_at=dt(2026, 6, 15, 12, 0, 0),
                source_reference="fixture://test",
                raw_payload_hash="abc",
            )

    def test_08_empty_source_reference_raises(self):
        with self.assertRaises(ValueError):
            ProviderFetchResult(
                provider_name="test",
                adapter_version="1.0.0",
                capability=ProviderCapability.TEAMS,
                fetched_at=_FAKE_NOW,
                source_reference="  ",
                raw_payload_hash="abc",
            )

    def test_09_is_empty_detects_empty_payload(self):
        r1 = _make_result(ProviderCapability.TEAMS, _FAKE_TEAMS_PAYLOAD)
        self.assertFalse(r1.is_empty)

        r2 = ProviderFetchResult(
            provider_name="test",
            adapter_version="1.0.0",
            capability=ProviderCapability.TEAMS,
            fetched_at=_FAKE_NOW,
            source_reference="fixture://test",
            raw_payload_hash="abc",
            payload={},
        )
        self.assertTrue(r2.is_empty)

    def test_10_to_dict(self):
        result = _make_result(ProviderCapability.TEAMS, _FAKE_TEAMS_PAYLOAD)
        d = result.to_dict()
        self.assertEqual(d["provider_name"], "fake_provider_v1")
        self.assertEqual(d["capability"], "teams")
        self.assertEqual(d["source_reference"], _fake_source("teams"))
        self.assertIsInstance(d["warnings"], list)

    def test_11_warnings_are_preserved(self):
        result = _make_result(
            ProviderCapability.LINEUPS,
            _FAKE_LINEUPS_PAYLOAD,
            warnings=("stale_data_possible",),
        )
        self.assertIn("stale_data_possible", result.warnings)

    def test_12_completeness_metadata(self):
        result = DeterministicFakeProvider().fetch_odds()
        self.assertIn("markets_present", result.completeness)


# ==========================================================================
# ProviderCapability enum
# ==========================================================================


class ProviderCapabilityTests(unittest.TestCase):
    """ProviderCapability enum values."""

    def test_01_all_capabilities_defined(self):
        expected = {
            "teams", "matches", "group_standings", "knockout_bracket",
            "odds", "lineups", "injuries", "suspensions", "prematch_signals",
        }
        actual = {c.value for c in ProviderCapability}
        self.assertEqual(actual, expected)

    def test_02_capability_is_string_enum(self):
        self.assertEqual(ProviderCapability.TEAMS.value, "teams")
        self.assertIsInstance(ProviderCapability.ODDS.value, str)


# ==========================================================================
# Provider error hierarchy
# ==========================================================================


class ProviderErrorTests(unittest.TestCase):
    """Structured provider error hierarchy."""

    def test_01_base_category(self):
        err = ProviderError("base")
        self.assertEqual(err.category, "provider")

    def test_02_unavailable_category(self):
        err = ProviderUnavailableError("down")
        self.assertEqual(err.category, "unavailable")

    def test_03_configuration_category(self):
        err = ProviderConfigurationError("bad key")
        self.assertEqual(err.category, "configuration")

    def test_04_schema_category(self):
        err = ProviderSchemaError("unexpected field")
        self.assertEqual(err.category, "schema")

    def test_05_errors_are_runtime_errors(self):
        for err_cls in (
            ProviderError,
            ProviderUnavailableError,
            ProviderConfigurationError,
            ProviderSchemaError,
        ):
            with self.assertRaises(RuntimeError):
                raise err_cls("test")


# ==========================================================================
# Deterministic fake provider — all methods return ProviderFetchResult
# ==========================================================================


class FakeProviderMethodTests(unittest.TestCase):
    """Every fetch method returns a valid ProviderFetchResult."""

    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def _assert_valid_result(self, result: ProviderFetchResult, capability: ProviderCapability):
        self.assertIsInstance(result, ProviderFetchResult)
        self.assertEqual(result.provider_name, "fake_provider_v1")
        self.assertEqual(result.capability, capability)
        self.assertEqual(result.adapter_version, "1.0.0")
        self.assertIsNotNone(result.fetched_at.tzinfo)
        self.assertTrue(result.source_reference.startswith("fixture://"))
        self.assertEqual(len(result.raw_payload_hash), 64)
        self.assertFalse(result.is_empty)

    def test_01_fetch_teams(self):
        result = self.provider.fetch_teams()
        self._assert_valid_result(result, ProviderCapability.TEAMS)
        self.assertIn("teams", result.payload)

    def test_02_fetch_matches(self):
        result = self.provider.fetch_matches()
        self._assert_valid_result(result, ProviderCapability.MATCHES)
        self.assertIn("matches", result.payload)

    def test_03_fetch_group_standings(self):
        result = self.provider.fetch_group_standings()
        self._assert_valid_result(result, ProviderCapability.GROUP_STANDINGS)
        self.assertIn("standings", result.payload)

    def test_04_fetch_knockout_bracket(self):
        result = self.provider.fetch_knockout_bracket()
        self._assert_valid_result(result, ProviderCapability.KNOCKOUT_BRACKET)
        self.assertIn("bracket", result.payload)

    def test_05_fetch_odds(self):
        result = self.provider.fetch_odds()
        self._assert_valid_result(result, ProviderCapability.ODDS)
        self.assertIn("odds", result.payload)

    def test_06_fetch_lineups(self):
        result = self.provider.fetch_lineups()
        self._assert_valid_result(result, ProviderCapability.LINEUPS)
        self.assertIn("lineups", result.payload)

    def test_07_fetch_injuries(self):
        result = self.provider.fetch_injuries()
        self._assert_valid_result(result, ProviderCapability.INJURIES)
        self.assertIn("injuries", result.payload)

    def test_08_fetch_suspensions(self):
        result = self.provider.fetch_suspensions()
        self._assert_valid_result(result, ProviderCapability.SUSPENSIONS)
        self.assertIn("suspensions", result.payload)

    def test_09_fetch_prematch_signals(self):
        result = self.provider.fetch_prematch_signals()
        self._assert_valid_result(result, ProviderCapability.PREMATCH_SIGNALS)
        self.assertIn("signals", result.payload)


# ==========================================================================
# Fake provider determinism
# ==========================================================================


class FakeProviderDeterminismTests(unittest.TestCase):
    """Fake provider is fully deterministic — same call, same result every time."""

    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def test_01_fetch_teams_deterministic(self):
        r1 = self.provider.fetch_teams()
        r2 = self.provider.fetch_teams()
        self.assertEqual(r1.raw_payload_hash, r2.raw_payload_hash)
        self.assertEqual(r1.payload, r2.payload)

    def test_02_fetch_matches_deterministic(self):
        r1 = self.provider.fetch_matches()
        r2 = self.provider.fetch_matches()
        self.assertEqual(r1.raw_payload_hash, r2.raw_payload_hash)

    def test_03_fetch_odds_deterministic(self):
        r1 = self.provider.fetch_odds()
        r2 = self.provider.fetch_odds()
        self.assertEqual(r1.raw_payload_hash, r2.raw_payload_hash)

    def test_04_fetch_lineups_deterministic(self):
        r1 = self.provider.fetch_lineups()
        r2 = self.provider.fetch_lineups()
        self.assertEqual(r1.raw_payload_hash, r2.raw_payload_hash)

    def test_05_fetch_signals_deterministic(self):
        r1 = self.provider.fetch_prematch_signals()
        r2 = self.provider.fetch_prematch_signals()
        self.assertEqual(r1.raw_payload_hash, r2.raw_payload_hash)


# ==========================================================================
# Fake provider — no real data
# ==========================================================================


class FakeProviderNoRealDataTests(unittest.TestCase):
    """All fake provider payloads use fictional names — no real teams, players, odds."""

    _REAL_PATTERNS = (
        "Brazil", "Argentina", "France", "Germany", "England", "Spain",
        "Italy", "Netherlands", "Portugal", "Mexico", "Canada", "Uruguay",
        "Japan", "Korea", "Senegal", "Morocco", "Croatia", "Belgium",
        "USA", "United States", "Australia", "Iran", "Saudi Arabia",
        "Qatar", "Ecuador", "Wales", "Poland", "Denmark", "Switzerland",
        "Serbia", "Cameroon", "Ghana", "Tunisia", "Costa Rica",
        "Neymar", "Messi", "Mbappé", "Ronaldo", "Kane", "Salah",
        "Modric", "De Bruyne", "Haaland", "Bellingham",
    )

    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def _check_no_real_names(self, payload_name: str, result: ProviderFetchResult):
        """Verify payload contains no real-world team/player names."""
        payload_str = str(result.payload).lower()
        for pattern in self._REAL_PATTERNS:
            self.assertNotIn(
                pattern.lower(),
                payload_str,
                f"'{payload_name}' payload contains real-world pattern '{pattern}'",
            )

    def test_01_teams_no_real_names(self):
        self._check_no_real_names("teams", self.provider.fetch_teams())

    def test_02_matches_no_real_names(self):
        self._check_no_real_names("matches", self.provider.fetch_matches())

    def test_03_standings_no_real_names(self):
        self._check_no_real_names("standings", self.provider.fetch_group_standings())

    def test_04_bracket_no_real_names(self):
        self._check_no_real_names("bracket", self.provider.fetch_knockout_bracket())

    def test_05_odds_no_real_names(self):
        self._check_no_real_names("odds", self.provider.fetch_odds())

    def test_06_lineups_no_real_names(self):
        result = self.provider.fetch_lineups()
        self._check_no_real_names("lineups", result)
        # Every player name must contain "Fake"
        for entry in result.payload["lineups"]:
            for player in entry.get("starting_xi", ()):
                self.assertIn("Fake", player["name"])
            for player in entry.get("substitutes", ()):
                self.assertIn("Fake", player["name"])

    def test_07_injuries_no_real_names(self):
        self._check_no_real_names("injuries", self.provider.fetch_injuries())

    def test_08_suspensions_no_real_names(self):
        self._check_no_real_names("suspensions", self.provider.fetch_suspensions())

    def test_09_signals_no_real_names(self):
        result = self.provider.fetch_prematch_signals()
        self._check_no_real_names("signals", result)
        for entry in result.payload["signals"]:
            self.assertIn("Fictional", entry["summary"])
            self.assertIn("Fictional", entry["source_name"])

    def test_10_source_references_are_fixture_not_http(self):
        methods = [
            self.provider.fetch_teams,
            self.provider.fetch_matches,
            self.provider.fetch_group_standings,
            self.provider.fetch_knockout_bracket,
            self.provider.fetch_odds,
            self.provider.fetch_lineups,
            self.provider.fetch_injuries,
            self.provider.fetch_suspensions,
            self.provider.fetch_prematch_signals,
        ]
        for method in methods:
            result = method()
            self.assertTrue(
                result.source_reference.startswith("fixture://"),
                f"{result.capability.value}: source_reference='{result.source_reference}' "
                "does not start with 'fixture://'",
            )
            self.assertNotIn(
                "http://", result.source_reference,
                f"{result.capability.value}: source_reference contains 'http://'",
            )
            self.assertNotIn(
                "https://", result.source_reference,
                f"{result.capability.value}: source_reference contains 'https://'",
            )


# ==========================================================================
# Fake provider — no model probability output
# ==========================================================================


class FakeProviderNoModelOutputTests(unittest.TestCase):
    """Fake provider results contain raw data, not model probabilities.

    Provider data must not contain result_probabilities, expected_goals,
    top_scores, over_under probabilities, or advancement_probabilities —
    those are the prediction engine's job, never the provider's.
    """

    _BANNED_KEYS = (
        "result_probabilities",
        "expected_goals",
        "top_scores",
        "over_under",
        "advancement_probabilities",
        "team_a_win",
        "team_b_win",
        "draw_probability",
    )

    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def _assert_no_model_keys(self, result: ProviderFetchResult):
        """Recursively check that payload contains no prediction-engine keys."""
        def _check(obj, path=""):
            if isinstance(obj, dict):
                for key in obj:
                    self.assertNotIn(
                        key,
                        self._BANNED_KEYS,
                        f"{result.capability.value} payload at {path} "
                        f"contains banned model key '{key}'",
                    )
                    _check(obj[key], f"{path}.{key}")
            elif isinstance(obj, (tuple, list)):
                for i, item in enumerate(obj):
                    _check(item, f"{path}[{i}]")

        _check(result.payload, "root")

    def test_01_teams_no_model_output(self):
        self._assert_no_model_keys(self.provider.fetch_teams())

    def test_02_matches_no_model_output(self):
        self._assert_no_model_keys(self.provider.fetch_matches())

    def test_03_standings_no_model_output(self):
        self._assert_no_model_keys(self.provider.fetch_group_standings())

    def test_04_bracket_no_model_output(self):
        self._assert_no_model_keys(self.provider.fetch_knockout_bracket())

    def test_05_odds_no_model_output(self):
        """Odds payload has decimal_odds (market data), not model probabilities."""
        result = self.provider.fetch_odds()
        self._assert_no_model_keys(result)
        # decimal_odds IS allowed — it's raw market data, not model output
        self.assertIn("decimal_odds", str(result.payload))

    def test_06_lineups_no_model_output(self):
        self._assert_no_model_keys(self.provider.fetch_lineups())

    def test_07_injuries_no_model_output(self):
        self._assert_no_model_keys(self.provider.fetch_injuries())

    def test_08_suspensions_no_model_output(self):
        self._assert_no_model_keys(self.provider.fetch_suspensions())

    def test_09_signals_no_model_output(self):
        self._assert_no_model_keys(self.provider.fetch_prematch_signals())


# ==========================================================================
# Provider adapter Protocol compliance
# ==========================================================================


class ProviderAdapterProtocolTests(unittest.TestCase):
    """DeterministicFakeProvider satisfies the ProviderAdapter Protocol."""

    def test_01_fake_provider_satisfies_protocol(self):
        """All required methods exist and are callable."""
        provider = DeterministicFakeProvider()
        required_methods = [
            "fetch_teams", "fetch_matches", "fetch_group_standings",
            "fetch_knockout_bracket", "fetch_odds", "fetch_lineups",
            "fetch_injuries", "fetch_suspensions", "fetch_prematch_signals",
        ]
        for method_name in required_methods:
            self.assertTrue(
                hasattr(provider, method_name),
                f"DeterministicFakeProvider missing method '{method_name}'",
            )
            method = getattr(provider, method_name)
            self.assertTrue(callable(method), f"'{method_name}' is not callable")

    def test_02_descriptor_is_provider_descriptor(self):
        provider = DeterministicFakeProvider()
        self.assertIsInstance(provider.descriptor, ProviderDescriptor)


# ==========================================================================
# _compute_payload_hash determinism
# ==========================================================================


class PayloadHashTests(unittest.TestCase):
    """_compute_payload_hash is deterministic and collision-resistant."""

    def test_01_same_payload_same_hash(self):
        h1 = _compute_payload_hash(_FAKE_TEAMS_PAYLOAD)
        h2 = _compute_payload_hash(_FAKE_TEAMS_PAYLOAD)
        self.assertEqual(h1, h2)

    def test_02_different_payload_different_hash(self):
        h1 = _compute_payload_hash(_FAKE_TEAMS_PAYLOAD)
        h2 = _compute_payload_hash(_FAKE_MATCHES_PAYLOAD)
        self.assertNotEqual(h1, h2)

    def test_03_hash_is_64_char_hex(self):
        h = _compute_payload_hash(_FAKE_ODDS_PAYLOAD)
        self.assertEqual(len(h), 64)
        int(h, 16)  # must not raise

    def test_04_dict_key_ordering_does_not_affect_hash(self):
        p1 = {"a": 1, "b": 2}
        p2 = {"b": 2, "a": 1}
        self.assertEqual(_compute_payload_hash(p1), _compute_payload_hash(p2))


# ==========================================================================
# Patch 15.1 — Protocol tightening: descriptor + capability + name/version alignment
# ==========================================================================


class ProtocolTighteningTests(unittest.TestCase):
    """ProviderAdapter Protocol must require descriptor; fake provider must comply."""

    _FETCH_CAPABILITY_MAP = (
        ("fetch_teams", ProviderCapability.TEAMS),
        ("fetch_matches", ProviderCapability.MATCHES),
        ("fetch_group_standings", ProviderCapability.GROUP_STANDINGS),
        ("fetch_knockout_bracket", ProviderCapability.KNOCKOUT_BRACKET),
        ("fetch_odds", ProviderCapability.ODDS),
        ("fetch_lineups", ProviderCapability.LINEUPS),
        ("fetch_injuries", ProviderCapability.INJURIES),
        ("fetch_suspensions", ProviderCapability.SUSPENSIONS),
        ("fetch_prematch_signals", ProviderCapability.PREMATCH_SIGNALS),
    )

    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def test_01_protocol_declares_descriptor(self):
        """ProviderAdapter Protocol includes descriptor: ProviderDescriptor."""
        # Protocol annotations may not surface via hasattr — check __annotations__
        # Note: from __future__ import annotations makes these strings, not types
        hints = getattr(ProviderAdapter, "__annotations__", {})
        self.assertIn("descriptor", hints,
                      "ProviderAdapter Protocol must declare 'descriptor'")
        anno = hints["descriptor"]
        # Accept either the class object or the string name (PEP 563)
        self.assertTrue(
            anno is ProviderDescriptor or anno == "ProviderDescriptor",
            f"descriptor annotation='{anno}' must be ProviderDescriptor",
        )

    def test_02_fake_provider_exposes_descriptor(self):
        self.assertTrue(hasattr(self.provider, "descriptor"))
        self.assertIsInstance(self.provider.descriptor, ProviderDescriptor)

    def test_03_descriptor_capabilities_cover_all_nine(self):
        caps = self.provider.descriptor.capabilities
        self.assertEqual(
            caps,
            frozenset(ProviderCapability),
            "Fake provider descriptor must cover all 9 ProviderCapability values",
        )

    def test_04_each_fetch_method_returns_correct_capability(self):
        """Every fetch_X method must return ProviderCapability.X."""
        for method_name, expected_cap in self._FETCH_CAPABILITY_MAP:
            method = getattr(self.provider, method_name)
            result = method()
            self.assertEqual(
                result.capability,
                expected_cap,
                f"{method_name}() returned capability={result.capability.value}, "
                f"expected={expected_cap.value}",
            )

    def test_05_provider_name_matches_descriptor_name(self):
        """Every fetch result's provider_name must equal descriptor.name."""
        for method_name, _ in self._FETCH_CAPABILITY_MAP:
            method = getattr(self.provider, method_name)
            result = method()
            self.assertEqual(
                result.provider_name,
                self.provider.descriptor.name,
                f"{method_name}(): provider_name='{result.provider_name}' "
                f"!= descriptor.name='{self.provider.descriptor.name}'",
            )

    def test_06_adapter_version_matches_descriptor_version(self):
        """Every fetch result's adapter_version must equal descriptor.adapter_version."""
        for method_name, _ in self._FETCH_CAPABILITY_MAP:
            method = getattr(self.provider, method_name)
            result = method()
            self.assertEqual(
                result.adapter_version,
                self.provider.descriptor.adapter_version,
                f"{method_name}(): adapter_version='{result.adapter_version}' "
                f"!= descriptor.adapter_version='{self.provider.descriptor.adapter_version}'",
            )


# ==========================================================================
# Patch 15.1 — Payload hash canonicalization rules
# ==========================================================================


class PayloadHashCanonicalizationTests(unittest.TestCase):
    """_compute_payload_hash must follow documented canonicalization rules.

    Rules (from _compute_payload_hash docstring, Patch 15.1):
      - Dict keys sorted at ALL nesting levels.
      - Tuples and lists both serialize as JSON arrays (same hash).
      - SHA-256 over UTF-8 canonical JSON.
    """

    def test_01_nested_dict_key_order_does_not_affect_hash(self):
        """Nested dicts with different key order produce same hash."""
        p1 = {
            "outer": [
                {"inner_a": 1, "inner_b": 2},
                {"inner_c": 3, "inner_d": 4},
            ],
        }
        p2 = {
            "outer": [
                {"inner_b": 2, "inner_a": 1},
                {"inner_d": 4, "inner_c": 3},
            ],
        }
        self.assertEqual(
            _compute_payload_hash(p1),
            _compute_payload_hash(p2),
            "Nested dict key order must not affect hash",
        )

    def test_02_deeply_nested_dict_key_order(self):
        """Three levels of nesting with different key order → same hash."""
        p1 = {
            "level1": {
                "level2": [
                    {"level3_a": 1, "level3_b": 2},
                ],
            },
        }
        p2 = {
            "level1": {
                "level2": [
                    {"level3_b": 2, "level3_a": 1},
                ],
            },
        }
        self.assertEqual(_compute_payload_hash(p1), _compute_payload_hash(p2))

    def test_03_tuple_and_list_same_elements_same_hash(self):
        """Tuple and list with same elements produce identical hash."""
        p_tuple = {"items": (1, 2, 3)}
        p_list = {"items": [1, 2, 3]}
        self.assertEqual(
            _compute_payload_hash(p_tuple),
            _compute_payload_hash(p_list),
            "Tuple and list with same elements must produce same hash "
            "(both canonicalize to JSON array)",
        )

    def test_04_nested_tuple_and_list_same_hash(self):
        """Nested tuple/list combinations produce same hash."""
        p1 = {
            "data": (
                {"name": "Fake Player One", "tags": ("a", "b")},
                {"name": "Fake Player Two", "tags": ("c", "d")},
            ),
        }
        p2 = {
            "data": [
                {"name": "Fake Player One", "tags": ["a", "b"]},
                {"name": "Fake Player Two", "tags": ["c", "d"]},
            ],
        }
        self.assertEqual(_compute_payload_hash(p1), _compute_payload_hash(p2))

    def test_05_top_level_key_order_does_not_affect_hash(self):
        """Reordered top-level keys produce same hash."""
        p1 = {"teams": [], "matches": [], "standings": []}
        p2 = {"standings": [], "matches": [], "teams": []}
        self.assertEqual(_compute_payload_hash(p1), _compute_payload_hash(p2))

    def test_06_different_values_produce_different_hash(self):
        """Semantically different payloads must have different hashes."""
        p1 = {"score": 1}
        p2 = {"score": 2}
        self.assertNotEqual(_compute_payload_hash(p1), _compute_payload_hash(p2))

    def test_07_empty_payload_hash_is_stable(self):
        """Empty payload hash is deterministic and correct length."""
        h1 = _compute_payload_hash({})
        h2 = _compute_payload_hash({})
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_08_docstring_documents_canonicalization(self):
        """_compute_payload_hash docstring mentions canonicalization rules."""
        doc = _compute_payload_hash.__doc__ or ""
        self.assertIn("sort_keys", doc.lower() or doc)
        self.assertIn("tuple", doc.lower())
        self.assertIn("list", doc.lower())
        self.assertIn("json", doc.lower())


if __name__ == "__main__":
    unittest.main()
