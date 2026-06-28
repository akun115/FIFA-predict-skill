"""Canonical schema skeleton for Data Service v1.

Patch 14 — schema types and deterministic fixtures only.
No provider runtime. No prediction integration. No real data.

IMPORTANT — Model Input Boundary (v1):
  odds_context, lineup_context, injury_context, suspension_context, and
  prematch_signals in MatchContextSnapshot are *structured context only*.
  They MUST NOT be used to:
    - modify result_probabilities
    - modify expected_goals
    - modify top_scores
    - modify over_under probabilities
    - modify advancement_probabilities
    - adjust xG
    - adjust team strength
    - replace or augment the local prediction engine

  Permitted uses in v1:
    - audit
    - data_quality reporting
    - market comparison (odds vs model, additive only)
    - replay traceability
    - Chinese report explanation
    - future analysis (gated behind separate patch)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import math
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# Data quality severity
# ---------------------------------------------------------------------------


class DataQualitySeverity(str, Enum):
    """Severity levels for DataQualityIssue.

    * info     — noteworthy but does not affect prediction.
    * warning  — may affect interpretation; does not block prediction.
    * error    — data is likely incorrect; prediction may be unreliable.
    * blocking — prediction cannot proceed; must be resolved first.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderProvenance:
    """Tracks every normalized field back to its raw source.

    Every canonical entity carries one or more provenance references so that
    replay evaluation can verify it is using the same raw data that was
    available at prediction time.
    """

    provider_name: str
    """Unique provider identifier, e.g. ``"fake_provider_v1"``."""

    adapter_version: str
    """Version of the adapter that produced this data, e.g. ``"1.0.0"``."""

    fetched_at: datetime
    """UTC-aware timestamp of when the provider was queried."""

    source_reference: str | None = None
    """URL or file path to the source, if available."""

    raw_payload_hash: str = ""
    """SHA-256 hex digest of the raw provider response."""

    license_notes: str | None = None
    """Attribution or license requirements, if relevant."""

    transformation_notes: str | None = None
    """Description of any transformations applied to go from raw → canonical."""

    def __post_init__(self) -> None:
        if not self.provider_name.strip():
            raise ValueError("provider_name must not be empty")
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")

    def to_dict(self) -> dict:
        return {
            "provider_name": self.provider_name,
            "adapter_version": self.adapter_version,
            "fetched_at": self.fetched_at.isoformat(),
            "source_reference": self.source_reference,
            "raw_payload_hash": self.raw_payload_hash,
            "license_notes": self.license_notes,
            "transformation_notes": self.transformation_notes,
        }


# ---------------------------------------------------------------------------
# Data quality issue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataQualityIssue:
    """Structured data quality issue for a canonical entity.

    Used in validation reports, snapshot metadata, and audit trails.
    """

    severity: DataQualitySeverity
    code: str
    """Machine-readable issue code, e.g. ``"MISSING_KICKOFF"``."""

    message: str
    """Human-readable description of the issue."""

    field_path: str | None = None
    """Dot-separated path to the affected field, e.g. ``"match.kickoff_at"``."""

    provenance_refs: tuple[str, ...] = ()
    """Provider names that contributed to or are affected by this issue."""

    @property
    def blocking(self) -> bool:
        """Convenience: ``True`` when severity is ``BLOCKING``."""
        return self.severity is DataQualitySeverity.BLOCKING

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "field_path": self.field_path,
            "provenance_refs": list(self.provenance_refs),
            "blocking": self.blocking,
        }


# ---------------------------------------------------------------------------
# Canonical entities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalTeam:
    """Canonical representation of a team, normalized across providers."""

    team_id: str
    """Stable canonical identifier, e.g. ``"FIC-ALPHA"``."""

    display_name: str
    """Human-readable display name, e.g. ``"Fictional Alpha FC"``."""

    country_code: str | None = None
    """ISO 3166-1 alpha-3 code, if applicable."""

    external_ids: Mapping[str, str] = field(default_factory=dict)
    """Provider-specific external IDs, keyed by provider_name."""

    provenance_refs: tuple[ProviderProvenance, ...] = ()
    data_quality: tuple[DataQualityIssue, ...] = ()

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "display_name": self.display_name,
            "country_code": self.country_code,
            "external_ids": dict(self.external_ids),
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
        }


@dataclass(frozen=True)
class CanonicalMatch:
    """Canonical representation of a match fixture, normalized across providers."""

    match_id: str
    """Stable canonical match identifier, e.g. ``"FIC-001"``."""

    team_a_id: str
    """Canonical ``team_id`` for team A."""

    team_b_id: str
    """Canonical ``team_id`` for team B."""

    kickoff_at: datetime
    """UTC-aware kickoff time."""

    stage: str = "group"
    """Tournament stage: ``"group"``, ``"R32"``, ``"R16"``, ``"QF"``, ``"SF"``, ``"3rd"``, ``"F"``."""

    group: str | None = None
    """Group name, e.g. ``"A"`` — ``None`` for knockout matches."""

    round_name: str | None = None
    """Round display name, e.g. ``"Round of 16"`` — ``None`` for group-stage."""

    venue: str | None = None
    """Stadium or city name."""

    neutral_site: bool = True
    """World Cup matches are all neutral-site."""

    provenance_refs: tuple[ProviderProvenance, ...] = ()
    data_quality: tuple[DataQualityIssue, ...] = ()

    def __post_init__(self) -> None:
        if not self.match_id.strip():
            raise ValueError("match_id must not be empty")
        if not self.team_a_id.strip() or not self.team_b_id.strip():
            raise ValueError("team_a_id and team_b_id must not be empty")
        if self.team_a_id == self.team_b_id:
            raise ValueError("team_a_id and team_b_id must differ")
        if self.kickoff_at.tzinfo is None or self.kickoff_at.utcoffset() is None:
            raise ValueError("kickoff_at must be timezone-aware")

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "team_a_id": self.team_a_id,
            "team_b_id": self.team_b_id,
            "kickoff_at": self.kickoff_at.isoformat(),
            "stage": self.stage,
            "group": self.group,
            "round_name": self.round_name,
            "venue": self.venue,
            "neutral_site": self.neutral_site,
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
        }


# ---------------------------------------------------------------------------
# Tournament context types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupStandingRow:
    """A single row in a group standings table."""

    position: int
    team_id: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0
    points: int = 0

    def to_dict(self) -> dict:
        return {
            "position": self.position,
            "team_id": self.team_id,
            "played": self.played,
            "won": self.won,
            "drawn": self.drawn,
            "lost": self.lost,
            "goals_for": self.goals_for,
            "goals_against": self.goals_against,
            "goal_difference": self.goal_difference,
            "points": self.points,
        }


@dataclass(frozen=True)
class GroupStandingContext:
    """Group standings table at a point in time."""

    group_id: str
    """Group identifier, e.g. ``"A"``."""

    rows: tuple[GroupStandingRow, ...]
    provenance_refs: tuple[ProviderProvenance, ...] = ()
    data_quality: tuple[DataQualityIssue, ...] = ()

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "rows": [row.to_dict() for row in self.rows],
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
        }


@dataclass(frozen=True)
class KnockoutBracketContext:
    """Knockout bracket structure for a competition season."""

    bracket_id: str
    """Identifier, e.g. ``"WC2026-KO"``."""

    round_name: str
    """Round name, e.g. ``"Round of 16"``, ``"Quarter-final"``."""

    match_slots: tuple[str, ...] = ()
    """Match IDs that belong to this bracket round, in bracket order."""

    provenance_refs: tuple[ProviderProvenance, ...] = ()
    data_quality: tuple[DataQualityIssue, ...] = ()

    def to_dict(self) -> dict:
        return {
            "bracket_id": self.bracket_id,
            "round_name": self.round_name,
            "match_slots": list(self.match_slots),
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
        }


# ---------------------------------------------------------------------------
# Odds context — market comparison only (NOT a model input in v1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OddsSelection:
    """A single selection within an odds market."""

    label: str
    """e.g. ``"team_a_win"``, ``"draw"``, ``"team_b_win"``, ``"over"``, ``"under"``."""

    decimal_odds: float
    """Decimal odds, e.g. ``2.10``."""

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("label must not be empty")
        if self.decimal_odds < 1.0:
            raise ValueError(f"decimal_odds must be >= 1.0, got {self.decimal_odds}")

    def to_dict(self) -> dict:
        return {"label": self.label, "decimal_odds": self.decimal_odds}


@dataclass(frozen=True)
class OddsMarketContext:
    """Odds market snapshot — MARKET COMPARISON ONLY.

    **v1 boundary:** This data is NOT used to modify model probabilities.
    ``model_vs_market_delta`` is an additive output, not an input blend.
    """

    match_id: str
    market_type: str
    """e.g. ``"1X2"``, ``"over_under_2.5"``."""

    selections: tuple[OddsSelection, ...] = ()
    """Individual odds selections in this market."""

    bookmaker: str | None = None
    """Bookmaker name, e.g. ``"fictional_bookmaker"``."""

    captured_at: datetime | None = None
    """When these odds were observed."""

    overround: float | None = None
    """Implied overround (bookmaker margin). Computed, not asserted."""

    normalized_probabilities: Mapping[str, float] = field(default_factory=dict)
    """Implied probabilities normalized to sum to 1.0 (overround removed).

    Keys match ``OddsSelection.label`` values.
    """

    provenance_refs: tuple[ProviderProvenance, ...] = ()
    data_quality: tuple[DataQualityIssue, ...] = ()

    def __post_init__(self) -> None:
        if not self.match_id.strip():
            raise ValueError("match_id must not be empty")

    @property
    def report_only(self) -> bool:
        """Odds context is report-only in v1 — never blended into model."""
        return True

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "market_type": self.market_type,
            "selections": [s.to_dict() for s in self.selections],
            "bookmaker": self.bookmaker,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "overround": self.overround,
            "normalized_probabilities": dict(self.normalized_probabilities),
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
            "report_only": self.report_only,
        }


# ---------------------------------------------------------------------------
# Squad / availability context — structured context ONLY (v1 boundary)
# ---------------------------------------------------------------------------


class LineupStatus(str, Enum):
    PREDICTED = "predicted"
    CONFIRMED = "confirmed"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PlayerSlot:
    """A player in a starting XI or substitutes list."""

    name: str
    number: int | None = None
    position: str | None = None
    is_captain: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "number": self.number,
            "position": self.position,
            "is_captain": self.is_captain,
        }


@dataclass(frozen=True)
class LineupContext:
    """Team lineup for a specific match — STRUCTURED CONTEXT ONLY.

    **v1 boundary:** Lineup data is NOT used to adjust xG, expected_goals,
    result_probabilities, or any model probability output.  It is stored for
    audit, data quality, replay traceability, and Chinese report explanation.
    """

    match_id: str
    team_id: str
    status: LineupStatus = LineupStatus.UNAVAILABLE
    """Confirmation status of this lineup."""

    formation: str | None = None
    starting_xi: tuple[PlayerSlot, ...] = ()
    substitutes: tuple[PlayerSlot, ...] = ()
    coach: str | None = None
    last_updated: datetime | None = None

    provenance_refs: tuple[ProviderProvenance, ...] = ()
    data_quality: tuple[DataQualityIssue, ...] = ()

    @property
    def report_only(self) -> bool:
        """Lineup context is report-only in v1 — never adjusts model output."""
        return True

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "team_id": self.team_id,
            "status": self.status.value,
            "formation": self.formation,
            "starting_xi": [p.to_dict() for p in self.starting_xi],
            "substitutes": [p.to_dict() for p in self.substitutes],
            "coach": self.coach,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
            "report_only": self.report_only,
        }


class InjuryStatus(str, Enum):
    OUT = "out"
    DOUBTFUL = "doubtful"
    QUESTIONABLE = "questionable"
    PROBABLE = "probable"


@dataclass(frozen=True)
class InjuryContext:
    """Player injury record — STRUCTURED CONTEXT ONLY.

    **v1 boundary:** Injury data is NOT used to adjust xG, expected_goals,
    result_probabilities, or any model probability output.
    """

    team_id: str
    player_name: str
    status: InjuryStatus = InjuryStatus.OUT
    injury_type: str | None = None
    expected_return: str | None = None
    source_updated_at: datetime | None = None

    provenance_refs: tuple[ProviderProvenance, ...] = ()
    data_quality: tuple[DataQualityIssue, ...] = ()

    @property
    def report_only(self) -> bool:
        """Injury context is report-only in v1 — never adjusts model output."""
        return True

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "player_name": self.player_name,
            "status": self.status.value,
            "injury_type": self.injury_type,
            "expected_return": self.expected_return,
            "source_updated_at": (
                self.source_updated_at.isoformat() if self.source_updated_at else None
            ),
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
            "report_only": self.report_only,
        }


@dataclass(frozen=True)
class SuspensionContext:
    """Player suspension record — STRUCTURED CONTEXT ONLY.

    **v1 boundary:** Suspension data is NOT used to adjust xG, expected_goals,
    result_probabilities, or any model probability output.
    """

    team_id: str
    player_name: str
    reason: str = ""
    """e.g. ``"yellow_accumulation"``, ``"red_card"``, ``"disciplinary"``."""

    matches_suspended: int = 1
    remaining_matches: int = 1

    provenance_refs: tuple[ProviderProvenance, ...] = ()
    data_quality: tuple[DataQualityIssue, ...] = ()

    @property
    def report_only(self) -> bool:
        """Suspension context is report-only in v1 — never adjusts model output."""
        return True

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "player_name": self.player_name,
            "reason": self.reason,
            "matches_suspended": self.matches_suspended,
            "remaining_matches": self.remaining_matches,
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
            "report_only": self.report_only,
        }


# ---------------------------------------------------------------------------
# Prematch signals — report-only context (v1 boundary)
# ---------------------------------------------------------------------------


class SignalConfidence(str, Enum):
    CONFIRMED = "confirmed"
    REPORTED = "reported"
    RUMOR = "rumor"


@dataclass(frozen=True)
class PrematchSignal:
    """A qualitative pre-match signal from AI Web Scout or provider — REPORT ONLY.

    **v1 boundary:** Signals are NOT parsed into quantitative xG adjustments.
    They are stored for audit, data quality, replay traceability, and Chinese
    report explanation.
    """

    signal_id: str
    match_id: str
    category: str
    """e.g. ``"weather"``, ``"travel"``, ``"tactical"``, ``"motivation"``, ``"news"``."""

    summary: str
    """Brief factual summary of the signal."""

    confidence: SignalConfidence = SignalConfidence.REPORTED
    source_url: str | None = None
    source_name: str | None = None
    published_at: datetime | None = None
    tags: tuple[str, ...] = ()

    provenance_refs: tuple[ProviderProvenance, ...] = ()
    data_quality: tuple[DataQualityIssue, ...] = ()

    @property
    def report_only(self) -> bool:
        """Prematch signal is report-only in v1 — never adjusts model output."""
        return True

    def __post_init__(self) -> None:
        if not self.signal_id.strip():
            raise ValueError("signal_id must not be empty")
        if not self.match_id.strip():
            raise ValueError("match_id must not be empty")

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "match_id": self.match_id,
            "category": self.category,
            "summary": self.summary,
            "confidence": self.confidence.value,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "tags": list(self.tags),
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
            "report_only": self.report_only,
        }


# ---------------------------------------------------------------------------
# MatchContextSnapshot — immutable prediction/replay input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchContextSnapshot:
    """Immutable, versioned snapshot of all available pre-match context.

    This is the single object passed to prediction and replay systems.
    Once created, it is never modified — replay reads historical snapshots,
    not live data.

    **v1 Model Input Boundary (see module docstring):**
    ``odds_context``, ``lineup_context``, ``injury_context``, ``suspension_context``,
    and ``prematch_signals`` are present for audit, data quality, market
    comparison, replay traceability, and Chinese report explanation.  The
    prediction engine MUST NOT read these fields to modify probabilities.
    """

    snapshot_id: str
    """Unique identifier for this snapshot (UUID or content hash)."""

    snapshot_version: str = "1.0.0"
    """Schema version for this snapshot."""

    snapshot_created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When this snapshot was built."""

    # ── Match identity ──
    match: CanonicalMatch | None = None

    # ── Teams ──
    team_a: CanonicalTeam | None = None
    team_b: CanonicalTeam | None = None

    # ── Tournament context (annotative only) ──
    group_context: GroupStandingContext | None = None
    knockout_context: KnockoutBracketContext | None = None

    # ── Market comparison (NOT model input) ──
    odds_context: OddsMarketContext | None = None
    """Odds snapshot — market comparison only; not blended into model."""

    # ── Squad context — structured context ONLY (NOT model input) ──
    lineup_context: tuple[LineupContext, ...] = ()
    """Team lineups — report/audit only; not used for xG adjustment."""

    injury_context: tuple[InjuryContext, ...] = ()
    """Injury records — report/audit only; not used for xG adjustment."""

    suspension_context: tuple[SuspensionContext, ...] = ()
    """Suspension records — report/audit only; not used for xG adjustment."""

    # ── Prematch signals — report ONLY (NOT model input) ──
    prematch_signals: tuple[PrematchSignal, ...] = ()
    """Qualitative signals — report/audit only; no quantitative extraction."""

    # ── Data quality ──
    data_quality: tuple[DataQualityIssue, ...] = ()

    # ── Provenance ──
    provenance_refs: tuple[ProviderProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be empty")
        if self.snapshot_created_at.tzinfo is None or self.snapshot_created_at.utcoffset() is None:
            raise ValueError("snapshot_created_at must be timezone-aware")

    @property
    def has_blocking_issues(self) -> bool:
        """``True`` if any data quality issue has severity ``BLOCKING``."""
        return any(dq.blocking for dq in self.data_quality)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "snapshot_created_at": self.snapshot_created_at.isoformat(),
            "match": self.match.to_dict() if self.match else None,
            "team_a": self.team_a.to_dict() if self.team_a else None,
            "team_b": self.team_b.to_dict() if self.team_b else None,
            "group_context": self.group_context.to_dict() if self.group_context else None,
            "knockout_context": self.knockout_context.to_dict() if self.knockout_context else None,
            "odds_context": self.odds_context.to_dict() if self.odds_context else None,
            "lineup_context": [lc.to_dict() for lc in self.lineup_context],
            "injury_context": [ic.to_dict() for ic in self.injury_context],
            "suspension_context": [sc.to_dict() for sc in self.suspension_context],
            "prematch_signals": [ps.to_dict() for ps in self.prematch_signals],
            "data_quality": [dq.to_dict() for dq in self.data_quality],
            "provenance_refs": [p.to_dict() for p in self.provenance_refs],
        }


# ---------------------------------------------------------------------------
# Deterministic fixture helpers
# ---------------------------------------------------------------------------


def _fixed_datetime(*args: int) -> datetime:
    """Return a UTC-aware datetime from year, month, day, hour, minute, second."""
    return datetime(*args, tzinfo=timezone.utc)


def _synthetic_hash(value: str) -> str:
    """Return a synthetic SHA-256 hash for deterministic fixture use."""
    return hashlib.sha256(f"synthetic:{value}".encode()).hexdigest()


def make_fixture_provenance(
    provider_name: str = "fake_provider_v1",
    suffix: str = "",
) -> ProviderProvenance:
    """Build a deterministic ``ProviderProvenance`` for fictional fixtures."""
    key = f"{provider_name}:{suffix}"
    return ProviderProvenance(
        provider_name=provider_name,
        adapter_version="1.0.0",
        fetched_at=_fixed_datetime(2026, 6, 1, 12, 0, 0),
        source_reference=f"fixture://{provider_name}/{suffix or 'default'}",
        raw_payload_hash=_synthetic_hash(key),
        license_notes="fictional fixture — no license required",
        transformation_notes="direct mapping from fictional fixture",
    )


def make_fixture_dq_issue(
    severity: DataQualitySeverity,
    code: str,
    message: str,
    field_path: str | None = None,
    provenance_names: tuple[str, ...] = ("fake_provider_v1",),
) -> DataQualityIssue:
    """Build a deterministic ``DataQualityIssue`` for fictional fixtures."""
    return DataQualityIssue(
        severity=severity,
        code=code,
        message=message,
        field_path=field_path,
        provenance_refs=provenance_names,
    )
