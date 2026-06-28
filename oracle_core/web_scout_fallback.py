"""Web Scout fallback runtime — Patch 33.

When lineups / injuries / suspensions / weather / news / prematch signals
are missing, generates evidence requests and fetches evidence via an
injectable scout adapter.

Default adapter is ``DisabledWebScoutAdapter`` — no network, no env read.
``DeterministicFakeWebScoutAdapter`` returns synthetic FIC-* evidence only.

Scout evidence is report-only/context-only.  It does NOT modify xG,
probabilities, odds, or team strength.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence


# ---------------------------------------------------------------------------
# Evidence types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebScoutEvidence:
    """A single piece of scout-sourced evidence.

    Report-only / context-only.  Does NOT modify model output.
    """

    evidence_id: str
    """Unique identifier for this evidence item."""

    evidence_type: str
    """Category: ``"injury"``, ``"lineup"``, ``"suspension"``, ``"weather"``,
    ``"news"``, ``"prematch_signal"``."""

    summary: str
    """Brief factual summary."""

    confidence: str = "low"
    """Confidence: ``"high"``, ``"medium"``, ``"low"``, ``"synthetic"``."""

    source_url_or_reference: str = ""
    """URL or reference to the source.  May be empty for synthetic."""

    searched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When the search was performed."""

    provenance: str = ""
    """Provenance info: which adapter produced this."""

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must not be empty")
        if self.searched_at.tzinfo is None or self.searched_at.utcoffset() is None:
            raise ValueError("searched_at must be timezone-aware")

    @property
    def report_only(self) -> bool:
        """Scout evidence is report-only/context-only in v1."""
        return True

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "summary": self.summary,
            "confidence": self.confidence,
            "source_url_or_reference": self.source_url_or_reference,
            "searched_at": self.searched_at.isoformat(),
            "provenance": self.provenance,
            "report_only": self.report_only,
        }


# ---------------------------------------------------------------------------
# Scout request / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebScoutRequest:
    """A request for web scout evidence on a specific topic."""

    request_id: str
    """Unique request identifier."""

    topic: str
    """What to search for: ``"injuries"``, ``"lineups"``, ``"weather"``, etc."""

    match_id: str = ""
    """Optional match identifier this request is for."""

    team_ids: tuple[str, ...] = ()
    """Team identifiers relevant to this request."""

    query_hint: str = ""
    """Natural-language hint for what to look for."""

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id must not be empty")


@dataclass(frozen=True)
class WebScoutResult:
    """Result of a web scout fallback run."""

    requests_sent: tuple[WebScoutRequest, ...] = ()
    """Requests that were issued."""

    evidence: tuple[WebScoutEvidence, ...] = ()
    """Evidence items gathered."""

    gaps: tuple[str, ...] = ()
    """Gaps that could not be filled (e.g. no real adapter)."""

    caveats: tuple[str, ...] = ()
    """Caveats about the scout run."""

    adapter_used: str = "disabled"
    """Which adapter was used."""

    completed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When the scout run completed."""


# ---------------------------------------------------------------------------
# Web Scout Adapter Protocol
# ---------------------------------------------------------------------------


class WebScoutAdapter(Protocol):
    """Protocol for web scout adapters.

    Implementations:
      - ``DisabledWebScoutAdapter`` — always returns empty (default).
      - ``DeterministicFakeWebScoutAdapter`` — returns FIC-* synthetic evidence.
      - Future: real web search adapter (opt-in, separate patch).
    """

    def search(self, request: WebScoutRequest) -> WebScoutEvidence | None: ...

    @property
    def adapter_name(self) -> str: ...


# ---------------------------------------------------------------------------
# Adapter implementations
# ---------------------------------------------------------------------------


class DisabledWebScoutAdapter:
    """Default adapter — always returns ``None`` (fail-closed).

    No network calls.  No env reads.  Scout is disabled by default.
    """

    @property
    def adapter_name(self) -> str:
        return "disabled"

    def search(self, request: WebScoutRequest) -> WebScoutEvidence | None:
        return None


class DeterministicFakeWebScoutAdapter:
    """Deterministic fake adapter for offline tests.

    Returns synthetic FIC-* evidence only.  No real teams, players, or data.
    No network calls.  No env reads.
    """

    @property
    def adapter_name(self) -> str:
        return "deterministic_fake"

    def search(self, request: WebScoutRequest) -> WebScoutEvidence | None:
        """Return synthetic evidence based on the request topic."""
        now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        templates: dict[str, tuple[str, str]] = {
            "injuries": (
                "FIC-injury-",
                "Synthetic injury report: Fictional Player X is doubtful "
                "with a fictional hamstring strain. Expected return unknown. "
                "(FIC-* synthetic data — not real.)",
            ),
            "lineups": (
                "FIC-lineup-",
                "Synthetic lineup report: Expected 4-3-3 formation for "
                "Fictional Team. All FIC-* players available. "
                "(FIC-* synthetic data — not real.)",
            ),
            "suspensions": (
                "FIC-susp-",
                "Synthetic suspension report: No FIC-* players suspended "
                "for this match. (FIC-* synthetic data — not real.)",
            ),
            "weather": (
                "FIC-weather-",
                "Synthetic weather report: Mild conditions expected at "
                "Fictional Stadium, 22°C, light breeze. "
                "(FIC-* synthetic data — not real.)",
            ),
            "news": (
                "FIC-news-",
                "Synthetic news: Fictional Team coach states squad is "
                "fully prepared. (FIC-* synthetic data — not real.)",
            ),
        }

        template = templates.get(request.topic)
        if template is None:
            template = (
                f"FIC-{request.topic}-",
                f"Synthetic {request.topic} evidence for match. "
                f"(FIC-* synthetic data — not real.)",
            )

        eid_prefix, summary = template
        return WebScoutEvidence(
            evidence_id=f"{eid_prefix}{request.request_id}",
            evidence_type=request.topic,
            summary=summary,
            confidence="synthetic",
            source_url_or_reference="fixture://fake_web_scout/" + request.topic,
            searched_at=now,
            provenance=f"DeterministicFakeWebScoutAdapter (FIC-* synthetic)",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_web_scout_requests(
    gap_list: Sequence[str],
    match_id: str = "",
    team_ids: tuple[str, ...] = (),
) -> tuple[WebScoutRequest, ...]:
    """Build scout requests from a gap list.

    Only generates requests for gaps that a web scout could potentially fill:
    injuries, lineups, suspensions, weather, news, prematch_signals.

    Does NOT generate requests for: team_id_resolution, standings,
    knockout_bracket, odds (these are provider/source gaps, not web-searchable).

    Args:
        gap_list: List of gap codes from context assembly.
        match_id: Optional match identifier.
        team_ids: Optional team identifiers.

    Returns:
        Tuple of ``WebScoutRequest`` objects.
    """
    scoutable_gaps = {
        "injuries_missing": "injuries",
        "lineups_missing": "lineups",
        "suspensions_missing": "suspensions",
        "weather_missing": "weather",
        "prematch_signals_missing": "news",
    }

    requests: list[WebScoutRequest] = []
    for gap in gap_list:
        topic = scoutable_gaps.get(gap)
        if topic is None:
            continue
        req = WebScoutRequest(
            request_id=f"scout-{topic}-{match_id or 'unknown'}",
            topic=topic,
            match_id=match_id,
            team_ids=team_ids,
            query_hint=f"Search for {topic} information",
        )
        requests.append(req)

    return tuple(requests)


def run_web_scout_fallback(
    requests: Sequence[WebScoutRequest],
    adapter: WebScoutAdapter | None = None,
) -> WebScoutResult:
    """Run web scout fallback with the given adapter.

    Args:
        requests: Scout requests to execute.
        adapter: A ``WebScoutAdapter`` implementation.  Defaults to
            ``DisabledWebScoutAdapter``.

    Returns:
        ``WebScoutResult`` with evidence gathered and gaps/caveats.
    """
    scout = adapter if adapter is not None else DisabledWebScoutAdapter()
    is_disabled = isinstance(scout, DisabledWebScoutAdapter)

    evidence: list[WebScoutEvidence] = []
    gaps: list[str] = []
    caveats: list[str] = []

    if is_disabled:
        caveats.append(
            "Web Scout is disabled by default. "
            "No web search performed. Scout evidence unavailable."
        )
        gaps.append("scout_web_provider_missing")
    else:
        caveats.append(
            "Web Scout evidence is report-only/context-only. "
            "Does NOT modify xG, probabilities, odds, or team strength."
        )

    for req in requests:
        result = scout.search(req)
        if result is not None:
            evidence.append(result)
        elif not is_disabled:
            gaps.append(f"scout_no_result:{req.topic}")

    if is_disabled:
        gaps.extend(["scout_disabled"] * len(requests) if requests else [])

    return WebScoutResult(
        requests_sent=tuple(requests),
        evidence=tuple(evidence),
        gaps=tuple(gaps),
        caveats=tuple(caveats),
        adapter_used=scout.adapter_name,
    )
