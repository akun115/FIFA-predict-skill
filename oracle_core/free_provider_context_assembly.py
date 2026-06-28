"""Free provider → MatchContextSnapshot assembly — Patch 30.

Assembles ``MatchContextAssemblyResult`` from one or more ``MappingResult``
objects.  Output is context/report layer only.  Does NOT enter the prediction
engine.  Does NOT generate any prediction fields.

IMPORTANT — Model Input Boundary (v1):
  model_boundary.affects_model is ALWAYS False.
  model_boundary.enters_prediction_engine is ALWAYS False.
  model_boundary.report_only_or_context_only is ALWAYS True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from oracle_core.data_service_types import (
    CanonicalTeam,
    CanonicalMatch,
    DataQualityIssue,
    DataQualitySeverity,
    MatchContextSnapshot,
    ProviderProvenance,
)
from oracle_core.free_provider_mappers import (
    MappingResult,
    ModelBoundary,
)


# ---------------------------------------------------------------------------
# Assembly result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchContextAssemblyResult:
    """Result envelope for assembling provider mapping results into context.

    Carries the assembled ``MatchContextSnapshot``, all data quality issues,
    provenance, and a model boundary declaration.

    This is a context/report-layer object.  It does NOT contain:
      - result_probabilities
      - expected_goals
      - top_scores
      - over_under probabilities
      - advancement_probabilities
      - odds blending
      - xG adjustment
      - score prediction
    """

    provider_name: str
    """Primary provider name, e.g. ``"thesportsdb"``."""

    context_snapshot: MatchContextSnapshot | None = None
    """Assembled match context snapshot.  ``None`` if assembly failed."""

    canonical_teams: tuple[CanonicalTeam, ...] = ()
    """Canonical team entities extracted from mapping results."""

    canonical_matches: tuple[CanonicalMatch, ...] = ()
    """Canonical match entities extracted from mapping results."""

    data_quality_issues: tuple[DataQualityIssue, ...] = ()
    """All data quality issues (from mapping + assembly)."""

    provenance: tuple[ProviderProvenance, ...] = ()
    """Provenance records from the mapping results."""

    source_references: tuple[str, ...] = ()
    """Redacted source references from the raw fetch results."""

    raw_payload_hashes: tuple[str, ...] = ()
    """SHA-256 hashes of the raw payloads."""

    assembled_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """UTC-aware timestamp of assembly."""

    model_boundary: ModelBoundary = field(default_factory=ModelBoundary)
    """Model boundary declaration — always report/context only."""

    gap_list: tuple[str, ...] = ()
    """Enumerated data gaps that are known to be missing."""

    def __post_init__(self) -> None:
        if self.assembled_at.tzinfo is None or self.assembled_at.utcoffset() is None:
            raise ValueError("assembled_at must be timezone-aware")

    @property
    def has_blocking_issues(self) -> bool:
        return any(i.blocking for i in self.data_quality_issues)


# ---------------------------------------------------------------------------
# Required gap list for TheSportsDB (free public provider)
# ---------------------------------------------------------------------------


_REQUIRED_GAPS: tuple[str, ...] = (
    "team_id_resolution_missing",
    "standings_missing",
    "lineups_missing",
    "injuries_missing",
    "suspensions_missing",
    "odds_missing",
    "knockout_bracket_missing",
    "prematch_signals_missing",
    "weather_missing",
    "timezone_unknown",
    "limited_match_coverage",
    "provider_not_approved_for_model_input",
    "production_provider_coverage_unverified",
)


def _build_gap_issues() -> list[DataQualityIssue]:
    """Build DataQualityIssue entries for every known gap."""
    issues: list[DataQualityIssue] = []
    for gap in _REQUIRED_GAPS:
        issues.append(DataQualityIssue(
            severity=DataQualitySeverity.WARNING,
            code=f"GAP_{gap.upper()}",
            message=f"Data gap: {gap.replace('_', ' ')} — "
                    f"not available from TheSportsDB free tier.",
            provenance_refs=("thesportsdb",),
        ))
    return issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assemble_match_context_from_mapping_results(
    *mapping_results: MappingResult,
) -> MatchContextAssemblyResult:
    """Assemble a ``MatchContextAssemblyResult`` from one or more
    ``MappingResult`` objects.

    Extracts canonical teams and matches, aggregates data quality issues,
    preserves provenance, and builds a gap list.  Does NOT generate any
    prediction fields.

    Args:
        mapping_results: One or more ``MappingResult`` from a provider mapper
            (e.g. ``map_thesportsdb_teams``, ``map_thesportsdb_matches``).

    Returns:
        ``MatchContextAssemblyResult`` with context snapshot, gap list, and
        model boundary.
    """
    all_issues: list[DataQualityIssue] = []
    all_teams: list[CanonicalTeam] = []
    all_matches: list[CanonicalMatch] = []
    all_provenance: list[ProviderProvenance] = []
    all_source_refs: list[str] = []
    all_hashes: list[str] = []
    provider_name = "unknown"

    for mr in mapping_results:
        if not isinstance(mr, MappingResult):
            continue
        provider_name = mr.provider_name
        all_issues.extend(mr.data_quality_issues)
        if mr.provenance:
            all_provenance.append(mr.provenance)
        if mr.source_reference:
            all_source_refs.append(mr.source_reference)
        if mr.raw_payload_hash:
            all_hashes.append(mr.raw_payload_hash)

        for item in mr.canonical_items:
            if isinstance(item, CanonicalTeam):
                all_teams.append(item)
            elif isinstance(item, CanonicalMatch):
                all_matches.append(item)

    # ── Assembly-level issues ──
    all_issues.append(DataQualityIssue(
        severity=DataQualitySeverity.INFO,
        code="ASSEMBLY_CONTEXT_REPORT_ONLY",
        message="MatchContextAssemblyResult is context/report layer only. "
                "Does not enter prediction engine. Does not affect model probabilities.",
        provenance_refs=(provider_name,),
    ))

    # Gap issues
    all_issues.extend(_build_gap_issues())

    # Provider not approved
    all_issues.append(DataQualityIssue(
        severity=DataQualitySeverity.INFO,
        code="PROVIDER_NOT_APPROVED_FOR_MODEL_INPUT",
        message=f"Provider '{provider_name}' is not approved for model input. "
                f"Context is for audit and report only.",
        provenance_refs=(provider_name,),
    ))

    # ── Build context snapshot ──
    snapshot = _build_context_snapshot(
        provider_name=provider_name,
        teams=all_teams,
        matches=all_matches,
        issues=all_issues,
        provenance=all_provenance,
    )

    return MatchContextAssemblyResult(
        provider_name=provider_name,
        context_snapshot=snapshot,
        canonical_teams=tuple(all_teams),
        canonical_matches=tuple(all_matches),
        data_quality_issues=tuple(all_issues),
        provenance=tuple(all_provenance),
        source_references=tuple(all_source_refs),
        raw_payload_hashes=tuple(all_hashes),
        model_boundary=ModelBoundary(),
        gap_list=_REQUIRED_GAPS,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_context_snapshot(
    provider_name: str,
    teams: list[CanonicalTeam],
    matches: list[CanonicalMatch],
    issues: list[DataQualityIssue],
    provenance: list[ProviderProvenance],
) -> MatchContextSnapshot:
    """Build a minimal ``MatchContextSnapshot`` from assembled data.

    Only populates team_a / team_b / match from the first available entries.
    All squad/odds/signal context fields are left empty (default) since
    TheSportsDB does not provide them.
    """
    team_a = teams[0] if len(teams) > 0 else None
    team_b = teams[1] if len(teams) > 1 else None
    match = matches[0] if len(matches) > 0 else None

    # If we have a match but no separate teams, try to match team_a/team_b
    # by team_id lookup
    if match and not team_a:
        for t in teams:
            if t.team_id == match.team_a_id:
                team_a = t
                break
    if match and not team_b:
        for t in teams:
            if t.team_id == match.team_b_id:
                team_b = t
                break

    now = datetime.now(timezone.utc)
    snapshot_id = _make_snapshot_id(provider_name, matches, now)

    return MatchContextSnapshot(
        snapshot_id=snapshot_id,
        snapshot_version="1.0.0-patch30",
        snapshot_created_at=now,
        match=match,
        team_a=team_a,
        team_b=team_b,
        group_context=None,
        knockout_context=None,
        odds_context=None,
        lineup_context=(),
        injury_context=(),
        suspension_context=(),
        prematch_signals=(),
        data_quality=tuple(issues),
        provenance_refs=tuple(provenance),
    )


def _make_snapshot_id(
    provider_name: str,
    matches: list[CanonicalMatch],
    now: datetime,
) -> str:
    """Generate a deterministic snapshot ID."""
    match_ids = "-".join(m.match_id for m in matches[:3]) if matches else "no-matches"
    ts = now.strftime("%Y%m%dT%H%M%S")
    return f"snap-{provider_name}-{match_ids[:60]}-{ts}"
