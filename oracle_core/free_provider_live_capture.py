"""Live provider raw store capture — Data Service v1 (Patch 28).

Opt-in only.  Persists ``ProviderFetchResult`` to the local raw store
for replay and audit.  Default mode: ``allow_real_payload=False``
(fail-closed).  Live capture requires explicit ``allow_real_payload=True``.

No normalization.  No prediction integration.  No model probability effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oracle_core.data_service_providers import ProviderFetchResult
from oracle_core.data_service_store import (
    DataServiceLocalStore,
    InvalidStorePayloadError,
)


# ── Forbidden content patterns ──

_FORBIDDEN_MODEL_KEYS = frozenset({
    "result_probabilities", "expected_goals", "top_scores",
    "over_under", "advancement_probabilities", "prediction",
    "predicted_score", "model_probability", "model_probabilities",
})

_NARRATIVE_PATTERNS = (
    "I predict", "will win", "likely score", "predicted winner",
    "final score prediction", "forecast",
)

_UNREDACTED_KEY_RE = __import__("re").compile(r"/api/v1/json/123/")


# ── Metadata ──


@dataclass(frozen=True)
class StoredRawFetchMetadata:
    """Metadata about a persisted raw provider fetch result."""

    provider_name: str
    adapter_version: str
    capability: str
    fetched_at: str
    raw_payload_hash: str
    source_reference: str
    stored_at: str
    capture_reason: str
    payload_kind: str  # "synthetic" | "opt_in_live"
    redaction_status: str  # "redacted" | "not_applicable"
    model_boundary: dict = field(default_factory=lambda: {
        "affects_model": False,
        "report_only_or_context_only": True,
    })
    file_path: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Validation ──


def _check_no_forbidden_keys(payload: Any, path: str = "$") -> None:
    """Raise InvalidStorePayloadError if payload contains forbidden model keys."""
    if isinstance(payload, dict):
        for key, val in payload.items():
            if key in _FORBIDDEN_MODEL_KEYS:
                raise InvalidStorePayloadError(
                    f"Forbidden model output key '{key}' at {path}")
            _check_no_forbidden_keys(val, f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for i, item in enumerate(payload):
            _check_no_forbidden_keys(item, f"{path}[{i}]")


def _check_no_narrative(payload_str: str) -> None:
    """Raise InvalidStorePayloadError if payload contains narrative prediction."""
    lower = payload_str.lower()
    for pat in _NARRATIVE_PATTERNS:
        if pat.lower() in lower:
            raise InvalidStorePayloadError(
                f"Narrative prediction pattern '{pat}' found in payload")


def _check_no_api_key(payload_str: str) -> None:
    """Raise if payload contains common API key patterns."""
    import re
    for pat in (r'[a-f0-9]{32}', r'sk-[a-zA-Z0-9]{32,}'):
        if re.search(pat, payload_str):
            raise InvalidStorePayloadError(
                "Possible API key pattern found in payload")


def _check_source_redacted(source_ref: str) -> None:
    """Raise if source_reference contains unredacted live key."""
    if _UNREDACTED_KEY_RE.search(source_ref):
        raise InvalidStorePayloadError(
            "source_reference contains unredacted live key '/api/v1/json/123/' — "
            "must use '<public_test_key>' redaction")


# ── Public API ──


def persist_provider_fetch_result(
    store: DataServiceLocalStore,
    result: ProviderFetchResult,
    *,
    capture_reason: str = "",
    allow_real_payload: bool = False,
) -> StoredRawFetchMetadata:
    """Persist *result* to *store*'s raw fetch result storage.

    Args:
        store: An initialized ``DataServiceLocalStore``.
        result: The ``ProviderFetchResult`` to persist.
        capture_reason: Human-readable reason for this capture.
        allow_real_payload: If False, rejects non-synthetic payloads.

    Returns:
        ``StoredRawFetchMetadata`` with provenance and model boundary info.

    Raises:
        InvalidStorePayloadError: If payload violates safety rules.
    """
    source_ref = result.source_reference
    is_synthetic = source_ref.startswith("fixture://")

    if not allow_real_payload and not is_synthetic:
        raise InvalidStorePayloadError(
            "Real payload capture requires allow_real_payload=True.  "
            f"source_reference={source_ref!r} does not start with 'fixture://'."
        )

    # Validate content safety
    payload_str = str(result.payload)
    _check_no_forbidden_keys(result.payload)
    _check_no_narrative(payload_str)
    _check_no_api_key(payload_str)
    _check_source_redacted(source_ref)

    # Persist
    path = store.write_raw_fetch_result(result)

    return StoredRawFetchMetadata(
        provider_name=result.provider_name,
        adapter_version=result.adapter_version,
        capability=result.capability.value,
        fetched_at=result.fetched_at.isoformat(),
        raw_payload_hash=result.raw_payload_hash,
        source_reference=source_ref,
        stored_at=_now_iso(),
        capture_reason=capture_reason,
        payload_kind="synthetic" if is_synthetic else "opt_in_live",
        redaction_status="not_applicable" if is_synthetic else "redacted",
        file_path=str(path),
    )
