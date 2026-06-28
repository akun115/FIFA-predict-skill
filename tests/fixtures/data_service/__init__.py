"""Deterministic fictional fixtures for Data Service v1 schema tests.

ALL FIXTURES ARE FICTIONAL.  No real teams, players, matches, odds, or news.
Every name is explicitly synthetic (``Fictional Alpha FC``, ``Fictional Beta FC``,
``Fake Player One``, etc.).  Timestamps and hashes are fixed.

These fixtures are designed to be:
  - deterministic (same inputs → same outputs every run)
  - self-documenting (field names make the fictional nature obvious)
  - sufficient for schema validation and import-boundary tests
"""

from __future__ import annotations

from datetime import datetime, timezone

from oracle_core.data_service_types import (
    CanonicalMatch,
    CanonicalTeam,
    DataQualityIssue,
    DataQualitySeverity,
    GroupStandingContext,
    GroupStandingRow,
    InjuryContext,
    InjuryStatus,
    KnockoutBracketContext,
    LineupContext,
    LineupStatus,
    MatchContextSnapshot,
    OddsMarketContext,
    OddsSelection,
    PlayerSlot,
    PrematchSignal,
    ProviderProvenance,
    SignalConfidence,
    SuspensionContext,
    make_fixture_dq_issue,
    make_fixture_provenance,
)


# ── Fixed timestamps (UTC) ──

FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
FIXED_KICKOFF = datetime(2026, 6, 16, 20, 0, 0, tzinfo=timezone.utc)
FIXED_FETCH = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)


# ── Provenance ──

FAKE_PROVENANCE = make_fixture_provenance("fake_provider_v1", "default")


# ── Teams ──

FICTIONAL_TEAM_ALPHA = CanonicalTeam(
    team_id="FIC-ALPHA",
    display_name="Fictional Alpha FC",
    country_code="FIC",
    external_ids={"fake_provider_v1": "FAKE-001"},
    provenance_refs=(FAKE_PROVENANCE,),
)

FICTIONAL_TEAM_BETA = CanonicalTeam(
    team_id="FIC-BETA",
    display_name="Fictional Beta FC",
    country_code="FIC",
    external_ids={"fake_provider_v1": "FAKE-002"},
    provenance_refs=(FAKE_PROVENANCE,),
)

FICTIONAL_TEAM_GAMMA = CanonicalTeam(
    team_id="FIC-GAMMA",
    display_name="Fictional Gamma FC",
    country_code="FIC",
    external_ids={"fake_provider_v1": "FAKE-003"},
    provenance_refs=(FAKE_PROVENANCE,),
)

FICTIONAL_TEAM_DELTA = CanonicalTeam(
    team_id="FIC-DELTA",
    display_name="Fictional Delta FC",
    country_code="FIC",
    external_ids={"fake_provider_v1": "FAKE-004"},
    provenance_refs=(FAKE_PROVENANCE,),
)


# ── Match ──

FICTIONAL_MATCH_ALPHA_BETA = CanonicalMatch(
    match_id="FIC-001",
    team_a_id="FIC-ALPHA",
    team_b_id="FIC-BETA",
    kickoff_at=FIXED_KICKOFF,
    stage="group",
    group="Fictional Group A",
    venue="Fictional Stadium One",
    neutral_site=True,
    provenance_refs=(FAKE_PROVENANCE,),
)

FICTIONAL_MATCH_KNOCKOUT = CanonicalMatch(
    match_id="FIC-KO-001",
    team_a_id="FIC-ALPHA",
    team_b_id="FIC-GAMMA",
    kickoff_at=datetime(2026, 7, 1, 20, 0, 0, tzinfo=timezone.utc),
    stage="QF",
    round_name="Quarter-final",
    venue="Fictional Grand Stadium",
    neutral_site=True,
    provenance_refs=(FAKE_PROVENANCE,),
)


# ── Group standings ──

FICTIONAL_GROUP_STANDINGS = GroupStandingContext(
    group_id="Fictional Group A",
    rows=(
        GroupStandingRow(position=1, team_id="FIC-ALPHA", played=2, won=2, drawn=0, lost=0,
                         goals_for=5, goals_against=1, goal_difference=4, points=6),
        GroupStandingRow(position=2, team_id="FIC-BETA", played=2, won=1, drawn=0, lost=1,
                         goals_for=2, goals_against=3, goal_difference=-1, points=3),
        GroupStandingRow(position=3, team_id="FIC-GAMMA", played=2, won=1, drawn=0, lost=1,
                         goals_for=2, goals_against=2, goal_difference=0, points=3),
        GroupStandingRow(position=4, team_id="FIC-DELTA", played=2, won=0, drawn=0, lost=2,
                         goals_for=1, goals_against=4, goal_difference=-3, points=0),
    ),
    provenance_refs=(FAKE_PROVENANCE,),
)


# ── Knockout bracket ──

FICTIONAL_KNOCKOUT_BRACKET = KnockoutBracketContext(
    bracket_id="FIC-KO-2026",
    round_name="Quarter-final",
    match_slots=("FIC-KO-001", "FIC-KO-002", "FIC-KO-003", "FIC-KO-004"),
    provenance_refs=(FAKE_PROVENANCE,),
)


# ── Odds (fictional, market comparison only) ──

FICTIONAL_ODDS = OddsMarketContext(
    match_id="FIC-001",
    market_type="1X2",
    selections=(
        OddsSelection(label="team_a_win", decimal_odds=2.10),
        OddsSelection(label="draw", decimal_odds=3.50),
        OddsSelection(label="team_b_win", decimal_odds=3.80),
    ),
    bookmaker="Fictional Bookmaker Ltd",
    captured_at=FIXED_FETCH,
    overround=0.065,
    normalized_probabilities={
        "team_a_win": 0.45,
        "draw": 0.27,
        "team_b_win": 0.28,
    },
    provenance_refs=(FAKE_PROVENANCE,),
)


# ── Lineups (fictional, report/audit only) ──

FICTIONAL_LINEUP_ALPHA = LineupContext(
    match_id="FIC-001",
    team_id="FIC-ALPHA",
    status=LineupStatus.CONFIRMED,
    formation="4-3-3",
    starting_xi=(
        PlayerSlot(name="Fake Player One", number=1, position="GK", is_captain=False),
        PlayerSlot(name="Fake Player Two", number=4, position="CB", is_captain=True),
        PlayerSlot(name="Fake Player Three", number=7, position="FW", is_captain=False),
    ),
    substitutes=(
        PlayerSlot(name="Fake Player Four", number=12, position="MF", is_captain=False),
    ),
    coach="Fake Coach Alpha",
    last_updated=FIXED_FETCH,
    provenance_refs=(FAKE_PROVENANCE,),
)

FICTIONAL_LINEUP_BETA = LineupContext(
    match_id="FIC-001",
    team_id="FIC-BETA",
    status=LineupStatus.PREDICTED,
    formation="4-4-2",
    starting_xi=(
        PlayerSlot(name="Fake Player Five", number=1, position="GK", is_captain=False),
        PlayerSlot(name="Fake Player Six", number=10, position="FW", is_captain=True),
    ),
    coach="Fake Coach Beta",
    last_updated=FIXED_FETCH,
    provenance_refs=(FAKE_PROVENANCE,),
)


# ── Injuries (fictional, report/audit only) ──

FICTIONAL_INJURY_ALPHA = InjuryContext(
    team_id="FIC-ALPHA",
    player_name="Fake Player Three",
    status=InjuryStatus.DOUBTFUL,
    injury_type="fictional hamstring strain",
    expected_return="2026-06-20",
    source_updated_at=FIXED_FETCH,
    provenance_refs=(FAKE_PROVENANCE,),
)

FICTIONAL_INJURY_BETA = InjuryContext(
    team_id="FIC-BETA",
    player_name="Fake Player Seven",
    status=InjuryStatus.OUT,
    injury_type="fictional knee sprain",
    expected_return="unknown",
    source_updated_at=FIXED_FETCH,
    provenance_refs=(FAKE_PROVENANCE,),
)


# ── Suspensions (fictional, report/audit only) ──

FICTIONAL_SUSPENSION_BETA = SuspensionContext(
    team_id="FIC-BETA",
    player_name="Fake Player Six",
    reason="yellow_accumulation",
    matches_suspended=1,
    remaining_matches=1,
    provenance_refs=(FAKE_PROVENANCE,),
)


# ── Prematch signals (fictional, report only) ──

FICTIONAL_SIGNAL_WEATHER = PrematchSignal(
    signal_id="FIC-SIG-001",
    match_id="FIC-001",
    category="weather",
    summary="Fictional mild rain expected at kickoff; no wind impact.",
    confidence=SignalConfidence.CONFIRMED,
    source_name="Fictional Weather Service",
    published_at=FIXED_FETCH,
    tags=("weather", "fictional"),
    provenance_refs=(FAKE_PROVENANCE,),
)

FICTIONAL_SIGNAL_TACTICAL = PrematchSignal(
    signal_id="FIC-SIG-002",
    match_id="FIC-001",
    category="tactical",
    summary=(
        "Fictional Alpha FC is expected to use a high-press approach "
        "against Fictional Beta FC's counter-attacking style."
    ),
    confidence=SignalConfidence.REPORTED,
    source_name="Fictional Tactical Analyst",
    published_at=FIXED_FETCH,
    tags=("tactical", "fictional"),
    provenance_refs=(FAKE_PROVENANCE,),
)


# ── Data quality issues ──

FICTIONAL_DQ_WARNING_STALE = make_fixture_dq_issue(
    DataQualitySeverity.WARNING,
    code="STALE_LINEUP",
    message="Lineup for FIC-BETA was last updated more than 24h before kickoff.",
    field_path="lineup_context.status",
)

FICTIONAL_DQ_BLOCKING = make_fixture_dq_issue(
    DataQualitySeverity.BLOCKING,
    code="MISSING_KICKOFF",
    message="Kickoff time is not present in any provider data.",
    field_path="match.kickoff_at",
)


# ── MatchContextSnapshot ──


def make_minimal_snapshot() -> MatchContextSnapshot:
    """Return the smallest valid ``MatchContextSnapshot``.

    Contains only match identity — no odds, lineups, injuries, suspensions,
    or prematch signals.  Useful as a baseline for boundary tests.
    """
    return MatchContextSnapshot(
        snapshot_id="FIC-SNAP-MINIMAL-001",
        snapshot_version="1.0.0",
        snapshot_created_at=FIXED_NOW,
        match=FICTIONAL_MATCH_ALPHA_BETA,
        team_a=FICTIONAL_TEAM_ALPHA,
        team_b=FICTIONAL_TEAM_BETA,
        provenance_refs=(FAKE_PROVENANCE,),
    )


def make_full_snapshot() -> MatchContextSnapshot:
    """Return a ``MatchContextSnapshot`` with all context fields populated.

    Includes group standings, odds, lineups, injuries, suspensions, and
    prematch signals — all fictional.  All context fields (odds, lineups,
    injuries, suspensions, signals) are ``report_only`` and MUST NOT be
    read by the prediction engine to modify probabilities in v1.
    """
    return MatchContextSnapshot(
        snapshot_id="FIC-SNAP-FULL-001",
        snapshot_version="1.0.0",
        snapshot_created_at=FIXED_NOW,
        match=FICTIONAL_MATCH_ALPHA_BETA,
        team_a=FICTIONAL_TEAM_ALPHA,
        team_b=FICTIONAL_TEAM_BETA,
        group_context=FICTIONAL_GROUP_STANDINGS,
        knockout_context=None,
        odds_context=FICTIONAL_ODDS,
        lineup_context=(FICTIONAL_LINEUP_ALPHA, FICTIONAL_LINEUP_BETA),
        injury_context=(FICTIONAL_INJURY_ALPHA, FICTIONAL_INJURY_BETA),
        suspension_context=(FICTIONAL_SUSPENSION_BETA,),
        prematch_signals=(FICTIONAL_SIGNAL_WEATHER, FICTIONAL_SIGNAL_TACTICAL),
        data_quality=(FICTIONAL_DQ_WARNING_STALE,),
        provenance_refs=(FAKE_PROVENANCE,),
    )


def make_blocking_snapshot() -> MatchContextSnapshot:
    """Return a ``MatchContextSnapshot`` with a blocking data quality issue.

    Used to verify that ``has_blocking_issues`` is ``True`` and that
    blocking issues are detectable without a prediction engine integration.
    """
    return MatchContextSnapshot(
        snapshot_id="FIC-SNAP-BLOCKING-001",
        snapshot_version="1.0.0",
        snapshot_created_at=FIXED_NOW,
        match=FICTIONAL_MATCH_ALPHA_BETA,
        team_a=FICTIONAL_TEAM_ALPHA,
        team_b=FICTIONAL_TEAM_BETA,
        data_quality=(FICTIONAL_DQ_BLOCKING,),
        provenance_refs=(FAKE_PROVENANCE,),
    )
