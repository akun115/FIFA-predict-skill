"""Reusable provider contract harness — Data Service v1 (Patch 19).

Contract-test assertions for any ``ProviderAdapter``-like object.
All functions are offline, deterministic, and do not import the
prediction engine.  No network.  No real data.  No API keys.

Usage in a provider test suite::

    from tests.provider_contract_helpers import (
        assert_provider_descriptor_valid,
        assert_fetch_result_envelope_valid,
        assert_no_forbidden_model_output_keys,
        ...
    )
    provider = MyProviderAdapter()
    for cap in provider.descriptor.capabilities:
        result = getattr(provider, f"fetch_{cap.value}")()
        assert_fetch_result_envelope_valid(provider, cap, result)
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Any

from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderFetchResult,
)
from oracle_core.data_service_validator import (
    _scan_forbidden_model_keys,
    has_blocking_issues,
    validate_provider_fetch_result,
)


# ---------------------------------------------------------------------------
# Descriptor checks
# ---------------------------------------------------------------------------


def assert_provider_descriptor_valid(provider: Any, *, expected_name: str | None = None) -> None:
    """Assert *provider* exposes a valid ``ProviderDescriptor``."""
    desc = getattr(provider, "descriptor", None)
    if desc is None:
        raise AssertionError("Provider is missing 'descriptor' attribute")
    if not getattr(desc, "name", "").strip():
        raise AssertionError("descriptor.name is empty")
    if not getattr(desc, "adapter_version", "").strip():
        raise AssertionError("descriptor.adapter_version is empty")
    if expected_name is not None and desc.name != expected_name:
        raise AssertionError(
            f"descriptor.name={desc.name!r}, expected={expected_name!r}"
        )


def assert_provider_capabilities_complete(provider: Any) -> None:
    """Assert *provider.descriptor.capabilities* covers all 9 capabilities."""
    desc = provider.descriptor
    actual = set(desc.capabilities)
    expected = set(ProviderCapability)
    if actual != expected:
        missing = expected - actual
        extra = actual - expected
        msg_parts = []
        if missing:
            msg_parts.append(f"missing: {sorted(c.value for c in missing)}")
        if extra:
            msg_parts.append(f"unexpected: {sorted(c.value for c in extra)}")
        raise AssertionError("descriptor.capabilities incomplete: " + "; ".join(msg_parts))


# ---------------------------------------------------------------------------
# Fetch result envelope checks
# ---------------------------------------------------------------------------


def assert_fetch_result_envelope_valid(
    provider: Any,
    capability: ProviderCapability,
    result: Any,
) -> None:
    """Assert *result* is a valid ``ProviderFetchResult`` with correct metadata."""
    if not isinstance(result, ProviderFetchResult):
        raise AssertionError(
            f"fetch_{capability.value}() returned {type(result).__name__}, "
            f"expected ProviderFetchResult"
        )
    if result.capability != capability:
        raise AssertionError(
            f"fetch_{capability.value}() result.capability={result.capability.value}, "
            f"expected={capability.value}"
        )
    if result.provider_name != provider.descriptor.name:
        raise AssertionError(
            f"fetch_{capability.value}(): provider_name={result.provider_name!r} "
            f"!= descriptor.name={provider.descriptor.name!r}"
        )
    if result.adapter_version != provider.descriptor.adapter_version:
        raise AssertionError(
            f"fetch_{capability.value}(): adapter_version={result.adapter_version!r} "
            f"!= descriptor.adapter_version={provider.descriptor.adapter_version!r}"
        )
    if not result.source_reference.strip():
        raise AssertionError(f"fetch_{capability.value}(): source_reference is empty")
    if result.fetched_at.tzinfo is None:
        raise AssertionError(f"fetch_{capability.value}(): fetched_at is naive")


def assert_fetch_result_provenance_valid(provider: Any, result: ProviderFetchResult) -> None:
    """Assert *result* carries complete provenance metadata."""
    cap = result.capability.value
    desc = provider.descriptor
    if result.provider_name != desc.name:
        raise AssertionError(
            f"fetch_{cap}(): provider_name mismatch: {result.provider_name!r} vs {desc.name!r}"
        )
    if result.adapter_version != desc.adapter_version:
        raise AssertionError(
            f"fetch_{cap}(): adapter_version mismatch: {result.adapter_version!r} vs {desc.adapter_version!r}"
        )
    assert_raw_payload_hash_valid(result)
    assert_source_reference_present(result)
    assert_fetched_at_timezone_aware(result)


def assert_raw_payload_hash_valid(result: ProviderFetchResult) -> None:
    """Assert *result.raw_payload_hash* is a 64-char lowercase hex string."""
    h = result.raw_payload_hash
    if len(h) != 64:
        raise AssertionError(
            f"raw_payload_hash length={len(h)}, expected 64: {h!r}"
        )
    if not re.match(r'^[0-9a-f]{64}$', h):
        raise AssertionError(
            f"raw_payload_hash is not 64-char lowercase hex: {h!r}"
        )


def assert_source_reference_present(result: ProviderFetchResult) -> None:
    """Assert *result.source_reference* is non-empty."""
    if not result.source_reference.strip():
        raise AssertionError(
            f"fetch_{result.capability.value}(): source_reference is empty"
        )


def assert_fetched_at_timezone_aware(result: ProviderFetchResult) -> None:
    """Assert *result.fetched_at* is timezone-aware."""
    if result.fetched_at.tzinfo is None or result.fetched_at.utcoffset() is None:
        raise AssertionError(
            f"fetch_{result.capability.value}(): fetched_at is naive (no timezone)"
        )


# ---------------------------------------------------------------------------
# Model boundary checks
# ---------------------------------------------------------------------------


def assert_no_forbidden_model_output_keys(result: ProviderFetchResult) -> None:
    """Assert *result.payload* contains no forbidden model output keys."""
    issues = _scan_forbidden_model_keys(result.payload)
    if issues:
        raise AssertionError(
            f"fetch_{result.capability.value}(): payload contains forbidden model keys: "
            + ", ".join(i.field_path or i.code for i in issues)
        )


_NARRATIVE_PREDICTION_PATTERNS = re.compile(
    r"(I predict|will win|is going to win|predicted winner"
    r"|final score prediction|most likely outcome is"
    r"|likely score|expected winner|forecast)",
    re.IGNORECASE,
)


def assert_no_narrative_prediction(result: ProviderFetchResult) -> None:
    """Assert *result.payload* contains no narrative prediction language."""
    payload_str = str(result.payload)
    match = _NARRATIVE_PREDICTION_PATTERNS.search(payload_str)
    if match:
        raise AssertionError(
            f"fetch_{result.capability.value}(): payload contains narrative "
            f"prediction text: {match.group()!r}"
        )


# ---------------------------------------------------------------------------
# Validator integration
# ---------------------------------------------------------------------------


def assert_provider_result_passes_validator(result: ProviderFetchResult) -> None:
    """Assert the Data Service validator finds no blocking issues."""
    d = result.to_dict()
    issues = validate_provider_fetch_result(d)
    if has_blocking_issues(issues):
        blocking = [i for i in issues if i.blocking]
        raise AssertionError(
            f"fetch_{result.capability.value}(): validator found blocking issues: "
            + "; ".join(f"{i.code}: {i.message}" for i in blocking)
        )


# ---------------------------------------------------------------------------
# Import boundary check
# ---------------------------------------------------------------------------


_PREDICTION_MODULES = frozenset({
    "oracle_core.engine", "oracle_core.scoring", "oracle_core.fitted",
    "oracle_core.knockout", "oracle_core.tournament", "oracle_core.odds",
})


def assert_provider_does_not_import_prediction_runtime(
    module_path: str | pathlib.Path,
) -> None:
    """Parse *module_path* and verify it does not import prediction engine modules."""
    source = pathlib.Path(module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _PREDICTION_MODULES:
                    raise AssertionError(
                        f"{module_path} imports prediction module: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module in _PREDICTION_MODULES:
                raise AssertionError(
                    f"{module_path} imports from prediction module: {node.module}"
                )
