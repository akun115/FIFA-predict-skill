"""Tournament state computation — standings, incentives, qualification scenarios."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from .types import (
    GroupDefinition,
    GroupStandingsRow,
    GroupTable,
    IncentiveResult,
    ScheduledMatch,
    TeamIncentive,
    TournamentRules,
    TournamentState,
)

# ---------------------------------------------------------------------------
# Default rules — used as fallback when no YAML file is found
# ---------------------------------------------------------------------------

DEFAULT_WORLD_CUP_2026_RULES = TournamentRules(
    tournament_name="FIFA World Cup 2026",
    group_stage_format="12 groups of 4 teams, single round-robin",
    total_groups=12,
    teams_per_group=4,
    matchdays_per_group=3,
    top_n_per_group=2,
    best_third_place_count=8,
    total_advancing=32,
    group_tiebreakers=(
        "points", "goal_difference", "goals_for",
        "head_to_head_points", "head_to_head_goal_difference",
        "head_to_head_goals_for", "fair_play_points", "drawing_of_lots",
    ),
    best_third_place_criteria=(
        "points", "goal_difference", "goals_for",
        "fair_play_points", "drawing_of_lots",
    ),
)

# ---------------------------------------------------------------------------
# YAML loaders
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"required data file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return data


def load_aliases(path: str | Path) -> dict[str, str]:
    """Return {alias_name: canonical_name} for team normalization."""
    raw = _read_yaml(Path(path)).get("aliases", {})
    if not isinstance(raw, dict):
        raise ValueError("aliases must be a mapping")
    mapping: dict[str, str] = {}
    for canonical, variants in raw.items():
        c = str(canonical).strip()
        mapping[c] = c  # canonical → itself
        if variants:
            for v in variants:
                mapping[str(v).strip()] = c
    return mapping


def normalize_team_name(name: str, aliases: dict[str, str]) -> str:
    """Return canonical team name or original if no match found."""
    return aliases.get(name.strip(), name.strip())


def load_groups(path: str | Path, aliases: dict[str, str]) -> dict[str, GroupDefinition]:
    """Read groups.yaml → {group_name: GroupDefinition} with alias normalization."""
    raw = _read_yaml(Path(path))
    groups_raw = raw.get("groups", raw)
    result: dict[str, GroupDefinition] = {}
    for group_name, team_list in groups_raw.items():
        if not isinstance(team_list, list):
            raise ValueError(f"group '{group_name}' must contain a list of teams")
        normalized = tuple(normalize_team_name(str(t), aliases) for t in team_list)
        result[str(group_name)] = GroupDefinition(group_name=str(group_name), teams=normalized)
    return result


def load_schedule(path: str | Path, aliases: dict[str, str]) -> tuple[ScheduledMatch, ...]:
    """Read schedule.yaml → tuple of ScheduledMatch with alias normalization."""
    raw = _read_yaml(Path(path))
    matches_raw = raw.get("matches", raw)
    if not isinstance(matches_raw, list):
        raise ValueError("schedule must contain a 'matches' list")
    result: list[ScheduledMatch] = []
    for m in matches_raw:
        score = None
        raw_score = m.get("score")
        if raw_score and isinstance(raw_score, list) and len(raw_score) == 2:
            score = (int(raw_score[0]), int(raw_score[1]))
        result.append(ScheduledMatch(
            match_id=str(m["match_id"]),
            group_or_round=str(m.get("group_or_round", m.get("group", ""))),
            matchday=int(m.get("matchday", 1)),
            team_a=normalize_team_name(str(m["team_a"]), aliases),
            team_b=normalize_team_name(str(m["team_b"]), aliases),
            kickoff_utc=str(m.get("kickoff_utc", "")),
            venue=str(m.get("venue", "")),
            neutral_site=bool(m.get("neutral_site", True)),
            score=score,
            stats=deepcopy(m.get("stats")) if m.get("stats") else None,
        ))
    return tuple(result)


def load_rules(path: str | Path | None = None) -> TournamentRules:
    """Load TournamentRules from YAML or return DEFAULT fallback."""
    if path is None:
        return DEFAULT_WORLD_CUP_2026_RULES
    p = Path(path)
    if not p.is_file():
        return DEFAULT_WORLD_CUP_2026_RULES
    raw = _read_yaml(p)
    return TournamentRules(
        tournament_name=str(raw.get("tournament_name", DEFAULT_WORLD_CUP_2026_RULES.tournament_name)),
        group_stage_format=str(raw.get("group_stage_format", DEFAULT_WORLD_CUP_2026_RULES.group_stage_format)),
        total_groups=int(raw.get("total_groups", DEFAULT_WORLD_CUP_2026_RULES.total_groups)),
        teams_per_group=int(raw.get("teams_per_group", DEFAULT_WORLD_CUP_2026_RULES.teams_per_group)),
        matchdays_per_group=int(raw.get("matchdays_per_group", DEFAULT_WORLD_CUP_2026_RULES.matchdays_per_group)),
        top_n_per_group=int(raw.get("advancement", {}).get("group_stage", {}).get("top_n_per_group", DEFAULT_WORLD_CUP_2026_RULES.top_n_per_group)),
        best_third_place_count=int(raw.get("advancement", {}).get("group_stage", {}).get("best_third_place_count", DEFAULT_WORLD_CUP_2026_RULES.best_third_place_count)),
        total_advancing=int(raw.get("advancement", {}).get("group_stage", {}).get("total_advancing", DEFAULT_WORLD_CUP_2026_RULES.total_advancing)),
        group_tiebreakers=tuple(raw.get("group_tiebreakers", DEFAULT_WORLD_CUP_2026_RULES.group_tiebreakers)),
        best_third_place_criteria=tuple(raw.get("best_third_place_ranking", {}).get("criteria", DEFAULT_WORLD_CUP_2026_RULES.best_third_place_criteria)),
    )


# ---------------------------------------------------------------------------
# Standings computation
# ---------------------------------------------------------------------------


def compute_group_standings(
    schedule: tuple[ScheduledMatch, ...],
    groups: dict[str, GroupDefinition],
) -> dict[str, GroupTable]:
    """Aggregate completed matches → one GroupTable per group."""
    tables: dict[str, dict[str, dict[str, int]]] = {}
    for gname, gdef in groups.items():
        tables[gname] = {
            t: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0}
            for t in gdef.teams
        }

    for match in schedule:
        if not match.is_completed:
            continue
        gname = match.group_or_round
        if gname not in tables:
            continue
        if match.team_a not in tables[gname] or match.team_b not in tables[gname]:
            continue
        sa, sb = match.score  # type: ignore[misc]
        for team, gf, ga in ((match.team_a, sa, sb), (match.team_b, sb, sa)):
            row = tables[gname][team]
            row["p"] += 1
            row["gf"] += gf
            row["ga"] += ga
        if sa > sb:
            tables[gname][match.team_a]["w"] += 1
            tables[gname][match.team_b]["l"] += 1
            tables[gname][match.team_a]["pts"] += 3
        elif sa < sb:
            tables[gname][match.team_a]["l"] += 1
            tables[gname][match.team_b]["w"] += 1
            tables[gname][match.team_b]["pts"] += 3
        else:
            tables[gname][match.team_a]["d"] += 1
            tables[gname][match.team_b]["d"] += 1
            tables[gname][match.team_a]["pts"] += 1
            tables[gname][match.team_b]["pts"] += 1

    for gname in tables:
        for t in tables[gname]:
            tables[gname][t]["gd"] = tables[gname][t]["gf"] - tables[gname][t]["ga"]

    result: dict[str, GroupTable] = {}
    for gname, team_data in tables.items():
        sorted_teams = sorted(
            team_data.items(),
            key=lambda item: (-item[1]["pts"], -item[1]["gd"], -item[1]["gf"], item[0]),
        )
        rows: list[GroupStandingsRow] = []
        for pos, (team, data) in enumerate(sorted_teams, start=1):
            rows.append(GroupStandingsRow(
                position=pos, team=team,
                played=data["p"], won=data["w"], drawn=data["d"], lost=data["l"],
                goals_for=data["gf"], goals_against=data["ga"],
                goal_difference=data["gd"], points=data["pts"],
            ))
        result[gname] = GroupTable(group_name=gname, rows=tuple(rows))
    return result


# ---------------------------------------------------------------------------
# Incentive derivation
# ---------------------------------------------------------------------------


def _find_team_row(table: GroupTable, team: str) -> GroupStandingsRow | None:
    for row in table.rows:
        if row.team == team:
            return row
    return None


def _remaining_for_group(
    schedule: tuple[ScheduledMatch, ...], group_name: str
) -> tuple[ScheduledMatch, ...]:
    return tuple(
        m for m in schedule
        if m.group_or_round == group_name and not m.is_completed
    )


def _max_possible_points(team_row: GroupStandingsRow, remaining: tuple[ScheduledMatch, ...]) -> int:
    matches_left = sum(1 for m in remaining if team_row.team in (m.team_a, m.team_b))
    return team_row.points + matches_left * 3


def _draw_sufficient_for_top_n(
    table: GroupTable,
    team: str,
    top_n: int,
    team_remaining: tuple[ScheduledMatch, ...],
    all_remaining: tuple[ScheduledMatch, ...],
) -> bool:
    """Can `team` secure a top-N finish by drawing every remaining match?

    Opponents who play against `team` in those remaining matches also draw
    (they cannot win a match that `team` draws).  Opponents not facing
    `team` are free to win all their remaining fixtures.
    """
    team_row = _find_team_row(table, team)
    if team_row is None or not team_remaining:
        return False

    draw_final_pts = team_row.points + len(team_remaining) * 1

    # Opponents who play *against* team in the remaining matches
    opponent_caps: dict[str, int] = {}
    for m in team_remaining:
        for side in (m.team_a, m.team_b):
            if side != team:
                opponent_caps[side] = opponent_caps.get(side, 0) + 1

    passing = 0
    for row in table.rows:
        if row.team == team:
            continue
        if row.team in opponent_caps:
            # They draw against team → max = current pts + draws (1pt each)
            opp_max = row.points + opponent_caps[row.team] * 1
        else:
            opp_max = _max_possible_points(row, all_remaining)
        if opp_max > draw_final_pts:
            passing += 1

    return passing < top_n


def _can_finish_top_n(
    table: GroupTable, team: str, n: int, remaining: tuple[ScheduledMatch, ...]
) -> bool:
    """Can `team` mathematically finish in the top `n` of the group?

    A team can finish top-N if there are fewer than N opponents whose
    *minimum* possible final points strictly exceed the team's *maximum*
    possible final points.
    """
    team_row = _find_team_row(table, team)
    if team_row is None:
        return False
    team_max = _max_possible_points(team_row, remaining)
    # Count opponents guaranteed to finish above team's max
    guaranteed_above = 0
    for row in table.rows:
        if row.team == team:
            continue
        # Opponent's MINIMUM final points = current points (they lose all remaining)
        # If this minimum > team's maximum, opponent is uncatchable
        opp_min = row.points
        if opp_min > team_max:
            guaranteed_above += 1
    return guaranteed_above < n


def _can_be_caught_from_below(
    table: GroupTable, team: str, remaining: tuple[ScheduledMatch, ...]
) -> bool:
    """Can any team below `team` catch up in points?"""
    team_row = _find_team_row(table, team)
    if team_row is None:
        return True
    for row in table.rows:
        if row.team == team:
            continue
        if row.position > team_row.position:
            if _max_possible_points(row, remaining) >= team_row.points:
                return True
    return False


def _ordinal_suffix(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def derive_incentive(
    table: GroupTable,
    team: str,
    matchday: int,
    remaining: tuple[ScheduledMatch, ...],
    rules: TournamentRules,
) -> IncentiveResult:
    """Determine a single team's incentive from current group state."""
    team_row = _find_team_row(table, team)
    if team_row is None:
        return IncentiveResult(
            primary_incentive=TeamIncentive.NO_CLEAR_INCENTIVE,
            incentive_flags=(),
            intensity=None,
            description=f"Team '{team}' not found in group {table.group_name} standings.",
        )

    top2_possible = _can_finish_top_n(table, team, rules.top_n_per_group, remaining)
    top3_possible = _can_finish_top_n(table, team, 3, remaining)
    already_top2 = team_row.position <= rules.top_n_per_group and not _can_be_caught_from_below(table, team, remaining)
    already_eliminated_from_top2 = not top2_possible
    force_eliminated = not top3_possible  # can't even reach top 3

    # Are there more points still to play for this team?
    team_remaining = tuple(m for m in remaining if team in (m.team_a, m.team_b))
    matches_left = len(team_remaining)

    flags: list[str] = []
    if matches_left == 0:
        flags.append("all_matches_completed")
    else:
        flags.append(f"{matches_left}_matches_remaining")

    # --- Determine primary incentive ---

    # All matches completed → final position determines outcome
    if matches_left == 0:
        if team_row.position <= rules.top_n_per_group:
            primary = TeamIncentive.ALREADY_QUALIFIED_ROTATION_RISK
            intensity = 0.0
            desc = f"{team} finished {team_row.position}{_ordinal_suffix(team_row.position)} in Group {table.group_name} and has qualified."
        elif team_row.position == rules.top_n_per_group + 1:
            primary = TeamIncentive.THIRD_PLACE_DEPENDENT
            intensity = 0.0
            flags.append("best_third_place_possible")
            desc = f"{team} finished {team_row.position}rd in Group {table.group_name}. Qualification depends on other groups."
        else:
            primary = TeamIncentive.ELIMINATED_LOW_PRESSURE
            intensity = 0.0
            desc = f"{team} finished {team_row.position}th in Group {table.group_name} and is eliminated."

    # Early matchday (1 or early 2) → insufficient data
    elif matchday <= 1 and matches_left >= 2:
        primary = TeamIncentive.NO_CLEAR_INCENTIVE
        intensity = None
        desc = f"{team} is in early stages of Group {table.group_name}; insufficient data to determine a single incentive."

    elif force_eliminated:
        primary = TeamIncentive.ELIMINATED_LOW_PRESSURE
        intensity = 0.0
        desc = (
            f"{team} cannot reach top 3 in Group {table.group_name}; "
            "eliminated with no remaining mathematical path to advance."
        )

    elif already_top2:
        primary = TeamIncentive.ALREADY_QUALIFIED_ROTATION_RISK
        intensity = 0.2
        flags.append("rotation_risk")
        # Check if top spot is still at stake
        if team_row.position == 1 and _can_be_caught_from_below(table, team, remaining):
            if _find_team_row(table, table.rows[1].team):
                flags.append("top_spot_at_stake")
        desc = (
            f"{team} has already secured a top-{rules.top_n_per_group} finish "
            f"in Group {table.group_name}. Rotation risk: may rest key players."
        )

    elif already_eliminated_from_top2:
        # Can only finish 3rd — must rely on best-third-place ranking
        primary = TeamIncentive.THIRD_PLACE_DEPENDENT
        intensity = 0.5
        flags.append("best_third_place_possible")
        desc = (
            f"{team} cannot finish top {rules.top_n_per_group} in Group {table.group_name} "
            f"and will likely finish 3rd. Qualification depends on performance "
            f"relative to 3rd-place teams from other groups."
        )

    else:
        # Matchday 2 or 3 with realistic top-2 chance.
        # Use a positional heuristic: if you're inside the top N,
        # assesses whether a draw is sufficient. If outside, you need a win.
        points_behind_second = 0
        if team_row.position > rules.top_n_per_group and len(table.rows) >= rules.top_n_per_group:
            second_place_row = table.rows[rules.top_n_per_group - 1]
            points_behind_second = second_place_row.points - team_row.points

        if team_row.position <= rules.top_n_per_group:
            # Currently in qualifying position
            if matchday == rules.matchdays_per_group:
                if _draw_sufficient_for_top_n(
                    table, team, rules.top_n_per_group,
                    team_remaining, remaining,
                ):
                    primary = TeamIncentive.DRAW_SUFFICIENT_FOR_TOP2
                    intensity = 0.3
                    desc = f"{team} is in the top {rules.top_n_per_group} in Group {table.group_name}; a draw mathematically secures advancement."
                else:
                    primary = TeamIncentive.DRAW_REQUIRES_HELP
                    intensity = 0.6
                    flags.append("depends_on_other_match")
                    desc = f"{team} may need a result and help from other matches to advance."
            else:
                primary = TeamIncentive.DRAW_SUFFICIENT_FOR_TOP2
                intensity = 0.3
                desc = f"{team} is in a qualifying position in Group {table.group_name}."
        else:
            # Outside qualifying position
            if matchday == rules.matchdays_per_group and points_behind_second <= 3:
                primary = TeamIncentive.MUST_WIN_FOR_TOP2
                intensity = 1.0
                desc = f"{team} must win to have a chance of a top-{rules.top_n_per_group} finish in Group {table.group_name}."
            elif points_behind_second <= 3:
                primary = TeamIncentive.MUST_WIN_TO_STAY_ALIVE
                intensity = 1.0
                desc = f"{team} must win to stay in contention for top {rules.top_n_per_group} in Group {table.group_name}."
            else:
                primary = TeamIncentive.DRAW_REQUIRES_HELP
                intensity = 0.6
                flags.append("depends_on_other_match")
                desc = f"{team} needs a result and favorable outcomes in other matches."

    # Check top-spot context (only when matches remain)
    if matches_left > 0 and primary not in (TeamIncentive.ELIMINATED_LOW_PRESSURE,):
        if team_row.position == 1 and _can_be_caught_from_below(table, team, remaining):
            flags.append("top_spot_can_be_lost")
            if primary in (TeamIncentive.DRAW_SUFFICIENT_FOR_TOP2,):
                flags.append("group_winner_at_stake")

    return IncentiveResult(
        primary_incentive=primary,
        incentive_flags=tuple(flags),
        intensity=intensity,
        description=desc,
    )


# ---------------------------------------------------------------------------
# Qualification scenarios (simplified)
# ---------------------------------------------------------------------------


def derive_qualification_scenarios(
    table: GroupTable,
    team: str,
    remaining: tuple[ScheduledMatch, ...],
    rules: TournamentRules,
) -> list[dict[str, str]]:
    """Return human-readable qualification scenarios."""
    incentive = derive_incentive(table, team, 3, remaining, rules)
    team_row = _find_team_row(table, team)
    if team_row is None:
        return []

    scenarios: list[dict[str, str]] = []
    if incentive.primary_incentive == TeamIncentive.ALREADY_QUALIFIED_ROTATION_RISK:
        scenarios.append({
            "condition": "already_qualified",
            "outcome": f"Regardless of result, {team} advances to Round of 32.",
        })
    elif incentive.primary_incentive == TeamIncentive.ELIMINATED_LOW_PRESSURE:
        scenarios.append({
            "condition": "eliminated",
            "outcome": f"Regardless of result, {team} is eliminated.",
        })
    elif incentive.primary_incentive == TeamIncentive.THIRD_PLACE_DEPENDENT:
        scenarios.append({
            "condition": "likely_third",
            "outcome": (
                f"{team} will likely finish 3rd in Group {table.group_name}. "
                f"Advancement depends on ranking among all 12 third-place teams "
                f"(top {rules.best_third_place_count} advance)."
            ),
        })
    else:
        # Generic win/draw/loss scenarios
        win_msg = f"If {team} wins: "
        draw_msg = f"If {team} draws: "
        loss_msg = f"If {team} loses: "

        if incentive.primary_incentive == TeamIncentive.MUST_WIN_FOR_TOP2:
            win_msg += "likely advances to Round of 32."
            draw_msg += "likely eliminated."
            loss_msg += "eliminated."
        elif incentive.primary_incentive == TeamIncentive.DRAW_SUFFICIENT_FOR_TOP2:
            win_msg += "advances (may win group)."
            draw_msg += "advances."
            loss_msg += "may need help from other matches."
        elif incentive.primary_incentive == TeamIncentive.MUST_WIN_TO_STAY_ALIVE:
            win_msg += "keeps qualification hopes alive."
            draw_msg += "likely eliminated."
            loss_msg += "eliminated."
        elif incentive.primary_incentive == TeamIncentive.DRAW_REQUIRES_HELP:
            win_msg += "good chance to advance."
            draw_msg += "needs favorable results in other matches."
            loss_msg += "likely eliminated."
        else:
            win_msg += "improves qualification chances."
            draw_msg += "keeps qualification possible."
            loss_msg += "reduces qualification chances."

        scenarios.extend([
            {"condition": "win", "outcome": win_msg},
            {"condition": "draw", "outcome": draw_msg},
            {"condition": "loss", "outcome": loss_msg},
        ])
    return scenarios


# ---------------------------------------------------------------------------
# Round-robin integrity check
# ---------------------------------------------------------------------------


def check_round_robin_integrity(
    schedule: tuple[ScheduledMatch, ...],
    group_name: str,
    teams: tuple[str, ...],
) -> dict:
    """Check that a group's schedule satisfies single-round-robin.

    Returns a dict with:
        status: "ok" if no issues, "warning" if pairings are broken.
        issues: list of human-readable issue strings.

    This function is the single source of truth for round-robin validation —
    used by both ``get_tournament_state`` (data-quality guard) and
    ``tests/test_schedule_integrity.py`` (structural integrity tests).
    """
    expected_pairs: set[tuple[str, str]] = {
        tuple(sorted(p)) for p in combinations(teams, 2)  # type: ignore[arg-type]
    }
    actual_pairs: set[tuple[str, str]] = set()
    dupes: list[str] = []

    for m in schedule:
        if m.group_or_round != group_name:
            continue
        pair = (min(m.team_a, m.team_b), max(m.team_a, m.team_b))
        if pair in actual_pairs:
            dupes.append(f"{pair[0]} vs {pair[1]}")
        actual_pairs.add(pair)

    missing = sorted(
        f"{p[0]} vs {p[1]}" for p in (expected_pairs - actual_pairs)
    )
    issues: list[str] = []
    for d in dupes:
        issues.append(f"duplicate_pair: {d}")
    for m in missing:
        issues.append(f"missing_pair: {m}")

    return {
        "status": "warning" if issues else "ok",
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Consistency check
# ---------------------------------------------------------------------------


def validate_schedule_results_consistency(
    schedule: tuple[ScheduledMatch, ...],
    match_results: list[dict],
) -> list[str]:
    """Check that completed schedule matches match the settlement audit log.

    Returns a list of warning strings. Empty list = no inconsistencies found.
    """
    warnings: list[str] = []
    results_by_id: dict[str, dict] = {r["id"]: r for r in match_results}
    for m in schedule:
        if not m.is_completed:
            continue
        settled = results_by_id.get(m.match_id)
        if settled is None:
            continue  # not yet settled — not an error
        settled_score = settled.get("score")
        if settled_score and list(settled_score) != list(m.score):
            warnings.append(
                f"score mismatch for {m.match_id}: "
                f"schedule={list(m.score)} vs match-results={settled_score}"
            )
    return warnings


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_tournament_state(
    match_id: str,
    schedule: tuple[ScheduledMatch, ...],
    groups: dict[str, GroupDefinition],
    rules: TournamentRules,
    *,
    state_mode: str = "current",
) -> TournamentState:
    """Orchestrate all computation for one match.

    Args:
        match_id: Target match identifier.
        schedule: All scheduled matches (completed + future).
        groups: Group definitions.
        rules: Tournament advancement and tiebreaker rules.
        state_mode:
            - \"current\": Standings include ALL completed matches (default).
            - \"pre_match\": Standings EXCLUDE the target match and all
              simultaneous group matches (same group, same matchday).
              This reconstructs the table as it was before kickoff.
    """
    if state_mode not in ("current", "pre_match"):
        raise ValueError(f"state_mode must be 'current' or 'pre_match', got {state_mode!r}")

    now = _now_utc()
    target = next((m for m in schedule if m.match_id == match_id), None)
    if target is None:
        raise ValueError(f"match_id '{match_id}' not found in schedule")

    group_name = target.group_or_round

    # --- Determine which matches to exclude ---
    excluded_ids: set[str] = set()
    if state_mode == "pre_match":
        # Exclude the target match itself
        excluded_ids.add(match_id)
        # Also exclude simultaneous group matches (same group, same matchday)
        for m in schedule:
            if m.group_or_round == group_name and m.matchday == target.matchday:
                excluded_ids.add(m.match_id)

    # --- Filtered schedule for standings ---
    effective_schedule = tuple(m for m in schedule if m.match_id not in excluded_ids)

    # --- Simultaneous matches (for reporting) ---
    simultaneous: list[dict[str, str]] = []
    for m in schedule:
        if m.match_id == match_id:
            continue
        if m.group_or_round == group_name and m.matchday == target.matchday:
            simultaneous.append({
                "match_id": m.match_id,
                "team_a": m.team_a,
                "team_b": m.team_b,
                "kickoff_utc": m.kickoff_utc,
            })

    # --- Compute standings ---
    standings = compute_group_standings(effective_schedule, groups)
    table = standings.get(group_name)

    # Remaining matches: uncompleted matches from filtered schedule, plus
    # in pre_match mode the excluded matches are "future" from that viewpoint
    remaining = _remaining_for_group(effective_schedule, group_name)
    if state_mode == "pre_match":
        seen = {m.match_id for m in remaining}
        extra = []
        for m in schedule:
            if m.match_id in excluded_ids and m.group_or_round == group_name and m.match_id not in seen:
                extra.append(ScheduledMatch(
                    match_id=m.match_id, group_or_round=m.group_or_round,
                    matchday=m.matchday, team_a=m.team_a, team_b=m.team_b,
                    kickoff_utc=m.kickoff_utc, venue=m.venue,
                    neutral_site=m.neutral_site,
                    score=None,  # treat as unplayed from pre-match viewpoint
                ))
        remaining = remaining + tuple(extra)

    # --- Derive incentives ---
    if table is not None:
        a_incentive = derive_incentive(table, target.team_a, target.matchday, remaining, rules)
        b_incentive = derive_incentive(table, target.team_b, target.matchday, remaining, rules)
        a_scenarios = derive_qualification_scenarios(table, target.team_a, remaining, rules)
        b_scenarios = derive_qualification_scenarios(table, target.team_b, remaining, rules)
    else:
        a_incentive = IncentiveResult(TeamIncentive.NO_CLEAR_INCENTIVE, (), None, "Group not found")
        b_incentive = IncentiveResult(TeamIncentive.NO_CLEAR_INCENTIVE, (), None, "Group not found")
        a_scenarios = []
        b_scenarios = []

    stale_dt = datetime.now(timezone.utc) + timedelta(hours=6)

    # --- Round-robin integrity check ---
    # Check the FULL schedule (not effective_schedule), because structural
    # pairing issues exist independently of pre_match filtering.
    dq: dict | None = None
    if group_name in groups:
        dq = check_round_robin_integrity(schedule, group_name, groups[group_name].teams)

    return TournamentState(
        match_id=match_id,
        generated_at=now,
        stale_after=stale_dt.isoformat(),
        state_mode=state_mode,
        state_timestamp_utc=(
            target.kickoff_utc if state_mode == "pre_match" else now
        ),
        excluded_matches=tuple(sorted(excluded_ids)),
        data_sources={
            "standings_from_completed_matches": sum(1 for m in effective_schedule if m.is_completed),
            "total_scheduled_matches": len(schedule),
            "effective_matches_used": len(effective_schedule),
            "groups_loaded": len(groups),
        },
        match_context={
            "kickoff_time_utc": target.kickoff_utc,
            "group_or_round": group_name,
            "matchday": target.matchday,
            "team_a": target.team_a,
            "team_b": target.team_b,
            "venue": target.venue,
        },
        group_standings_before_match=table,
        simultaneous_group_matches=tuple(simultaneous),
        qualification_scenarios={
            "team_a": a_scenarios,
            "team_b": b_scenarios,
        },
        team_a_incentive=a_incentive,
        team_b_incentive=b_incentive,
        knockout_edge_if_known=None,
        data_quality=dq,
    )
