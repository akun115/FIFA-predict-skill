"""Multi-provider fallback framework.

Builds an ordered provider chain per capability and walks it to attempt
data retrieval.  Every provider is blocked by default — no network calls,
no environment reads, no fabricated data.

**Default state:** All built-in providers are disabled or ``needs_more_info``.
Any call to ``execute_fallback_chain`` returns a ``FallbackResult`` with
comprehensive gap codes explaining why data could not be obtained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from oracle_core.provider_plugging import (
    ProviderApprovalStatus,
    ProviderPluginSpec,
    _ALL_BUILTIN_SPECS,
)


# ---------------------------------------------------------------------------
# Fallback request
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FallbackRequest:
    """Description of what data is being requested via the fallback chain."""

    capability: str
    """Which capability is being requested, e.g. ``"teams"``, ``"fixtures"``."""

    allow_live: bool = False
    """``True`` if live (network) providers are permitted for this request."""

    match_id: str | None = None
    """Optional match identifier to scope the request."""

    team_ids: tuple[str, ...] = ()
    """Optional team identifiers to scope the request."""


# ---------------------------------------------------------------------------
# Provider chain entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderChainEntry:
    """Record of one attempt (or blocked attempt) in a fallback chain."""

    provider_name: str
    """Name of the provider that was attempted."""

    approval_status: ProviderApprovalStatus
    """Approval status of this provider at the time of the attempt."""

    attempt_made: bool = False
    """``True`` if the provider was actually queried."""

    attempt_blocked_reason: str | None = None
    """Reason the attempt was blocked, if applicable, e.g. ``"provider_disabled"``."""

    result: dict[str, Any] | None = None
    """Result payload if the attempt succeeded, ``None`` otherwise."""


# ---------------------------------------------------------------------------
# Fallback result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FallbackResult:
    """Result of executing a fallback chain for a single capability request."""

    capability: str
    """Which capability was requested."""

    providers_requested: tuple[str, ...] = ()
    """Provider names that were considered for this request, in chain order."""

    providers_attempted: tuple[str, ...] = ()
    """Provider names that were actually queried (subset of requested)."""

    providers_used: tuple[str, ...] = ()
    """Provider names that returned usable data (subset of attempted)."""

    providers_blocked: tuple[str, ...] = ()
    """Provider names that were blocked from being queried."""

    success: bool = False
    """``True`` if usable data was obtained from at least one provider."""

    data: dict[str, Any] | None = None
    """Merged data obtained from successful providers, if any."""

    gaps: tuple[str, ...] = ()
    """Gap codes encountered during the fallback walk, e.g. ``"provider_disabled"``."""

    caveats: tuple[str, ...] = ()
    """Caveats or warnings about the fallback result."""

    provenance_chain: tuple[str, ...] = ()
    """Ordered list of provider names that were walked, in chain order."""

    network_called: bool = False
    """``True`` if any network request was made during this fallback.

    Defaults to ``False`` — network calls require explicit opt-in.
    """


# ---------------------------------------------------------------------------
# Chain building
# ---------------------------------------------------------------------------


def build_fallback_chain(
    capability: str,
    *,
    allow_live: bool = False,
) -> tuple[ProviderPluginSpec, ...]:
    """Build an ordered fallback chain of providers for the given capability.

    When ``allow_live`` is ``False`` (the default), only providers with
    approval status ``DISABLED`` or ``NEEDS_MORE_INFO`` are included — these
    serve as stubs that will be blocked at execution time.

    When ``allow_live`` is ``True``, all matching providers are included
    regardless of approval status.

    Only providers whose capabilities tuple includes the requested
    ``capability`` string are included in the chain.

    Returns a tuple of ``ProviderPluginSpec`` in chain order.
    """
    live_statuses = {
        ProviderApprovalStatus.SANDBOX_ONLY,
        ProviderApprovalStatus.LIVE_OPT_IN,
        ProviderApprovalStatus.APPROVED_FOR_LIVE_ADAPTER,
    }
    stub_statuses = {
        ProviderApprovalStatus.DISABLED,
        ProviderApprovalStatus.NEEDS_MORE_INFO,
    }

    candidates: list[ProviderPluginSpec] = []
    for spec in _ALL_BUILTIN_SPECS:
        if capability not in spec.capabilities:
            continue
        if allow_live and spec.approval_status in live_statuses | stub_statuses:
            candidates.append(spec)
        elif not allow_live and spec.approval_status in stub_statuses:
            candidates.append(spec)

    # Stable ordering: approved-first, then by name
    def _chain_key(spec: ProviderPluginSpec) -> tuple[int, str]:
        priority = {
            ProviderApprovalStatus.APPROVED_FOR_LIVE_ADAPTER: 0,
            ProviderApprovalStatus.LIVE_OPT_IN: 1,
            ProviderApprovalStatus.SANDBOX_ONLY: 2,
            ProviderApprovalStatus.NEEDS_MORE_INFO: 3,
            ProviderApprovalStatus.DISABLED: 4,
        }
        return (priority.get(spec.approval_status, 99), spec.provider_name)

    return tuple(sorted(candidates, key=_chain_key))


# ---------------------------------------------------------------------------
# Fallback execution
# ---------------------------------------------------------------------------

_DEFAULT_GAPS: tuple[str, ...] = (
    "provider_disabled",
    "provider_not_configured",
    "provider_not_approved",
    "credential_missing",
    "network_not_allowed",
)


def execute_fallback_chain(
    capability: str,
    *,
    allow_live: bool = False,
) -> FallbackResult:
    """Walk the fallback chain for ``capability`` and return the result.

    Each provider in the chain is evaluated: if it is blocked (disabled,
    needs-more-info, missing credentials, or network not allowed) the
    block reason is recorded.  No actual network requests are made.

    Returns a ``FallbackResult`` with all gaps populated.  ``success`` is
    always ``False`` in the default (all-disabled) configuration.
    """
    chain = build_fallback_chain(capability, allow_live=allow_live)
    if not chain:
        return FallbackResult(
            capability=capability,
            gaps=("no_provider_for_capability",),
            caveats=(f"no provider supports capability: {capability!r}",),
            provenance_chain=(),
            network_called=False,
        )

    providers_requested: list[str] = []
    providers_attempted: list[str] = []
    providers_used: list[str] = []
    providers_blocked: list[str] = []
    entries: list[ProviderChainEntry] = []
    all_gaps: list[str] = []
    all_caveats: list[str] = []
    provenance_chain: list[str] = []

    for spec in chain:
        providers_requested.append(spec.provider_name)
        provenance_chain.append(spec.provider_name)
        blocked_reasons: list[str] = []

        # -- approval checks --
        if spec.approval_status is ProviderApprovalStatus.DISABLED:
            blocked_reasons.append("provider_disabled")
            if "provider_disabled" not in all_gaps:
                all_gaps.append("provider_disabled")

        if spec.approval_status is ProviderApprovalStatus.NEEDS_MORE_INFO:
            blocked_reasons.append("provider_not_approved")
            if "provider_not_approved" not in all_gaps:
                all_gaps.append("provider_not_approved")

        if spec.approval_status not in (
            ProviderApprovalStatus.DISABLED,
            ProviderApprovalStatus.NEEDS_MORE_INFO,
        ):
            # Provider is further along the approval pipeline but still
            # not configured for live use in this environment.
            blocked_reasons.append("provider_not_configured")
            if "provider_not_configured" not in all_gaps:
                all_gaps.append("provider_not_configured")

        # -- credential checks --
        if spec.credential_policy is not None and spec.credential_policy.value != "none":
            blocked_reasons.append("credential_missing")
            if "credential_missing" not in all_gaps:
                all_gaps.append("credential_missing")

        # -- network checks --
        if not allow_live:
            blocked_reasons.append("network_not_allowed")
            if "network_not_allowed" not in all_gaps:
                all_gaps.append("network_not_allowed")

        # -- record the entry --
        if blocked_reasons:
            providers_blocked.append(spec.provider_name)
            entries.append(ProviderChainEntry(
                provider_name=spec.provider_name,
                approval_status=spec.approval_status,
                attempt_made=False,
                attempt_blocked_reason="; ".join(blocked_reasons),
            ))
        else:
            # Would attempt a real fetch — but without network/env this
            # path is unreachable in the default configuration.
            providers_attempted.append(spec.provider_name)
            blocked_reasons.append("provider_not_configured")
            providers_blocked.append(spec.provider_name)
            if "provider_not_configured" not in all_gaps:
                all_gaps.append("provider_not_configured")
            entries.append(ProviderChainEntry(
                provider_name=spec.provider_name,
                approval_status=spec.approval_status,
                attempt_made=True,
                attempt_blocked_reason="provider_not_configured",
            ))

    # Deduplicate and sort gaps for deterministic output
    seen: set[str] = set()
    ordered_gaps: list[str] = []
    for g in all_gaps:
        if g not in seen:
            seen.add(g)
            ordered_gaps.append(g)

    return FallbackResult(
        capability=capability,
        providers_requested=tuple(providers_requested),
        providers_attempted=tuple(providers_attempted),
        providers_used=tuple(providers_used),
        providers_blocked=tuple(providers_blocked),
        success=False,
        data=None,
        gaps=tuple(ordered_gaps),
        caveats=tuple(all_caveats),
        provenance_chain=tuple(provenance_chain),
        network_called=False,
    )


# ---------------------------------------------------------------------------
# Summary rendering
# ---------------------------------------------------------------------------


def fallback_summary(result: FallbackResult) -> str:
    """Return a human-readable summary of a fallback result."""
    lines: list[str] = [
        f"Fallback result for capability: {result.capability}",
        f"  Success: {result.success}",
    ]

    if result.providers_requested:
        lines.append(f"  Providers requested ({len(result.providers_requested)}):")
        for name in result.providers_requested:
            lines.append(f"    - {name}")

    if result.providers_attempted:
        lines.append(f"  Providers attempted ({len(result.providers_attempted)}):")
        for name in result.providers_attempted:
            lines.append(f"    - {name}")

    if result.providers_used:
        lines.append(f"  Providers used ({len(result.providers_used)}):")
        for name in result.providers_used:
            lines.append(f"    - {name}")

    if result.providers_blocked:
        lines.append(f"  Providers blocked ({len(result.providers_blocked)}):")
        for name in result.providers_blocked:
            lines.append(f"    - {name}")

    if result.gaps:
        lines.append(f"  Gaps ({len(result.gaps)}):")
        for gap in result.gaps:
            lines.append(f"    - {gap}")

    if result.caveats:
        lines.append("  Caveats:")
        for caveat in result.caveats:
            lines.append(f"    - {caveat}")

    if result.provenance_chain:
        lines.append(f"  Provenance chain: {' -> '.join(result.provenance_chain)}")

    lines.append(f"  Network called: {result.network_called}")

    return "\n".join(lines)
