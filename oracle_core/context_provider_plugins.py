"""Context provider plugging kit — lineups, injuries, suspensions, news, weather.

Plugin specs, request/response types, and default disabled adapters for
context data providers.  All providers are disabled by default.  No network.
No env reads.  No fake data.

All context data is ``report_only=True``, ``affects_model=False`` — enforced
at the type level.  Context data NEVER adjusts xG or model probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Plugin spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextProviderPluginSpec:
    """Specification for a context provider plugin.

    All providers start disabled (``approval_status="disabled"``).
    ``report_only`` is always ``True``.  ``affects_model`` is always ``False``.
    """

    provider_name: str
    context_type: str = "news"
    """Type of context: ``"lineups"``, ``"injuries"``, ``"suspensions"``,
    ``"news"``, ``"weather"``."""

    configured: bool = False
    requires_api_key: bool = True
    approval_status: str = "disabled"
    report_only: bool = True
    affects_model: bool = False

    def __post_init__(self) -> None:
        valid_types = ("lineups", "injuries", "suspensions", "news", "weather")
        if self.context_type not in valid_types:
            raise ValueError(
                f"context_type must be one of {valid_types}, "
                f"got '{self.context_type}'"
            )
        if not self.report_only:
            raise ValueError(
                "ContextProviderPluginSpec.report_only must always be True. "
                "Context data is report-only — it must not affect model output."
            )
        if self.affects_model:
            raise ValueError(
                "ContextProviderPluginSpec.affects_model must always be False. "
                "Context data must not adjust xG or model probabilities."
            )


# ---------------------------------------------------------------------------
# Plugin-level request / response
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextProviderRequest:
    """A plugin-level request for context data.

    ``context_type`` specifies what to fetch (lineups, injuries, etc.).
    ``allow_live`` is a per-request opt-in flag.
    """

    context_type: str
    match_id: str
    team_ids: tuple[str, ...] = ()
    allow_live: bool = False

    def __post_init__(self) -> None:
        valid_types = ("lineups", "injuries", "suspensions", "news", "weather")
        if self.context_type not in valid_types:
            raise ValueError(
                f"context_type must be one of {valid_types}, "
                f"got '{self.context_type}'"
            )
        if not self.match_id.strip():
            raise ValueError("match_id must not be empty")


@dataclass(frozen=True)
class ContextProviderResponse:
    """Response from a context provider fetch.

    When ``success`` is ``False``, ``data`` is ``None`` and gaps/caveats
    describe the failure.

    ``freshness`` indicates how up-to-date the data is.
    ``provenance`` describes where the data originated.
    ``redacted_references`` is a tuple of references that were redacted
    (e.g. for privacy or licensing reasons).
    """

    provider_name: str
    context_type: str
    success: bool
    data: dict[str, Any] | None = None
    """Provider-shaped context data dict.  ``None`` when fetch fails."""

    gaps: tuple[str, ...] = ()
    """Gaps that could not be filled (e.g. no provider configured)."""

    caveats: tuple[str, ...] = ()
    """Caveats / warnings about the context fetch."""

    network_called: bool = False
    """Whether a network call was made during this fetch."""

    freshness: str = "unknown"
    """How fresh the data is: ``"stale"``, ``"fresh"``, or ``"unknown"``."""

    provenance: str = ""
    """Description of where the data originated."""

    redacted_references: tuple[str, ...] = ()
    """References that were redacted (e.g. privacy, licensing)."""

    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When the fetch completed."""

    def __post_init__(self) -> None:
        valid_freshness = ("stale", "fresh", "unknown")
        if self.freshness not in valid_freshness:
            raise ValueError(
                f"freshness must be one of {valid_freshness}, "
                f"got '{self.freshness}'"
            )
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")


# ---------------------------------------------------------------------------
# Built-in specs (all disabled)
# ---------------------------------------------------------------------------

DISABLED_LINEUPS_SPEC = ContextProviderPluginSpec(
    provider_name="disabled_lineups",
    context_type="lineups",
    configured=False,
    requires_api_key=True,
    approval_status="disabled",
)

DISABLED_INJURIES_SPEC = ContextProviderPluginSpec(
    provider_name="disabled_injuries",
    context_type="injuries",
    configured=False,
    requires_api_key=True,
    approval_status="disabled",
)

DISABLED_SUSPENSIONS_SPEC = ContextProviderPluginSpec(
    provider_name="disabled_suspensions",
    context_type="suspensions",
    configured=False,
    requires_api_key=True,
    approval_status="disabled",
)

DISABLED_NEWS_SPEC = ContextProviderPluginSpec(
    provider_name="disabled_news",
    context_type="news",
    configured=False,
    requires_api_key=True,
    approval_status="disabled",
)

DISABLED_WEATHER_SPEC = ContextProviderPluginSpec(
    provider_name="disabled_weather",
    context_type="weather",
    configured=False,
    requires_api_key=True,
    approval_status="disabled",
)


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


class ContextPluginAdapter(Protocol):
    """Protocol that all context plugin adapters implement."""

    PROVIDER_NAME: str
    CONTEXT_TYPE: str

    def fetch(self, request: ContextProviderRequest) -> ContextProviderResponse:
        """Fetch context data for *request*.

        Returns a ``ContextProviderResponse``.  Never raises.
        """
        ...


# ---------------------------------------------------------------------------
# DisabledContextPluginAdapter — default fail-closed adapter
# ---------------------------------------------------------------------------


class DisabledContextPluginAdapter:
    """Default adapter — always returns fail-closed response.

    No network.  No env reads.  Never fabricates data.
    """

    PROVIDER_NAME = "disabled"

    def __init__(self, context_type: str = "news") -> None:
        valid_types = ("lineups", "injuries", "suspensions", "news", "weather")
        if context_type not in valid_types:
            raise ValueError(
                f"context_type must be one of {valid_types}, "
                f"got '{context_type}'"
            )
        self._context_type = context_type

    @property
    def CONTEXT_TYPE(self) -> str:
        return self._context_type

    def fetch(self, request: ContextProviderRequest) -> ContextProviderResponse:
        now = datetime.now(timezone.utc)
        return ContextProviderResponse(
            provider_name=self.PROVIDER_NAME,
            context_type=self._context_type,
            success=False,
            data=None,
            gaps=("context_provider_disabled",),
            caveats=(
                f"Context provider '{self._context_type}' is disabled by default. "
                f"No context fetch performed. "
                f"{self._context_type.capitalize()} data unavailable.",
            ),
            network_called=False,
            freshness="unknown",
            provenance="",
            redacted_references=(),
            fetched_at=now,
        )


# ---------------------------------------------------------------------------
# List context providers
# ---------------------------------------------------------------------------


def list_context_providers() -> tuple[ContextProviderPluginSpec, ...]:
    """Return all built-in context provider plugin specs.

    Returns:
        Tuple of ``ContextProviderPluginSpec``, all disabled by default.
    """
    return (
        DISABLED_LINEUPS_SPEC,
        DISABLED_INJURIES_SPEC,
        DISABLED_SUSPENSIONS_SPEC,
        DISABLED_NEWS_SPEC,
        DISABLED_WEATHER_SPEC,
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_context_adapter(
    provider_name: str,
    context_type: str,
    *,
    allow_live: bool = False,
) -> ContextPluginAdapter:
    """Factory: create a context plugin adapter.

    Always disabled unless explicit opt-in via ``allow_live=True``.
    Even with opt-in, only a stub adapter is returned — no real context
    provider is configured by default.

    Args:
        provider_name: Name of the context provider (ignored in current
            version).
        context_type: The type of context
            (``"lineups"``, ``"injuries"``, ``"suspensions"``,
            ``"news"``, ``"weather"``).
        allow_live: If ``False`` (default), returns
            ``DisabledContextPluginAdapter``.

    Returns:
        - ``DisabledContextPluginAdapter`` if ``allow_live`` is ``False``.
        - ``_StubRealContextAdapter`` if ``allow_live`` is ``True`` (no real
          provider configured yet).
    """
    if not allow_live:
        return DisabledContextPluginAdapter(context_type=context_type)

    return _StubRealContextAdapter(context_type=context_type)


class _StubRealContextAdapter:
    """Stub adapter for future real context providers.

    Always returns a fail-closed response indicating no context provider is
    configured.  Never fakes data.
    """

    PROVIDER_NAME = "stub_real"
    CONTEXT_TYPE = "unknown"

    def __init__(self, context_type: str = "news") -> None:
        valid_types = ("lineups", "injuries", "suspensions", "news", "weather")
        if context_type not in valid_types:
            raise ValueError(
                f"context_type must be one of {valid_types}, "
                f"got '{context_type}'"
            )
        self.CONTEXT_TYPE = context_type

    def fetch(self, request: ContextProviderRequest) -> ContextProviderResponse:
        now = datetime.now(timezone.utc)
        return ContextProviderResponse(
            provider_name=self.PROVIDER_NAME,
            context_type=self.CONTEXT_TYPE,
            success=False,
            data=None,
            gaps=("context_provider_not_configured",),
            caveats=(
                f"No real context provider configured for "
                f"'{self.CONTEXT_TYPE}'. "
                f"Context data unavailable.",
            ),
            network_called=False,
            freshness="unknown",
            provenance="",
            redacted_references=(),
            fetched_at=now,
        )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def execute_context_fetch(
    adapter: ContextPluginAdapter,
    request: ContextProviderRequest,
) -> ContextProviderResponse:
    """Run *adapter*.fetch(*request*), catching errors.

    Args:
        adapter: A ``ContextPluginAdapter`` implementation.
        request: The ``ContextProviderRequest`` to send.

    Returns:
        ``ContextProviderResponse`` — the adapter's response on success, or a
        fail-closed response with gaps/caveats on error.

    Never raises.  Never fabricates data on failure.
    """
    try:
        return adapter.fetch(request)
    except Exception as exc:
        now = datetime.now(timezone.utc)
        return ContextProviderResponse(
            provider_name=getattr(adapter, "PROVIDER_NAME", "unknown"),
            context_type=getattr(adapter, "CONTEXT_TYPE", "unknown"),
            success=False,
            data=None,
            gaps=("context_fetch_error",),
            caveats=(
                f"Context fetch raised {type(exc).__name__}: {exc}",
            ),
            network_called=False,
            freshness="unknown",
            provenance="",
            redacted_references=(),
            fetched_at=now,
        )


# ---------------------------------------------------------------------------
# Report section builder
# ---------------------------------------------------------------------------

_CONTEXT_TYPE_LABELS: dict[str, str] = {
    "lineups": "Lineups",
    "injuries": "Injuries",
    "suspensions": "Suspensions",
    "news": "News",
    "weather": "Weather",
}


def context_to_report_section(
    response: ContextProviderResponse,
) -> str:
    """Format a context provider response as a report section string.

    Args:
        response: The ``ContextProviderResponse`` to format.

    Returns:
        A formatted string section suitable for inclusion in a prediction
        report.  When the provider is disabled or fails, returns a section
        stating that context data is unavailable.
    """
    label = _CONTEXT_TYPE_LABELS.get(response.context_type, response.context_type)
    header = f"【{label} Context】"

    if not response.success or response.data is None:
        lines = [
            header,
            f"  Provider: {response.provider_name}",
            f"  Status: Unavailable",
            f"  Freshness: {response.freshness}",
        ]
        if response.gaps:
            lines.append(f"  Gaps: {', '.join(response.gaps)}")
        if response.caveats:
            lines.append(f"  Caveats: {'; '.join(response.caveats)}")
        if response.redacted_references:
            lines.append(
                f"  Redacted references: {len(response.redacted_references)}"
            )
        lines.append(
            "  说明：Context 数据为 report-only，不影响模型输出。"
        )
        lines.append("")
        return "\n".join(lines)

    lines = [
        header,
        f"  Provider: {response.provider_name}",
        f"  Freshness: {response.freshness}",
        f"  Provenance: {response.provenance or 'N/A'}",
    ]

    if response.data:
        for key, value in response.data.items():
            lines.append(f"  {key}: {value}")

    if response.gaps:
        lines.append(f"  Gaps: {', '.join(response.gaps)}")
    if response.caveats:
        lines.append(f"  Caveats: {'; '.join(response.caveats)}")
    if response.redacted_references:
        lines.append(
            f"  Redacted references: {len(response.redacted_references)}"
        )

    lines.append(
        "  说明：Context 数据为 report-only，不影响 xG、概率、"
        "赔率或队伍实力。"
    )
    lines.append("")
    return "\n".join(lines)
