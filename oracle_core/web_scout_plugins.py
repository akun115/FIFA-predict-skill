"""Web Scout plugging kit — extends ``oracle_core.web_scout_runtime``.

Plugin specs, request/response types, and default disabled adapters for
Web Scout providers.  All providers are disabled by default.  No network.
No env reads.  No fake data.

Scout evidence is ALWAYS ``report_only=True``, ``affects_model=False``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol


# ---------------------------------------------------------------------------
# Plugin spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchProviderPluginSpec:
    """Specification for a Web Scout search provider plugin.

    All providers start disabled (``approval_status="disabled"``).
    Activation requires explicit approval.
    """

    provider_name: str
    provider_type: str = "http_search"
    base_url: str = ""
    configured: bool = False
    requires_api_key: bool = True
    approval_status: str = "disabled"
    evidence_schema_version: str = "1.0.0"


# ---------------------------------------------------------------------------
# Plugin-level request / response
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoutSearchRequest:
    """A plugin-level request for Web Scout evidence.

    Carries query, topics, match context, and an explicit allow flag.
    """

    query: str
    """Natural-language query for the search."""

    topics: tuple[str, ...] = ()
    """Topics to search: ``"injuries"``, ``"lineups"``, ``"weather"``, etc."""

    match_id: str = ""
    """Optional match identifier this request is for."""

    team_ids: tuple[str, ...] = ()
    """Team identifiers relevant to this request."""

    allow_web_scout: bool = False
    """Explicit opt-in flag.  ``False`` means scout is disabled."""

    max_results: int = 5
    """Maximum results to return."""

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be empty")
        if self.max_results < 1:
            raise ValueError("max_results must be >= 1")


def _make_default_evidence_dict() -> dict[str, Any]:
    """Return a default evidence dict with safe defaults."""
    return {
        "title": "",
        "source": "",
        "url_or_reference": "",
        "snippet": "",
        "evidence_type": "unknown",
        "confidence": "low",
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "report_only": True,
        "affects_model": False,
    }


@dataclass(frozen=True)
class ScoutSearchResponse:
    """Response from a plugin-level Web Scout search.

    ``evidence`` is a tuple of dicts, each containing: ``title``, ``source``,
    ``url_or_reference``, ``snippet``, ``evidence_type``, ``confidence``,
    ``searched_at``, ``report_only``, ``affects_model``.

    When disabled, ``gaps`` and ``caveats`` describe the failure.
    """

    provider_name: str
    success: bool
    evidence: tuple[dict[str, Any], ...] = ()
    """Evidence items gathered.  Each entry is a dict as described above."""

    gaps: tuple[str, ...] = ()
    """Gaps that could not be filled (e.g. no provider configured)."""

    caveats: tuple[str, ...] = ()
    """Caveats / warnings about the search."""

    network_called: bool = False
    """Whether a network call was made during this search."""

    searched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When the search completed."""

    def __post_init__(self) -> None:
        if self.searched_at.tzinfo is None or self.searched_at.utcoffset() is None:
            raise ValueError("searched_at must be timezone-aware")

    def _validate_evidence(self) -> None:
        """Ensure all evidence dicts carry report_only=True, affects_model=False."""
        for ev in self.evidence:
            if ev.get("report_only", True) is not True:
                raise ValueError(
                    "Scout evidence report_only must always be True. "
                    "Scout evidence is report-only/context-only."
                )
            if ev.get("affects_model", False) is not False:
                raise ValueError(
                    "Scout evidence affects_model must always be False. "
                    "Scout evidence must not affect model output."
                )


# ---------------------------------------------------------------------------
# Built-in specs
# ---------------------------------------------------------------------------

DISABLED_SCOUT_SPEC = SearchProviderPluginSpec(
    provider_name="disabled_scout",
    provider_type="http_search",
    configured=False,
    requires_api_key=True,
    approval_status="disabled",
)

GENERIC_HTTP_SEARCH_SPEC = SearchProviderPluginSpec(
    provider_name="generic_http_search",
    provider_type="http_search",
    configured=False,
    requires_api_key=True,
    approval_status="disabled",
)


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


class ScoutPluginAdapter(Protocol):
    """Protocol that all scout plugin adapters implement."""

    PROVIDER_NAME: str

    def search(self, request: ScoutSearchRequest) -> ScoutSearchResponse:
        """Search for evidence given *request*.

        Returns a ``ScoutSearchResponse``.  Never raises.
        """
        ...


# ---------------------------------------------------------------------------
# DisabledScoutAdapter — default fail-closed adapter
# ---------------------------------------------------------------------------


class DisabledScoutAdapter:
    """Default adapter — always returns fail-closed response.

    No network.  No env reads.  Never fabricates data.
    """

    PROVIDER_NAME = "disabled"

    def search(self, request: ScoutSearchRequest) -> ScoutSearchResponse:
        now = datetime.now(timezone.utc)
        return ScoutSearchResponse(
            provider_name=self.PROVIDER_NAME,
            success=False,
            evidence=(),
            gaps=("scout_provider_disabled",),
            caveats=(
                "Web Scout plugin is disabled by default. "
                "No search performed. Scout evidence unavailable.",
            ),
            network_called=False,
            searched_at=now,
        )


# ---------------------------------------------------------------------------
# List plugins
# ---------------------------------------------------------------------------


def list_scout_plugins() -> tuple[SearchProviderPluginSpec, ...]:
    """Return all built-in Web Scout plugin specs.

    Returns:
        Tuple of ``SearchProviderPluginSpec``, all disabled by default.
    """
    return (DISABLED_SCOUT_SPEC, GENERIC_HTTP_SEARCH_SPEC)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_scout_adapter(
    provider_name: str,
    *,
    allow_web_scout: bool = False,
) -> ScoutPluginAdapter:
    """Factory: create a scout plugin adapter.

    Args:
        provider_name: Provider name hint.  Ignored in current version.
        allow_web_scout: If ``True``, returns a stub adapter for future real
            search.  If ``False`` (default), returns ``DisabledScoutAdapter``.

    Returns:
        A ``ScoutPluginAdapter`` implementation.
    """
    if allow_web_scout:
        return _StubRealScoutAdapter()
    return DisabledScoutAdapter()


class _StubRealScoutAdapter:
    """Stub adapter for future real search provider integration.

    Returns gap/caveat that no real search provider is configured.
    Does NOT fabricate evidence.  No network.  No env reads.
    """

    PROVIDER_NAME = "stub_real"

    def search(self, request: ScoutSearchRequest) -> ScoutSearchResponse:
        now = datetime.now(timezone.utc)
        return ScoutSearchResponse(
            provider_name=self.PROVIDER_NAME,
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
            searched_at=now,
        )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def execute_scout_search(
    adapter: ScoutPluginAdapter,
    request: ScoutSearchRequest,
) -> ScoutSearchResponse:
    """Execute a scout search through the given adapter, catching errors.

    Args:
        adapter: A ``ScoutPluginAdapter`` implementation.
        request: The ``ScoutSearchRequest`` to execute.

    Returns:
        ``ScoutSearchResponse`` with evidence, gaps, and caveats.

    Never raises.  Never fabricates data on failure.
    """
    try:
        result = adapter.search(request)
        return result
    except Exception as exc:
        now = datetime.now(timezone.utc)
        return ScoutSearchResponse(
            provider_name=getattr(adapter, "PROVIDER_NAME", "unknown"),
            success=False,
            evidence=(),
            gaps=("scout_search_error",),
            caveats=(
                f"Scout search raised {type(exc).__name__}: {exc}",
            ),
            network_called=False,
            searched_at=now,
        )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def deduplicate_evidence(
    evidence_items: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Deduplicate evidence items by URL/source/title.

    Items with matching ``url_or_reference`` are considered duplicates.
    If URL is empty, falls back to ``(source, title)`` pair.

    Args:
        evidence_items: Tuple of evidence dicts to deduplicate.

    Returns:
        Deduplicated tuple of evidence dicts, preserving insertion order.
    """
    seen: set[tuple[str, ...]] = set()
    result: list[dict[str, Any]] = []

    for ev in evidence_items:
        url = ev.get("url_or_reference", "") or ""
        source = ev.get("source", "") or ""
        title = ev.get("title", "") or ""

        if url.strip():
            key = ("url", url.strip().lower())
        elif source.strip() and title.strip():
            key = ("st", source.strip().lower(), title.strip().lower())
        else:
            key = ("fallback", str(id(ev)))

        if key not in seen:
            seen.add(key)
            result.append(ev)

    return tuple(result)


# ---------------------------------------------------------------------------
# Context formatter
# ---------------------------------------------------------------------------


def scout_evidence_to_context(
    evidence: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Format scout evidence for report inclusion.

    Ensures every evidence dict has ``report_only=True`` and
    ``affects_model=False``.  Output is intended for the report section,
    not for model input.

    Args:
        evidence: Tuple of evidence dicts.

    Returns:
        Tuple of evidence dicts with ``report_only=True`` and
        ``affects_model=False`` enforced.
    """
    result: list[dict[str, Any]] = []
    for ev in evidence:
        entry = dict(ev)
        entry["report_only"] = True
        entry["affects_model"] = False
        result.append(entry)
    return tuple(result)
