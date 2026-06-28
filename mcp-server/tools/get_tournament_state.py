"""MCP Tool: get_tournament_state — tournament context for one match."""

from __future__ import annotations

import json
from pathlib import Path

from oracle_core.tournament import (
    get_tournament_state,
    load_aliases,
    load_groups,
    load_rules,
    load_schedule,
)


def run_get_tournament_state(
    match_id: str,
    *,
    knowledge_root: str = "",
    state_mode: str = "current",
) -> str:
    root = Path(knowledge_root) if knowledge_root else Path(__file__).parents[2] / "knowledge"

    aliases = load_aliases(root / "L2-states" / "team-aliases.yaml")
    groups = load_groups(root / "L2-states" / "groups.yaml", aliases)
    schedule = load_schedule(root / "L1-events" / "schedule.yaml", aliases)
    rules = load_rules(root / "L2-states" / "tournament-rules-2026.yaml")

    state = get_tournament_state(match_id, schedule, groups, rules, state_mode=state_mode)

    payload = {
        "match_id": state.match_id,
        "generated_at": state.generated_at,
        "stale_after": state.stale_after,
        "state_mode": state.state_mode,
        "state_timestamp_utc": state.state_timestamp_utc,
        "excluded_matches": list(state.excluded_matches),
        "data_sources": state.data_sources,
        "match_context": state.match_context,
        "simultaneous_group_matches": list(state.simultaneous_group_matches),
        "qualification_scenarios": state.qualification_scenarios,
        "team_a_incentive": {
            "primary_incentive": state.team_a_incentive.primary_incentive.value,
            "incentive_flags": list(state.team_a_incentive.incentive_flags),
            "intensity": state.team_a_incentive.intensity,
            "description": state.team_a_incentive.description,
        },
        "team_b_incentive": {
            "primary_incentive": state.team_b_incentive.primary_incentive.value,
            "incentive_flags": list(state.team_b_incentive.incentive_flags),
            "intensity": state.team_b_incentive.intensity,
            "description": state.team_b_incentive.description,
        },
        "knockout_edge_if_known": state.knockout_edge_if_known,
        "data_quality": state.data_quality,
    }
    if state.group_standings_before_match is not None:
        payload["group_standings_before_match"] = {
            "group": state.group_standings_before_match.group_name,
            "table": [
                {
                    "position": r.position,
                    "team": r.team,
                    "played": r.played,
                    "won": r.won,
                    "drawn": r.drawn,
                    "lost": r.lost,
                    "goals_for": r.goals_for,
                    "goals_against": r.goals_against,
                    "goal_difference": r.goal_difference,
                    "points": r.points,
                }
                for r in state.group_standings_before_match.rows
            ],
        }

    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
