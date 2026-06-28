"""Free provider → canonical entity mappers — Data Service v1 (Patch 29).

Minimal canonical mapping from TheSportsDB raw ``ProviderFetchResult`` to
``CanonicalTeam`` and ``CanonicalMatch`` entities.  Output is context/report
layer only.  Does NOT enter the prediction engine.

No odds blending.  No xG adjustment.  No LLM score prediction.
No real data in defaults.  All offline by default.

IMPORTANT — Model Input Boundary (v1):
  MappingResult.model_boundary.affects_model is ALWAYS False.
  MappingResult.model_boundary.enters_prediction_engine is ALWAYS False.
  Canonical context objects are for audit, data quality, replay traceability,
  and report explanation — NEVER for modifying model probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from oracle_core.data_service_types import (
    CanonicalTeam,
    CanonicalMatch,
    DataQualityIssue,
    DataQualitySeverity,
    ProviderProvenance,
)
from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderFetchResult,
)
from oracle_core.data_service_validator import (
    _try_parse_iso_utc,
)


# ---------------------------------------------------------------------------
# Model boundary marker
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelBoundary:
    """Immutable boundary declaration for every MappingResult.

    All fields default to the v1 boundary: context/report layer only,
    never enters the prediction engine.
    """

    affects_model: bool = False
    """MUST be False — mapper output does not affect model probabilities."""

    report_only_or_context_only: bool = True
    """MUST be True — mapper output is context/report layer only."""

    enters_prediction_engine: bool = False
    """MUST be False — mapper output does not enter the prediction engine."""


# ---------------------------------------------------------------------------
# Mapping result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MappingResult:
    """Result envelope for a provider → canonical mapping operation.

    Carries canonical entities, data quality issues, provenance, and a
    model boundary declaration.
    """

    provider_name: str
    """Provider that produced the raw data, e.g. ``"thesportsdb"``."""

    capability: str
    """Capability that was mapped, e.g. ``"teams"``, ``"matches"``."""

    canonical_items: tuple[CanonicalTeam | CanonicalMatch, ...] = ()
    """Normalized canonical entities produced by this mapping."""

    data_quality_issues: tuple[DataQualityIssue, ...] = ()
    """Issues found during mapping (missing fields, coverage, boundary)."""

    provenance: ProviderProvenance | None = None
    """Provenance for the mapping operation itself."""

    source_reference: str = ""
    """Redacted source reference from the raw fetch result."""

    raw_payload_hash: str = ""
    """SHA-256 hash of the raw payload this was mapped from."""

    mapped_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """UTC-aware timestamp of when mapping was performed."""

    model_boundary: ModelBoundary = field(default_factory=ModelBoundary)
    """Boundary declaration — always report/context only in v1."""

    def __post_init__(self) -> None:
        if self.mapped_at.tzinfo is None or self.mapped_at.utcoffset() is None:
            raise ValueError("mapped_at must be timezone-aware")

    @property
    def has_blocking_issues(self) -> bool:
        """``True`` if any data quality issue has severity ``BLOCKING``."""
        return any(i.blocking for i in self.data_quality_issues)


# ==========================================================================
# Shared issue builders
# ==========================================================================


def _issue(
    severity: DataQualitySeverity,
    code: str,
    message: str,
    field_path: str | None = None,
) -> DataQualityIssue:
    return DataQualityIssue(
        severity=severity,
        code=code,
        message=message,
        field_path=field_path,
        provenance_refs=("thesportsdb",),
    )


def _common_issues(source_reference: str, capability: str) -> list[DataQualityIssue]:
    """Issues that apply to every TheSportsDB mapping result."""
    issues: list[DataQualityIssue] = []

    # Provider remains needs_more_info
    issues.append(_issue(
        DataQualitySeverity.INFO,
        "PROVIDER_NEEDS_MORE_INFO",
        "TheSportsDB remains needs_more_info — not approved for live adapter.",
    ))

    # Model boundary — always report/context only
    issues.append(_issue(
        DataQualitySeverity.INFO,
        "MODEL_BOUNDARY_REPORT_ONLY",
        "TheSportsDB mapper output is context/report layer only. "
        "Does not enter prediction engine. Does not affect model probabilities.",
    ))

    # Live data not approved for model input
    issues.append(_issue(
        DataQualitySeverity.INFO,
        "LIVE_DATA_NOT_APPROVED_FOR_MODEL",
        "TheSportsDB live data is not approved for model input. "
        "Mapping is for audit and report context only.",
    ))

    # Unredacted source reference check
    if source_reference and "/api/v1/json/123/" in source_reference:
        issues.append(_issue(
            DataQualitySeverity.BLOCKING,
            "UNREDACTED_SOURCE_REFERENCE",
            "source_reference contains unredacted public test key '/123/' — "
            "must use '<public_test_key>' redaction.",
            field_path="source_reference",
        ))

    return issues


def _build_mapping_provenance(result: ProviderFetchResult) -> ProviderProvenance:
    """Build a provenance record for the mapping operation."""
    return ProviderProvenance(
        provider_name=result.provider_name,
        adapter_version=result.adapter_version,
        fetched_at=result.fetched_at,
        source_reference=result.source_reference,
        raw_payload_hash=result.raw_payload_hash,
        transformation_notes=(
            f"TheSportsDB {result.capability.value} → canonical mapping (Patch 29)"
        ),
    )


def _build_item_provenance(
    result: ProviderFetchResult,
    item_type: str,
) -> ProviderProvenance:
    """Build a provenance record for a single canonical item."""
    return ProviderProvenance(
        provider_name=result.provider_name,
        adapter_version=result.adapter_version,
        fetched_at=result.fetched_at,
        source_reference=result.source_reference,
        raw_payload_hash=result.raw_payload_hash,
        transformation_notes=(
            f"TheSportsDB {item_type} → canonical entity"
        ),
    )


# ==========================================================================
# Public API — map_thesportsdb_teams
# ==========================================================================


def map_thesportsdb_teams(result: ProviderFetchResult) -> MappingResult:
    """Map TheSportsDB teams raw payload → ``CanonicalTeam`` entities.

    Expected raw payload shape::

        {"teams": [{"idTeam": ..., "strTeam": ..., "strCountry": ..., ...}, ...]}

    Returns a ``MappingResult`` with canonical teams and data quality issues.
    Does NOT enter the prediction engine.
    """
    all_issues: list[DataQualityIssue] = []
    all_issues.extend(_common_issues(result.source_reference, "teams"))
    teams: list[CanonicalTeam] = []
    payload = result.payload

    # ── Schema check ──
    if "teams" not in payload:
        all_issues.append(_issue(
            DataQualitySeverity.ERROR,
            "UNKNOWN_SCHEMA",
            "Payload does not contain 'teams' key — unknown schema shape. "
            "Expected TheSportsDB searchteams.php response.",
            field_path="payload",
        ))
        return _build_mapping_result(result, tuple(teams), tuple(all_issues))

    team_list = payload.get("teams")
    if not isinstance(team_list, (list, tuple)):
        all_issues.append(_issue(
            DataQualitySeverity.ERROR,
            "UNKNOWN_SCHEMA",
            f"Payload 'teams' is {type(team_list).__name__}, expected list. "
            f"Unknown schema shape.",
            field_path="payload.teams",
        ))
        return _build_mapping_result(result, tuple(teams), tuple(all_issues))

    # ── Empty payload ──
    if len(team_list) == 0:
        all_issues.append(_issue(
            DataQualitySeverity.BLOCKING,
            "EMPTY_TEAMS_PAYLOAD",
            "TheSportsDB teams payload is empty — no team entries to map.",
            field_path="payload.teams",
        ))
        return _build_mapping_result(result, tuple(teams), tuple(all_issues))

    # ── Map each team entry ──
    for idx, item in enumerate(team_list):
        if not isinstance(item, dict):
            all_issues.append(_issue(
                DataQualitySeverity.ERROR,
                "UNKNOWN_SCHEMA",
                f"teams[{idx}] is {type(item).__name__}, expected dict.",
                field_path=f"payload.teams[{idx}]",
            ))
            continue

        team_issues: list[DataQualityIssue] = []
        field_prefix = f"payload.teams[{idx}]"

        # --- Required: idTeam ---
        id_team = item.get("idTeam")
        if not id_team or (isinstance(id_team, str) and not id_team.strip()):
            team_issues.append(_issue(
                DataQualitySeverity.BLOCKING,
                "MISSING_TEAM_PROVIDER_ID",
                f"teams[{idx}] missing idTeam — cannot assign canonical team_id.",
                field_path=f"{field_prefix}.idTeam",
            ))

        # --- Required: strTeam ---
        str_team = item.get("strTeam")
        if not str_team or (isinstance(str_team, str) and not str_team.strip()):
            team_issues.append(_issue(
                DataQualitySeverity.BLOCKING,
                "MISSING_TEAM_NAME",
                f"teams[{idx}] missing strTeam — cannot assign display_name.",
                field_path=f"{field_prefix}.strTeam",
            ))

        # --- Optional: strCountry (full name, NOT ISO code) ---
        str_country = item.get("strCountry")
        country_code: str | None = None
        if str_country:
            team_issues.append(_issue(
                DataQualitySeverity.INFO,
                "COUNTRY_NOT_ISO",
                f"strCountry '{str_country}' is a full country name, "
                f"not an ISO 3166-1 alpha-3 code. country_code set to None.",
                field_path=f"{field_prefix}.strCountry",
            ))

        # --- Optional: strBadge (report-only, not used for model) ---
        str_badge = item.get("strBadge")
        if str_badge:
            team_issues.append(_issue(
                DataQualitySeverity.INFO,
                "BADGE_REPORT_ONLY",
                f"strBadge present for '{str_team or id_team}' — "
                f"report/display only; does not affect model.",
                field_path=f"{field_prefix}.strBadge",
            ))

        # --- External IDs ---
        external_ids: dict[str, str] = {}
        if id_team:
            external_ids["thesportsdb"] = str(id_team)

        # --- Build canonical team ---
        team_id = str(id_team).strip() if id_team else "UNKNOWN"
        display_name = str(str_team).strip() if str_team else "UNKNOWN"

        prov = _build_item_provenance(result, "teams")

        team = CanonicalTeam(
            team_id=team_id,
            display_name=display_name,
            country_code=country_code,
            external_ids=external_ids,
            provenance_refs=(prov,),
            data_quality=tuple(team_issues),
        )
        teams.append(team)
        # Accumulate per-item issues into result-level issues
        all_issues.extend(team_issues)

    return _build_mapping_result(result, tuple(teams), tuple(all_issues))


# ==========================================================================
# Public API — map_thesportsdb_matches
# ==========================================================================


def map_thesportsdb_matches(result: ProviderFetchResult) -> MappingResult:
    """Map TheSportsDB matches (events) raw payload → ``CanonicalMatch`` entities.

    Expected raw payload shape::

        {"events": [{"idEvent": ..., "strHomeTeam": ..., "strAwayTeam": ...,
                      "dateEvent": ..., "strTime": ..., ...}, ...]}

    TheSportsDB ``eventsnextleague.php`` returns only the next 5 events —
    a ``LIMITED_MATCH_COVERAGE`` warning is always emitted.

    Returns a ``MappingResult`` with canonical matches and data quality issues.
    Does NOT enter the prediction engine.
    """
    all_issues: list[DataQualityIssue] = []
    all_issues.extend(_common_issues(result.source_reference, "matches"))
    matches: list[CanonicalMatch] = []
    payload = result.payload

    # ── eventsnextleague limited coverage ──
    if "eventsnextleague" in result.source_reference.lower():
        all_issues.append(_issue(
            DataQualitySeverity.WARNING,
            "LIMITED_MATCH_COVERAGE",
            "eventsnextleague endpoint returns limited events (typically next 5). "
            "Match coverage is incomplete — not all tournament fixtures available.",
            field_path="source_reference",
        ))

    # ── Schema check ──
    if "events" not in payload:
        all_issues.append(_issue(
            DataQualitySeverity.ERROR,
            "UNKNOWN_SCHEMA",
            "Payload does not contain 'events' key — unknown schema shape. "
            "Expected TheSportsDB eventsnextleague.php response.",
            field_path="payload",
        ))
        return _build_mapping_result(result, tuple(matches), tuple(all_issues))

    event_list = payload.get("events")
    if not isinstance(event_list, (list, tuple)):
        all_issues.append(_issue(
            DataQualitySeverity.ERROR,
            "UNKNOWN_SCHEMA",
            f"Payload 'events' is {type(event_list).__name__}, expected list. "
            f"Unknown schema shape.",
            field_path="payload.events",
        ))
        return _build_mapping_result(result, tuple(matches), tuple(all_issues))

    # ── Empty payload ──
    if len(event_list) == 0:
        all_issues.append(_issue(
            DataQualitySeverity.BLOCKING,
            "EMPTY_MATCHES_PAYLOAD",
            "TheSportsDB matches payload is empty — no event entries to map.",
            field_path="payload.events",
        ))
        return _build_mapping_result(result, tuple(matches), tuple(all_issues))

    # ── Map each event entry ──
    for idx, item in enumerate(event_list):
        if not isinstance(item, dict):
            all_issues.append(_issue(
                DataQualitySeverity.ERROR,
                "UNKNOWN_SCHEMA",
                f"events[{idx}] is {type(item).__name__}, expected dict.",
                field_path=f"payload.events[{idx}]",
            ))
            continue

        match_issues: list[DataQualityIssue] = []
        field_prefix = f"payload.events[{idx}]"

        # --- Required: idEvent ---
        id_event = item.get("idEvent")
        if not id_event or (isinstance(id_event, str) and not id_event.strip()):
            match_issues.append(_issue(
                DataQualitySeverity.BLOCKING,
                "MISSING_MATCH_PROVIDER_ID",
                f"events[{idx}] missing idEvent — cannot assign canonical match_id.",
                field_path=f"{field_prefix}.idEvent",
            ))

        # --- Required: home team ---
        str_home = item.get("strHomeTeam")
        id_home = item.get("idHomeTeam")
        if not str_home and not id_home:
            match_issues.append(_issue(
                DataQualitySeverity.BLOCKING,
                "MISSING_HOME_TEAM",
                f"events[{idx}] missing both strHomeTeam and idHomeTeam.",
                field_path=f"{field_prefix}.strHomeTeam",
            ))

        # --- Required: away team ---
        str_away = item.get("strAwayTeam")
        id_away = item.get("idAwayTeam")
        if not str_away and not id_away:
            match_issues.append(_issue(
                DataQualitySeverity.BLOCKING,
                "MISSING_AWAY_TEAM",
                f"events[{idx}] missing both strAwayTeam and idAwayTeam.",
                field_path=f"{field_prefix}.strAwayTeam",
            ))

        # --- Kickoff time ---
        date_event = item.get("dateEvent")
        str_time = item.get("strTime", "00:00:00")
        kickoff_at: datetime | None = None

        if date_event:
            if isinstance(date_event, str) and date_event.strip():
                dt_str = f"{date_event}T{str_time}"
                parsed = _try_parse_iso_utc(dt_str)
                if parsed is not None:
                    kickoff_at = parsed
                    # TheSportsDB does not provide timezone info
                    match_issues.append(_issue(
                        DataQualitySeverity.WARNING,
                        "TIMEZONE_UNKNOWN",
                        f"TheSportsDB dateEvent + strTime have no timezone — "
                        f"kickoff_at treated as UTC. True kickoff timezone is unknown.",
                        field_path=f"{field_prefix}.dateEvent",
                    ))
                else:
                    match_issues.append(_issue(
                        DataQualitySeverity.BLOCKING,
                        "KICKOFF_UNPARSEABLE",
                        f"Cannot parse kickoff time from "
                        f"dateEvent={date_event!r} strTime={str_time!r}.",
                        field_path=f"{field_prefix}.dateEvent",
                    ))
            else:
                match_issues.append(_issue(
                    DataQualitySeverity.BLOCKING,
                    "KICKOFF_UNPARSEABLE",
                    f"dateEvent is not a parseable string: {date_event!r}.",
                    field_path=f"{field_prefix}.dateEvent",
                ))
        else:
            match_issues.append(_issue(
                DataQualitySeverity.BLOCKING,
                "MISSING_KICKOFF",
                f"events[{idx}] missing dateEvent — cannot determine kickoff time.",
                field_path=f"{field_prefix}.dateEvent",
            ))

        # Fallback kickoff if unparseable (needed for CanonicalMatch validation)
        if kickoff_at is None:
            kickoff_at = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

        # --- Team IDs for canonical match ---
        # Prefer idHomeTeam/idAwayTeam (numeric/provider IDs);
        # fall back to strHomeTeam/strAwayTeam (display names).
        team_a_id = str(id_home).strip() if id_home else (
            str(str_home).strip() if str_home else "UNKNOWN-A")
        team_b_id = str(id_away).strip() if id_away else (
            str(str_away).strip() if str_away else "UNKNOWN-B")

        # Guard against same-team match (data error)
        if team_a_id == team_b_id:
            match_issues.append(_issue(
                DataQualitySeverity.BLOCKING,
                "SAME_TEAM_MATCH",
                f"Home and away team resolve to same id '{team_a_id}' — "
                f"likely data error in provider payload.",
                field_path=f"{field_prefix}.strHomeTeam",
            ))
            # Make them distinct so CanonicalMatch can be constructed
            team_a_id = f"{team_a_id}-HOME"
            team_b_id = f"{team_b_id}-AWAY"

        # --- Match identity ---
        match_id = str(id_event).strip() if id_event else "UNKNOWN"

        # --- Venue ---
        str_venue = item.get("strVenue") or None

        # --- Build canonical match ---
        prov = _build_item_provenance(result, "matches")

        try:
            match = CanonicalMatch(
                match_id=match_id,
                team_a_id=team_a_id,
                team_b_id=team_b_id,
                kickoff_at=kickoff_at,
                stage="group",
                venue=str_venue,
                neutral_site=True,
                provenance_refs=(prov,),
                data_quality=tuple(match_issues),
            )
            matches.append(match)
        except ValueError as exc:
            match_issues.append(_issue(
                DataQualitySeverity.BLOCKING,
                "CANONICAL_MATCH_CREATION_FAILED",
                f"Cannot create CanonicalMatch for event[{idx}] "
                f"(idEvent={id_event!r}): {exc}",
                field_path=field_prefix,
            ))
        # Accumulate per-item issues into result-level issues
        all_issues.extend(match_issues)

    return _build_mapping_result(result, tuple(matches), tuple(all_issues))


# ==========================================================================
# Internal helpers
# ==========================================================================


def _build_mapping_result(
    result: ProviderFetchResult,
    canonical_items: tuple,
    issues: tuple[DataQualityIssue, ...],
) -> MappingResult:
    """Assemble a ``MappingResult`` from a provider result and mapped items."""
    return MappingResult(
        provider_name=result.provider_name,
        capability=result.capability.value,
        canonical_items=canonical_items,
        data_quality_issues=issues,
        provenance=_build_mapping_provenance(result),
        source_reference=result.source_reference,
        raw_payload_hash=result.raw_payload_hash,
        model_boundary=ModelBoundary(),
    )
