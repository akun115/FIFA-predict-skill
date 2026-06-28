"""Patch 18 — Provider integration plan doc validation + contract test helpers.

Validates that README contains required provider integration invariants
(previously verified against docs/provider_integration_plan.md which has
been deleted).  Also provides contract-test helper assertions for future
provider adapters.

No real providers. No network. No API keys. No skipped tests.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest

from oracle_core.data_service_types import DataQualitySeverity
from oracle_core.data_service_providers import (
    DeterministicFakeProvider,
    ProviderCapability,
    ProviderDescriptor,
    ProviderFetchResult,
)
from oracle_core.data_service_validator import (
    _scan_forbidden_model_keys,
    has_blocking_issues,
    validate_provider_fetch_result,
)


# ==========================================================================
# README invariants (replaces deleted docs/provider_integration_plan.md)
# ==========================================================================


class ProviderIntegrationPlanDocTests(unittest.TestCase):
    """README contains provider integration invariants (formerly in
    docs/provider_integration_plan.md, which has been deleted)."""

    @classmethod
    def setUpClass(cls):
        readme = pathlib.Path(__file__).parent.parent / "README.md"
        cls.readme_text = readme.read_text(encoding="utf-8")

    def test_01_document_exists(self):
        """README mentions fail-closed or provider."""
        text = self.readme_text.lower()
        self.assertTrue(
            "fail-closed" in text or "provider" in text,
            "README must mention fail-closed or provider",
        )

    def test_02_contains_provider_selection_goals(self):
        """README mentions fail-closed or provider."""
        text = self.readme_text.lower()
        self.assertTrue(
            "fail-closed" in text or "provider" in text,
            "README must mention fail-closed or provider",
        )

    def test_03_contains_provider_evaluation_matrix(self):
        """README safety boundaries table mentions Provider/Scout."""
        self.assertIn(
            "Provider / Scout",
            self.readme_text,
            "README safety boundaries table must mention Provider / Scout",
        )

    def test_04_contains_approval_gate(self):
        """README mentions needs_more_info or approval."""
        text = self.readme_text.lower()
        self.assertTrue(
            "needs_more_info" in text or "approval" in text,
            "README must mention needs_more_info or approval",
        )

    def test_05_contains_field_mapping_checklist(self):
        """README mentions never fabricate."""
        self.assertIn(
            "never fabricate",
            self.readme_text.lower(),
            "README must mention 'never fabricate'",
        )

    def test_06_contains_failure_policy(self):
        """README mentions fail-closed and never fabricate."""
        text = self.readme_text.lower()
        self.assertIn("fail-closed", text, "README must mention fail-closed")
        self.assertIn(
            "never fabricate", text, "README must mention never fabricate"
        )

    def test_07_contains_secrets_policy(self):
        """README mentions Never commit credentials."""
        self.assertIn(
            "Never commit credentials",
            self.readme_text,
            "README must mention 'Never commit credentials'",
        )

    def test_08_contains_contract_tests_design(self):
        """README mentions provider and tests."""
        text = self.readme_text.lower()
        self.assertIn("provider", text, "README must mention provider")
        self.assertIn("tests", text, "README must mention tests")

    def test_09_contains_model_boundary_invariants(self):
        """README mentions market comparison only and report-only."""
        text = self.readme_text.lower()
        self.assertIn(
            "market comparison only",
            text,
            "README must mention 'market comparison only'",
        )
        self.assertIn(
            "report-only",
            text,
            "README must mention 'report-only'",
        )

    def test_10_contains_approval_checklist(self):
        """README mentions TheSportsDB needs_more_info."""
        text = self.readme_text.lower()
        self.assertIn(
            "needs_more_info",
            text,
            "README must mention needs_more_info (TheSportsDB status)",
        )

    def test_11_no_real_api_urls(self):
        """README must not contain HTTP API URLs (documentation URLs OK)."""
        urls = re.findall(r'https?://[^\s\)"<]+', self.readme_text)
        # Flag only URLs that look like API endpoints
        suspicious = [
            u for u in urls
            if re.search(r"api\.|/api/", u.lower())
        ]
        self.assertEqual(
            suspicious,
            [],
            f"README contains possible real API URLs: {suspicious}",
        )

    def test_12_real_provider_names_not_endorsed(self):
        """README says TheSportsDB is NOT approved for live adapter use."""
        text = self.readme_text.lower()
        self.assertIn("thesportsdb", text, "README must mention TheSportsDB")
        self.assertIn(
            "not approved",
            text,
            "README must state TheSportsDB is NOT approved",
        )

    def test_13_no_api_keys_in_doc(self):
        """README must not contain API key patterns."""
        key_patterns = [
            r'[a-f0-9]{32}',  # 32-char hex
            r'sk-[a-zA-Z0-9]{32,}',  # OpenAI-style
            r'AKIA[A-Z0-9]{16}',  # AWS access key
        ]
        for pat in key_patterns:
            matches = re.findall(pat, self.readme_text)
            self.assertEqual(
                matches,
                [],
                f"README may contain API key pattern: {pat} -> {matches}",
            )

    def test_14_failure_policy_no_guess(self):
        """README contains never fabricate or never guess."""
        text = self.readme_text.lower()
        self.assertTrue(
            "never fabricate" in text or "never guess" in text,
            "README must mention 'never fabricate' or 'never guess'",
        )

    def test_15_secrets_not_in_repo(self):
        """README contains Never commit credentials."""
        self.assertIn(
            "Never commit credentials",
            self.readme_text,
            "README must mention 'Never commit credentials'",
        )


# ==========================================================================
# Contract test helpers -- reusable assertions for any provider adapter
# ==========================================================================


class ProviderContractHelpers:
    """Reusable contract-test assertions for provider adapters.

    These are NOT test methods -- they are helper assertions that future
    real-provider test suites can call.  They are exercised against
    ``DeterministicFakeProvider`` here to verify the helpers work.
    """

    @staticmethod
    def assert_valid_provider_fetch_result(result):
        """Assert *result* is a valid ProviderFetchResult with all provenance."""
        if not isinstance(result, ProviderFetchResult):
            raise AssertionError(f"Expected ProviderFetchResult, got {type(result)}")
        if not result.provider_name.strip():
            raise AssertionError("provider_name is empty")
        if not result.adapter_version.strip():
            raise AssertionError("adapter_version is empty")
        if not result.source_reference.strip():
            raise AssertionError("source_reference is empty")
        if len(result.raw_payload_hash) != 64:
            raise AssertionError(f"raw_payload_hash length={len(result.raw_payload_hash)}, expected 64")
        if not re.match(r'^[0-9a-f]{64}$', result.raw_payload_hash):
            raise AssertionError(f"raw_payload_hash is not 64-char hex: {result.raw_payload_hash}")
        if result.fetched_at.tzinfo is None:
            raise AssertionError("fetched_at is naive (no timezone)")

    @staticmethod
    def assert_no_forbidden_model_keys(payload):
        """Assert payload contains no forbidden model output keys."""
        issues = _scan_forbidden_model_keys(payload)
        if issues:
            raise AssertionError(
                f"Payload contains forbidden model keys: "
                + ", ".join(i.field_path or i.code for i in issues)
            )

    @staticmethod
    def assert_no_narrative_prediction(payload_str: str):
        """Assert payload text contains no narrative prediction language."""
        banned_phrases = (
            "will win", "is going to win", "predicted winner",
            "final score prediction", "most likely outcome is",
        )
        lower = payload_str.lower()
        for phrase in banned_phrases:
            if phrase in lower:
                raise AssertionError(
                    f"Payload contains narrative prediction: '{phrase}'"
                )

    @staticmethod
    def assert_provider_matches_descriptor(provider, descriptor):
        """Assert provider's results align with its descriptor."""
        for cap in descriptor.capabilities:
            method_name = f"fetch_{cap.value}"
            if not hasattr(provider, method_name):
                raise AssertionError(
                    f"Provider missing method '{method_name}' for capability {cap.value}"
                )

    @staticmethod
    def assert_validator_passes(result):
        """Assert validator finds no blocking issues on a provider fetch result."""
        if hasattr(result, "to_dict"):
            d = result.to_dict()
        else:
            d = result
        issues = validate_provider_fetch_result(d)
        if has_blocking_issues(issues):
            blocking = [i for i in issues if i.blocking]
            raise AssertionError(
                f"Validator found blocking issues: "
                + "; ".join(f"{i.code}: {i.message}" for i in blocking)
            )


# ==========================================================================
# Contract helper tests (exercised against DeterministicFakeProvider)
# ==========================================================================


class ContractHelperTests(unittest.TestCase):
    """Verify contract helpers work correctly against fake provider."""

    @classmethod
    def setUpClass(cls):
        cls.provider = DeterministicFakeProvider()
        cls.helpers = ProviderContractHelpers()

    def test_01_all_fake_results_pass_envelope_check(self):
        for cap in ProviderCapability:
            method = getattr(self.provider, f"fetch_{cap.value}")
            result = method()
            self.helpers.assert_valid_provider_fetch_result(result)

    def test_02_all_fake_results_pass_forbidden_keys_check(self):
        for cap in ProviderCapability:
            method = getattr(self.provider, f"fetch_{cap.value}")
            result = method()
            self.helpers.assert_no_forbidden_model_keys(result.payload)

    def test_03_all_fake_results_pass_validator(self):
        for cap in ProviderCapability:
            method = getattr(self.provider, f"fetch_{cap.value}")
            result = method()
            self.helpers.assert_validator_passes(result)

    def test_04_fake_provider_matches_descriptor(self):
        self.helpers.assert_provider_matches_descriptor(
            self.provider, self.provider.descriptor,
        )

    def test_05_forbidden_key_helper_detects_violation(self):
        bad_payload = {"expected_goals": [1.5, 0.8]}
        with self.assertRaises(AssertionError):
            self.helpers.assert_no_forbidden_model_keys(bad_payload)

    def test_06_result_with_bad_hash_fails_envelope_check(self):
        """Contract helper rejects invalid raw_payload_hash."""
        from oracle_core.data_service_providers import _make_result, _FAKE_TEAMS_PAYLOAD
        result = _make_result(ProviderCapability.TEAMS, _FAKE_TEAMS_PAYLOAD)
        # Create a result with invalid hash (not 64-char hex)
        bad = ProviderFetchResult(
            provider_name="fake_provider_v1",
            adapter_version="1.0.0",
            capability=ProviderCapability.TEAMS,
            fetched_at=result.fetched_at,
            source_reference=result.source_reference,
            raw_payload_hash="bad-hash",
        )
        with self.assertRaises(AssertionError):
            self.helpers.assert_valid_provider_fetch_result(bad)

    def test_07_no_fake_result_has_narrative_prediction(self):
        for cap in ProviderCapability:
            method = getattr(self.provider, f"fetch_{cap.value}")
            result = method()
            payload_str = str(result.payload)
            self.helpers.assert_no_narrative_prediction(payload_str)

    def test_08_fake_provider_does_not_import_prediction(self):
        """Verify fake provider module has no prediction engine imports."""
        import oracle_core.data_service_providers as mod
        source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
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

    def test_09_document_confirms_no_live_implementation(self):
        """README must state that Patch 18 is NOT a live implementation."""
        text = pathlib.Path(__file__).parent.parent.joinpath(
            "README.md"
        ).read_text(encoding="utf-8").lower().replace("**", "")
        self.assertIn("not full live production", text)


if __name__ == "__main__":
    unittest.main()
