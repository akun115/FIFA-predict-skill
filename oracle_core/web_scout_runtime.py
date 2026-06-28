"""Production runtime boundary for Web Scout — Patch 36.

Extends ``web_scout_fallback.py`` with a production-capable runtime boundary.
Provides its own request/response types at the runtime level, with adapters
that wrap the fallback layer.

Default adapter is ``DisabledWebScoutRuntimeAdapter`` — no network, no env reads.
``StubRealWebScoutAdapter`` returns gaps/caveats for missing provider config.

Scout evidence is ALWAYS report-only/context-only.
Evidence NEVER modifies xG, probabilities, odds, or team strength.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from oracle_core.web_scout_fallback import (
    DisabledWebScoutAdapter,
    WebScoutRequest,
    run_web_scout_fallback,
)


# ---------------------------------------------------------------------------
# Runtime evidence item
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebScoutEvidenceItem:
    """A single scout-sourced evidence item at the runtime level.

    Report-only / context-only.  Does NOT modify model output.
    ``report_only`` is ALWAYS ``True``.  ``affects_model`` is ALWAYS ``False``.
    """

    title: str
    """Title or headline for this evidence item."""

    source: str
    """Source name, e.g. ``"web_scout"``."""

    source_url_or_reference: str
    """URL or reference to the source.  May be empty for stub/disabled."""

    snippet: str
    """Brief factual snippet describing the evidence."""

    evidence_type: str
    """Category: ``"injury"``, ``"lineup"``, ``"suspension"``, ``"weather"``,
    ``"news"``, ``"prematch_signal"``."""

    confidence: str = "low"
    """Confidence: ``"high"``, ``"medium"``, ``"low"``."""

    searched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When the search was performed."""

    report_only: bool = True
    """ALWAYS ``True`` — scout evidence is report-only/context-only."""

    affects_model: bool = False
    """ALWAYS ``False`` — scout evidence does NOT affect model output."""

    def __post_init__(self) -> None:
        if self.searched_at.tzinfo is None or self.searched_at.utcoffset() is None:
            raise ValueError("searched_at must be timezone-aware")

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source": self.source,
            "source_url_or_reference": self.source_url_or_reference,
            "snippet": self.snippet,
            "evidence_type": self.evidence_type,
            "confidence": self.confidence,
            "searched_at": self.searched_at.isoformat(),
            "report_only": self.report_only,
            "affects_model": self.affects_model,
        }


# ---------------------------------------------------------------------------
# Runtime request / response
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebScoutRuntimeRequest:
    """A production-level request for web scout evidence.

    Carries multiple query topics, match context, and an explicit allow flag.
    """

    query_topics: tuple[str, ...]
    """Topics to search: ``"injuries"``, ``"lineups"``, ``"weather"``, etc."""

    match_id: str = ""
    """Optional match identifier this request is for."""

    team_ids: tuple[str, ...] = ()
    """Team identifiers relevant to this request."""

    allow_web_scout: bool = False
    """Explicit opt-in flag.  ``False`` means scout is disabled."""

    max_results_per_topic: int = 5
    """Maximum results to return per topic."""

    def __post_init__(self) -> None:
        if self.max_results_per_topic < 1:
            raise ValueError("max_results_per_topic must be >= 1")


@dataclass(frozen=True)
class WebScoutRuntimeResponse:
    """Result of a production web scout runtime run."""

    success: bool
    """Whether the scout run completed successfully."""

    evidence: tuple[Mapping[str, Any], ...] = ()
    """Evidence items gathered as dicts."""

    gaps: tuple[str, ...] = ()
    """Gaps that could not be filled (e.g. no provider configured)."""

    caveats: tuple[str, ...] = ()
    """Caveats / warnings about the scout run."""

    network_called: bool = False
    """Whether a network call was made during this scout run."""

    env_read: bool = False
    """Whether environment variables (API keys) were read."""

    searched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When the scout run completed."""

    def __post_init__(self) -> None:
        if self.searched_at.tzinfo is None or self.searched_at.utcoffset() is None:
            raise ValueError("searched_at must be timezone-aware")


# ---------------------------------------------------------------------------
# Runtime Adapter Protocol
# ---------------------------------------------------------------------------


class WebScoutRuntimeAdapter(Protocol):
    """Protocol for production web scout runtime adapters."""

    def execute(self, request: WebScoutRuntimeRequest) -> WebScoutRuntimeResponse: ...

    @property
    def adapter_name(self) -> str: ...


# ---------------------------------------------------------------------------
# Adapter implementations
# ---------------------------------------------------------------------------


class DisabledWebScoutRuntimeAdapter:
    """Default adapter — returns fail-closed response.

    No network calls.  No env reads.  Scout is disabled by default.
    """

    @property
    def adapter_name(self) -> str:
        return "disabled_runtime"

    def execute(self, request: WebScoutRuntimeRequest) -> WebScoutRuntimeResponse:
        return WebScoutRuntimeResponse(
            success=False,
            evidence=(),
            gaps=("web_scout_disabled",),
            caveats=(
                "Web Scout runtime is disabled by default. "
                "No web search performed. Scout evidence unavailable.",
            ),
            network_called=False,
            env_read=False,
        )


class StubRealWebScoutAdapter:
    """Stub adapter for future real search provider.

    Returns gap/caveat that no real search provider is configured.
    Does NOT fabricate evidence.  No network calls.  No env reads.
    """

    @property
    def adapter_name(self) -> str:
        return "stub_real"

    def execute(self, request: WebScoutRuntimeRequest) -> WebScoutRuntimeResponse:
        return WebScoutRuntimeResponse(
            success=False,
            evidence=(),
            gaps=("no_real_search_provider_configured",),
            caveats=(
                "No real search provider is configured. "
                "Web Scout evidence is unavailable. "
                "To enable real search, configure a provider and "
                "opt in via allow_web_scout=True.",
            ),
            network_called=False,
            env_read=False,
        )


class FallbackWebScoutRuntimeAdapter:
    """Runtime adapter that wraps a ``web_scout_fallback`` adapter.

    Translates runtime requests to fallback requests, runs the fallback,
    and converts evidence to runtime-level dicts.

    May delegate to any ``WebScoutAdapter`` (e.g. ``DisabledWebScoutAdapter``
    or ``DeterministicFakeWebScoutAdapter``).
    """

    def __init__(self, fallback_adapter=None) -> None:
        self._fallback = (
            fallback_adapter
            if fallback_adapter is not None
            else DisabledWebScoutAdapter()
        )

    @property
    def adapter_name(self) -> str:
        return f"fallback_wrapper({self._fallback.adapter_name})"

    def execute(self, request: WebScoutRuntimeRequest) -> WebScoutRuntimeResponse:
        if not request.allow_web_scout:
            return WebScoutRuntimeResponse(
                success=False,
                evidence=(),
                gaps=("web_scout_not_allowed",),
                caveats=(
                    "Web Scout is not allowed for this request. "
                    "Set allow_web_scout=True to enable.",
                ),
                network_called=False,
                env_read=False,
            )

        # Translate runtime topics to fallback requests
        fallback_requests: list[WebScoutRequest] = []
        for topic in request.query_topics:
            req = WebScoutRequest(
                request_id=f"runtime-scout-{topic}-{request.match_id or 'unknown'}",
                topic=topic,
                match_id=request.match_id,
                team_ids=request.team_ids,
                query_hint=f"Search for {topic} information",
            )
            fallback_requests.append(req)

        # Run fallback
        result = run_web_scout_fallback(fallback_requests, self._fallback)

        # Convert evidence to runtime dicts
        evidence_dicts: list[dict] = []
        for ev in result.evidence:
            item = WebScoutEvidenceItem(
                title=f"{ev.evidence_type}: {ev.summary[:60]}",
                source=ev.provenance or "web_scout_fallback",
                source_url_or_reference=ev.source_url_or_reference or "",
                snippet=ev.summary,
                evidence_type=ev.evidence_type,
                confidence=ev.confidence,
                searched_at=ev.searched_at,
            )
            evidence_dicts.append(item.to_dict())

        # Determine network/env status
        is_disabled = isinstance(self._fallback, DisabledWebScoutAdapter)
        network_called = not is_disabled and len(fallback_requests) > 0
        env_read = False

        all_gaps = list(result.gaps)
        all_caveats = list(result.caveats)

        return WebScoutRuntimeResponse(
            success=not is_disabled and len(evidence_dicts) > 0,
            evidence=tuple(evidence_dicts),
            gaps=tuple(all_gaps),
            caveats=tuple(all_caveats),
            network_called=network_called,
            env_read=env_read,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_web_scout_runtime(
    provider_name: str = "",
    *,
    allow_web_scout: bool = False,
) -> WebScoutRuntimeAdapter:
    """Factory: create a web scout runtime adapter.

    Args:
        provider_name: Provider name hint.  Ignored in current version.
        allow_web_scout: If ``True``, returns ``StubRealWebScoutAdapter``
            (placeholder for future real search).  If ``False``, returns
            ``DisabledWebScoutRuntimeAdapter`` (default, fail-closed).

    Returns:
        A ``WebScoutRuntimeAdapter`` implementation.
    """
    if allow_web_scout:
        return StubRealWebScoutAdapter()
    return DisabledWebScoutRuntimeAdapter()


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def run_web_scout(
    adapter: WebScoutRuntimeAdapter,
    request: WebScoutRuntimeRequest,
) -> WebScoutRuntimeResponse:
    """Execute a web scout runtime request through the given adapter.

    Args:
        adapter: A ``WebScoutRuntimeAdapter`` implementation.
        request: The runtime request to execute.

    Returns:
        ``WebScoutRuntimeResponse`` with evidence, gaps, and caveats.
    """
    return adapter.execute(request)


# ---------------------------------------------------------------------------
# Report section formatter
# ---------------------------------------------------------------------------


def scout_evidence_to_report_section(
    evidence_items: tuple[Mapping[str, Any], ...],
) -> str:
    """Format web scout evidence items as a report section string.

    Args:
        evidence_items: Tuple of evidence dicts (from
            ``WebScoutEvidenceItem.to_dict()``).

    Returns:
        A formatted string section suitable for inclusion in a prediction report.
    """
    if not evidence_items:
        return (
            "【Web Scout Evidence】\n"
            "  Web Scout 未启用或无搜索结果。\n"
            "  如启用真实 Web Scout，需显式 opt-in 并配置搜索 provider。\n"
        )

    lines: list[str] = [
        "【Web Scout Evidence】",
        "  说明：Web Scout evidence 为 report-only / context-only，不入模型。",
        "  Scout 不会修改 xG、概率、赔率或队伍实力。",
    ]
    for i, ev in enumerate(evidence_items, 1):
        etype = ev.get("evidence_type", "unknown")
        title = ev.get("title", "unknown")
        snippet = ev.get("snippet", "")
        confidence = ev.get("confidence", "low")
        source = ev.get("source_url_or_reference", "")
        lines.append(f"  {i}. [{etype}] {title}")
        lines.append(f"     可信度: {confidence} | 来源: {source}")
        if snippet:
            lines.append(f"     摘要: {snippet[:120]}")

    lines.append("")
    return "\n".join(lines)
