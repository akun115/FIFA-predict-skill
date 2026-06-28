"""Provider plugging kit — third-party providers can be registered without
touching the prediction engine.

Third-party data sources register themselves via ``ProviderPluginSpec``
descriptors.  The prediction engine never reads provider payloads directly;
it only reads normalized snapshots built by the data-service pipeline.

**Model Input Boundary (enforced):**
  Provider data — including odds, lineups, injuries, suspensions, and
  prematch signals — MUST NOT be used to modify model probabilities at
  any stage.  ``affects_model`` is enforced as ``False`` for all providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Provider approval status
# ---------------------------------------------------------------------------


class ProviderApprovalStatus(str, Enum):
    """Approval lifecycle for a third-party provider plugin.

    Values are ordered from least to most permissive.
    """

    DISABLED = "disabled"
    NEEDS_MORE_INFO = "needs_more_info"
    SANDBOX_ONLY = "sandbox_only"
    LIVE_OPT_IN = "live_opt_in"
    APPROVED_FOR_LIVE_ADAPTER = "approved_for_live_adapter"


# ---------------------------------------------------------------------------
# Provider credential policy
# ---------------------------------------------------------------------------


class ProviderCredentialPolicy(str, Enum):
    """What kind of credential the provider requires, if any."""

    NONE = "none"
    ENV_REQUIRED_LIVE_ONLY = "env_required_live_only"
    CONFIG_FILE_REQUIRED_LIVE_ONLY = "config_file_required_live_only"
    EXTERNAL_SECRET_MANAGER_REQUIRED = "external_secret_manager_required"


# ---------------------------------------------------------------------------
# Valid capability registry
# ---------------------------------------------------------------------------

_VALID_CAPABILITIES: frozenset[str] = frozenset({
    "fixtures",
    "teams",
    "standings",
    "injuries",
    "lineups",
    "suspensions",
    "weather",
    "odds",
    "news",
})


# ---------------------------------------------------------------------------
# Provider plugin spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderPluginSpec:
    """Descriptor for a third-party provider plugin.

    A spec declares what a provider can supply, its approval status,
    credential requirements, and whether it carries data that could
    theoretically affect model output (enforced ``False``).
    """

    provider_name: str
    """Unique identifier for this provider, e.g. ``"thesportsdb"``."""

    capabilities: tuple[str, ...] = ()
    """Capability strings this provider supports, e.g. ``("teams", "fixtures")``.

    Valid values: ``fixtures``, ``teams``, ``standings``, ``injuries``,
    ``lineups``, ``suspensions``, ``weather``, ``odds``, ``news``.
    """

    approval_status: ProviderApprovalStatus = ProviderApprovalStatus.DISABLED
    """Current approval status for this provider plugin."""

    credential_policy: ProviderCredentialPolicy = ProviderCredentialPolicy.NONE
    """Credential policy for this provider plugin."""

    context_only: bool = True
    """``True`` if this provider's data is context/report-only (never model input)."""

    affects_model: bool = False
    """**Enforced ``False``.**  Provider data must never modify model probabilities."""

    may_write_raw_payload: bool = False
    """``True`` if this provider is permitted to write raw payload blobs to storage."""

    def __post_init__(self) -> None:
        if not self.provider_name.strip():
            raise ValueError("provider_name must not be empty")
        if self.affects_model:
            raise ValueError(
                "affects_model must be False — provider data must never "
                "modify model probabilities"
            )
        for cap in self.capabilities:
            if cap not in _VALID_CAPABILITIES:
                raise ValueError(f"unknown capability: {cap!r}")


# ---------------------------------------------------------------------------
# Provider validation result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderValidationResult:
    """Result of validating a provider plugin spec."""

    provider_name: str
    """Which provider was validated."""

    success: bool
    """``True`` if the spec passes all validation checks."""

    gaps: tuple[str, ...] = ()
    """Gap codes identified during validation, e.g. ``("capability_not_covered",)``."""

    caveats: tuple[str, ...] = ()
    """Caveats or warnings about this provider."""

    coverage_summary: dict[str, Any] = field(default_factory=dict)
    """Summary of capability coverage, e.g. ``{"present": ["teams"], "missing": [...]}``."""

    provenance: str = ""
    """Description of where this spec definition originated."""

    redacted_references: tuple[str, ...] = ()
    """References that have been redacted (e.g. API docs, endpoints)."""

    def __post_init__(self) -> None:
        if not self.provider_name.strip():
            raise ValueError("provider_name must not be empty")


# ---------------------------------------------------------------------------
# Built-in provider specs
# ---------------------------------------------------------------------------

THESPORTSDB_SPEC = ProviderPluginSpec(
    provider_name="thesportsdb",
    approval_status=ProviderApprovalStatus.NEEDS_MORE_INFO,
    capabilities=("teams", "fixtures"),
    context_only=True,
    affects_model=False,
    may_write_raw_payload=False,
)

GENERIC_PAID_FIXTURE_SPEC = ProviderPluginSpec(
    provider_name="generic_paid_fixture",
    approval_status=ProviderApprovalStatus.DISABLED,
    capabilities=("fixtures", "teams", "standings"),
    credential_policy=ProviderCredentialPolicy.ENV_REQUIRED_LIVE_ONLY,
    context_only=True,
    affects_model=False,
    may_write_raw_payload=False,
)

GENERIC_LINEUP_INJURY_SPEC = ProviderPluginSpec(
    provider_name="generic_lineup_injury",
    approval_status=ProviderApprovalStatus.DISABLED,
    capabilities=("lineups", "injuries", "suspensions"),
    context_only=True,
    affects_model=False,
    may_write_raw_payload=False,
)

GENERIC_WEATHER_SPEC = ProviderPluginSpec(
    provider_name="generic_weather",
    approval_status=ProviderApprovalStatus.DISABLED,
    capabilities=("weather",),
    context_only=True,
    affects_model=False,
    may_write_raw_payload=False,
)

GENERIC_NEWS_SPEC = ProviderPluginSpec(
    provider_name="generic_news",
    approval_status=ProviderApprovalStatus.DISABLED,
    capabilities=("news",),
    context_only=True,
    affects_model=False,
    may_write_raw_payload=False,
)

GENERIC_ODDS_SPEC = ProviderPluginSpec(
    provider_name="generic_odds",
    approval_status=ProviderApprovalStatus.DISABLED,
    capabilities=("odds",),
    context_only=True,
    affects_model=False,
    may_write_raw_payload=False,
)

_ALL_BUILTIN_SPECS: tuple[ProviderPluginSpec, ...] = (
    THESPORTSDB_SPEC,
    GENERIC_PAID_FIXTURE_SPEC,
    GENERIC_LINEUP_INJURY_SPEC,
    GENERIC_WEATHER_SPEC,
    GENERIC_NEWS_SPEC,
    GENERIC_ODDS_SPEC,
)

_SPEC_BY_NAME: dict[str, ProviderPluginSpec] = {
    spec.provider_name: spec for spec in _ALL_BUILTIN_SPECS
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_provider_spec(spec: ProviderPluginSpec) -> ProviderValidationResult:
    """Validate a provider plugin spec and return a structured result.

    Checks performed:
      * ``provider_name`` is non-empty.
      * All capabilities are known strings.
      * ``affects_model`` is ``False`` (enforced).

    Returns a ``ProviderValidationResult`` with coverage summary and any
    gaps or caveats identified.
    """
    gaps: list[str] = []
    caveats: list[str] = []

    if not spec.provider_name.strip():
        gaps.append("provider_name_empty")

    unknown = [cap for cap in spec.capabilities if cap not in _VALID_CAPABILITIES]
    if unknown:
        gaps.append(f"unknown_capabilities:{','.join(sorted(unknown))}")

    if spec.affects_model:
        gaps.append("affects_model_not_allowed")

    if spec.approval_status is ProviderApprovalStatus.DISABLED:
        caveats.append("provider_is_disabled")

    if spec.approval_status is ProviderApprovalStatus.NEEDS_MORE_INFO:
        caveats.append("provider_needs_more_info")

    if spec.credential_policy is not ProviderCredentialPolicy.NONE:
        caveats.append(f"credentials_required:{spec.credential_policy.value}")

    present_caps = sorted(spec.capabilities)
    missing_caps = sorted(_VALID_CAPABILITIES - set(spec.capabilities))

    coverage_summary: dict[str, Any] = {
        "total_valid_capabilities": len(_VALID_CAPABILITIES),
        "present": present_caps,
        "missing": missing_caps,
    }

    return ProviderValidationResult(
        provider_name=spec.provider_name,
        success=len(gaps) == 0,
        gaps=tuple(gaps),
        caveats=tuple(caveats),
        coverage_summary=coverage_summary,
        provenance="built-in spec definition",
        redacted_references=(),
    )


def list_available_providers() -> tuple[ProviderPluginSpec, ...]:
    """Return all built-in provider plugin specs."""
    return _ALL_BUILTIN_SPECS


def get_provider_spec(name: str) -> ProviderPluginSpec:
    """Look up a built-in provider spec by name.

    Raises ``ValueError`` if no provider with the given name exists.
    """
    try:
        return _SPEC_BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown provider: {name!r}") from None
