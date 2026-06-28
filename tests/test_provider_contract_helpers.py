"""Patch 19 — Provider contract harness tests against DeterministicFakeProvider.

Covers all 9 ProviderCapability values.  All tests offline, no real data.
No skipped tests.
"""

from __future__ import annotations

import ast
import pathlib
import unittest
from datetime import datetime

from oracle_core.data_service_providers import (
    DeterministicFakeProvider,
    ProviderCapability,
    ProviderFetchResult,
)

from tests.provider_contract_helpers import (
    assert_fetch_result_envelope_valid,
    assert_fetch_result_provenance_valid,
    assert_fetched_at_timezone_aware,
    assert_no_forbidden_model_output_keys,
    assert_no_narrative_prediction,
    assert_provider_capabilities_complete,
    assert_provider_descriptor_valid,
    assert_provider_does_not_import_prediction_runtime,
    assert_provider_result_passes_validator,
    assert_raw_payload_hash_valid,
    assert_source_reference_present,
)


# ==========================================================================
# Descriptor contract
# ==========================================================================


class DescriptorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def test_01_descriptor_valid(self):
        assert_provider_descriptor_valid(self.provider)

    def test_02_capabilities_complete(self):
        assert_provider_capabilities_complete(self.provider)

    def test_03_descriptor_name_matches_expected(self):
        assert_provider_descriptor_valid(
            self.provider, expected_name="fake_provider_v1",
        )

    def test_04_bad_descriptor_name_rejected(self):
        class BadProvider:
            descriptor = type("D", (), {"name": "", "adapter_version": "1.0.0"})()

        with self.assertRaises(AssertionError):
            assert_provider_descriptor_valid(BadProvider())

    def test_05_missing_descriptor_rejected(self):
        with self.assertRaises(AssertionError):
            assert_provider_descriptor_valid(object())


# ==========================================================================
# Envelope contract — all 9 capabilities
# ==========================================================================


class EnvelopeContractAllCapabilitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def test_01_teams_envelope_valid(self):
        r = self.provider.fetch_teams()
        assert_fetch_result_envelope_valid(self.provider, ProviderCapability.TEAMS, r)

    def test_02_matches_envelope_valid(self):
        r = self.provider.fetch_matches()
        assert_fetch_result_envelope_valid(self.provider, ProviderCapability.MATCHES, r)

    def test_03_group_standings_envelope_valid(self):
        r = self.provider.fetch_group_standings()
        assert_fetch_result_envelope_valid(self.provider, ProviderCapability.GROUP_STANDINGS, r)

    def test_04_knockout_bracket_envelope_valid(self):
        r = self.provider.fetch_knockout_bracket()
        assert_fetch_result_envelope_valid(self.provider, ProviderCapability.KNOCKOUT_BRACKET, r)

    def test_05_odds_envelope_valid(self):
        r = self.provider.fetch_odds()
        assert_fetch_result_envelope_valid(self.provider, ProviderCapability.ODDS, r)

    def test_06_lineups_envelope_valid(self):
        r = self.provider.fetch_lineups()
        assert_fetch_result_envelope_valid(self.provider, ProviderCapability.LINEUPS, r)

    def test_07_injuries_envelope_valid(self):
        r = self.provider.fetch_injuries()
        assert_fetch_result_envelope_valid(self.provider, ProviderCapability.INJURIES, r)

    def test_08_suspensions_envelope_valid(self):
        r = self.provider.fetch_suspensions()
        assert_fetch_result_envelope_valid(self.provider, ProviderCapability.SUSPENSIONS, r)

    def test_09_prematch_signals_envelope_valid(self):
        r = self.provider.fetch_prematch_signals()
        assert_fetch_result_envelope_valid(self.provider, ProviderCapability.PREMATCH_SIGNALS, r)


# ==========================================================================
# Provenance contract — all 9 capabilities
# ==========================================================================


class ProvenanceContractAllCapabilitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def _check(self, cap):
        method = getattr(self.provider, f"fetch_{cap.value}")
        assert_fetch_result_provenance_valid(self.provider, method())

    def test_01_teams(self): self._check(ProviderCapability.TEAMS)
    def test_02_matches(self): self._check(ProviderCapability.MATCHES)
    def test_03_standings(self): self._check(ProviderCapability.GROUP_STANDINGS)
    def test_04_bracket(self): self._check(ProviderCapability.KNOCKOUT_BRACKET)
    def test_05_odds(self): self._check(ProviderCapability.ODDS)
    def test_06_lineups(self): self._check(ProviderCapability.LINEUPS)
    def test_07_injuries(self): self._check(ProviderCapability.INJURIES)
    def test_08_suspensions(self): self._check(ProviderCapability.SUSPENSIONS)
    def test_09_signals(self): self._check(ProviderCapability.PREMATCH_SIGNALS)


# ==========================================================================
# Forbidden model output keys — all 9 capabilities
# ==========================================================================


class ForbiddenModelKeysAllCapabilitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def _check(self, cap):
        method = getattr(self.provider, f"fetch_{cap.value}")
        assert_no_forbidden_model_output_keys(method())

    def test_01_teams(self): self._check(ProviderCapability.TEAMS)
    def test_02_matches(self): self._check(ProviderCapability.MATCHES)
    def test_03_standings(self): self._check(ProviderCapability.GROUP_STANDINGS)
    def test_04_bracket(self): self._check(ProviderCapability.KNOCKOUT_BRACKET)
    def test_05_odds(self): self._check(ProviderCapability.ODDS)
    def test_06_lineups(self): self._check(ProviderCapability.LINEUPS)
    def test_07_injuries(self): self._check(ProviderCapability.INJURIES)
    def test_08_suspensions(self): self._check(ProviderCapability.SUSPENSIONS)
    def test_09_signals(self): self._check(ProviderCapability.PREMATCH_SIGNALS)


# ==========================================================================
# Narrative prediction — all 9 capabilities
# ==========================================================================


class NarrativePredictionAllCapabilitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def _check(self, cap):
        method = getattr(self.provider, f"fetch_{cap.value}")
        assert_no_narrative_prediction(method())

    def test_01_teams(self): self._check(ProviderCapability.TEAMS)
    def test_02_matches(self): self._check(ProviderCapability.MATCHES)
    def test_03_standings(self): self._check(ProviderCapability.GROUP_STANDINGS)
    def test_04_bracket(self): self._check(ProviderCapability.KNOCKOUT_BRACKET)
    def test_05_odds(self): self._check(ProviderCapability.ODDS)
    def test_06_lineups(self): self._check(ProviderCapability.LINEUPS)
    def test_07_injuries(self): self._check(ProviderCapability.INJURIES)
    def test_08_suspensions(self): self._check(ProviderCapability.SUSPENSIONS)
    def test_09_signals(self): self._check(ProviderCapability.PREMATCH_SIGNALS)


# ==========================================================================
# Validator pass — all 9 capabilities
# ==========================================================================


class ValidatorAllCapabilitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()

    def _check(self, cap):
        method = getattr(self.provider, f"fetch_{cap.value}")
        assert_provider_result_passes_validator(method())

    def test_01_teams(self): self._check(ProviderCapability.TEAMS)
    def test_02_matches(self): self._check(ProviderCapability.MATCHES)
    def test_03_standings(self): self._check(ProviderCapability.GROUP_STANDINGS)
    def test_04_bracket(self): self._check(ProviderCapability.KNOCKOUT_BRACKET)
    def test_05_odds(self): self._check(ProviderCapability.ODDS)
    def test_06_lineups(self): self._check(ProviderCapability.LINEUPS)
    def test_07_injuries(self): self._check(ProviderCapability.INJURIES)
    def test_08_suspensions(self): self._check(ProviderCapability.SUSPENSIONS)
    def test_09_signals(self): self._check(ProviderCapability.PREMATCH_SIGNALS)


# ==========================================================================
# Negative tests — bad inputs rejected by contract helpers
# ==========================================================================


class NegativeContractTests(unittest.TestCase):
    """Contract helpers must reject deliberately bad inputs."""

    def _valid_result(self):
        return DeterministicFakeProvider().fetch_teams()

    # ── Bad hash ──

    def test_01_bad_raw_payload_hash_rejected(self):
        r = self._valid_result()
        bad = ProviderFetchResult(
            provider_name=r.provider_name,
            adapter_version=r.adapter_version,
            capability=r.capability,
            fetched_at=r.fetched_at,
            source_reference=r.source_reference,
            raw_payload_hash="bad-hash",
        )
        with self.assertRaises(AssertionError):
            assert_raw_payload_hash_valid(bad)

    def test_02_short_hash_rejected(self):
        import types
        bad = types.SimpleNamespace(
            raw_payload_hash="aa",
            capability=ProviderCapability.TEAMS,
        )
        with self.assertRaises(AssertionError):
            assert_raw_payload_hash_valid(bad)

    # ── Missing source_reference ──

    def test_03_missing_source_reference_rejected(self):
        import types
        bad = types.SimpleNamespace(
            source_reference="",
            capability=ProviderCapability.TEAMS,
        )
        with self.assertRaises(AssertionError):
            assert_source_reference_present(bad)

    # ── Naive fetched_at ──

    def test_04_naive_fetched_at_rejected(self):
        import types
        bad = types.SimpleNamespace(
            fetched_at=datetime(2026, 6, 15, 12, 0, 0),  # naive
            capability=ProviderCapability.TEAMS,
        )
        with self.assertRaises(AssertionError):
            assert_fetched_at_timezone_aware(bad)

    # ── Forbidden keys ──

    def test_05_expected_goals_rejected(self):
        r = self._valid_result()
        # Use a wrapper to inject forbidden key into payload text
        import types
        data = r.to_dict()
        data["payload"] = {"expected_goals": [1.5, 0.8]}
        bad = types.SimpleNamespace(
            capability=r.capability, payload=data["payload"],
            raw_payload_hash=r.raw_payload_hash,
        )
        # assert_no_forbidden_model_output_keys checks payload directly
        with self.assertRaises(AssertionError):
            assert_no_forbidden_model_output_keys(bad)

    def test_06_result_probabilities_rejected(self):
        import types
        bad = types.SimpleNamespace(
            capability=ProviderCapability.TEAMS,
            payload={"result_probabilities": {"home": 0.5}},
            raw_payload_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        with self.assertRaises(AssertionError):
            assert_no_forbidden_model_output_keys(bad)

    def test_07_advancement_probabilities_rejected(self):
        import types
        bad = types.SimpleNamespace(
            capability=ProviderCapability.TEAMS,
            payload={"advancement_probabilities": {"team_a": 0.7}},
            raw_payload_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        with self.assertRaises(AssertionError):
            assert_no_forbidden_model_output_keys(bad)

    # ── Narrative prediction ──

    def test_08_narrative_i_predict_rejected(self):
        import types
        bad = types.SimpleNamespace(
            capability=ProviderCapability.TEAMS,
            payload={"summary": "I predict Brazil will win this match easily."},
            raw_payload_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        with self.assertRaises(AssertionError):
            assert_no_narrative_prediction(bad)

    def test_09_narrative_will_win_rejected(self):
        import types
        bad = types.SimpleNamespace(
            capability=ProviderCapability.TEAMS,
            payload={"note": "The home team will win comfortably."},
            raw_payload_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        with self.assertRaises(AssertionError):
            assert_no_narrative_prediction(bad)

    def test_10_narrative_likely_score_rejected(self):
        import types
        bad = types.SimpleNamespace(
            capability=ProviderCapability.TEAMS,
            payload={"headline": "Likely score: 2-0 to the favorites."},
            raw_payload_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        with self.assertRaises(AssertionError):
            assert_no_narrative_prediction(bad)


# ==========================================================================
# Import boundary — contract helpers are prediction-free
# ==========================================================================


class ContractHelpersImportBoundaryTests(unittest.TestCase):
    def test_01_helpers_do_not_import_prediction(self):
        """provider_contract_helpers module does not import prediction engine."""
        mod_path = pathlib.Path(__file__).parent / "provider_contract_helpers.py"
        assert_provider_does_not_import_prediction_runtime(mod_path)

    def test_02_fake_provider_module_clean(self):
        mod_path = (pathlib.Path(__file__).parent.parent
                    / "oracle_core" / "data_service_providers.py")
        assert_provider_does_not_import_prediction_runtime(mod_path)

    def test_03_validator_module_clean(self):
        mod_path = (pathlib.Path(__file__).parent.parent
                    / "oracle_core" / "data_service_validator.py")
        assert_provider_does_not_import_prediction_runtime(mod_path)

    def test_04_store_module_clean(self):
        mod_path = (pathlib.Path(__file__).parent.parent
                    / "oracle_core" / "data_service_store.py")
        assert_provider_does_not_import_prediction_runtime(mod_path)


if __name__ == "__main__":
    unittest.main()
