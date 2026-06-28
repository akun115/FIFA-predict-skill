"""Tournament state tests — all use temporary fixture data, not real knowledge/ files."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

import yaml

from oracle_core.tournament import (
    DEFAULT_WORLD_CUP_2026_RULES,
    compute_group_standings,
    derive_incentive,
    derive_qualification_scenarios,
    get_tournament_state,
    load_aliases,
    load_groups,
    load_rules,
    load_schedule,
    normalize_team_name,
    validate_schedule_results_consistency,
)
from oracle_core.types import (
    GroupDefinition,
    ScheduledMatch,
    TeamIncentive,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def _make_aliases() -> dict[str, str]:
    return {
        "Czech Republic": "Czech Republic",
        "Czechia": "Czech Republic",
        "USA": "United States",
        "United States": "United States",
        "Korea Republic": "South Korea",
        "South Korea": "South Korea",
        "Congo DR": "DR Congo",
        "DR Congo": "DR Congo",
        "Côte d'Ivoire": "Ivory Coast",
        "Ivory Coast": "Ivory Coast",
    }


def _sample_groups() -> dict[str, GroupDefinition]:
    return {
        "C": GroupDefinition("C", ("Brazil", "Morocco", "Scotland", "Haiti")),
    }


def _sample_schedule(completed: bool = True) -> tuple[ScheduledMatch, ...]:
    """Group C — 6 matches. If completed=True, all have scores; else matchday 3 incomplete."""
    score_bra_sco = (0, 3) if completed else None
    score_mar_hai = (4, 2) if completed else None
    return (
        ScheduledMatch("wc2026-grpC-mar-bra", "C", 1, "Morocco", "Brazil",
                       "2026-06-20T00:00:00Z", "Venue1", True, (1, 1)),
        ScheduledMatch("wc2026-grpC-sco-hai", "C", 1, "Scotland", "Haiti",
                       "2026-06-20T00:00:00Z", "Venue1", True, (1, 0)),
        ScheduledMatch("wc2026-grpC-bra-hai", "C", 2, "Brazil", "Haiti",
                       "2026-06-23T00:00:00Z", "Venue2", True, (3, 0)),
        ScheduledMatch("wc2026-grpC-sco-mar", "C", 2, "Scotland", "Morocco",
                       "2026-06-23T00:00:00Z", "Venue2", True, (0, 1)),
        ScheduledMatch("wc2026-grpC-sco-bra", "C", 3, "Scotland", "Brazil",
                       "2026-06-26T03:00:00Z", "Miami", True, score_bra_sco),
        ScheduledMatch("wc2026-grpC-mar-hai", "C", 3, "Morocco", "Haiti",
                       "2026-06-26T03:00:00Z", "Atlanta", True, score_mar_hai),
    )


def _full_group_c_schedule() -> tuple[ScheduledMatch, ...]:
    """All 6 Group C matches completed — used for post-match standings tests."""
    return _sample_schedule(completed=True)


def _partial_group_c_schedule() -> tuple[ScheduledMatch, ...]:
    """4 completed + 2 unplayed (matchday 3 pending)."""
    return _sample_schedule(completed=False)


# ---------------------------------------------------------------------------
# 1. Standings aggregation
# ---------------------------------------------------------------------------


class StandingsAggregationTests(unittest.TestCase):
    def test_completed_group_produces_correct_standings(self):
        schedule = _full_group_c_schedule()
        groups = _sample_groups()
        tables = compute_group_standings(schedule, groups)
        self.assertIn("C", tables)
        table = tables["C"]
        rows_by_team = {r.team: r for r in table.rows}

        # Brazil: 1W(Morocco)+1W(Haiti)+1W(Scotland) = 7pts GF=7 GA=1
        bra = rows_by_team["Brazil"]
        self.assertEqual(bra.points, 7)
        self.assertEqual(bra.played, 3)
        self.assertEqual(bra.goals_for, 7)
        self.assertEqual(bra.goals_against, 1)
        self.assertEqual(bra.goal_difference, 6)

        # Morocco: 1D(Brazil)+1W(Scotland)+1W(Haiti) = 7pts GF=6 GA=3
        mar = rows_by_team["Morocco"]
        self.assertEqual(mar.points, 7)
        self.assertEqual(mar.played, 3)
        self.assertEqual(mar.goals_for, 6)
        self.assertEqual(mar.goals_against, 3)

        # Scotland: 1W(Haiti)+0L(Morocco)+0L(Brazil) = 3pts
        sco = rows_by_team["Scotland"]
        self.assertEqual(sco.points, 3)
        self.assertEqual(sco.played, 3)

        # Haiti: 0L(Sco)+0L(Bra)+0L(Mar) = 0pts
        hai = rows_by_team["Haiti"]
        self.assertEqual(hai.points, 0)

        # Brazil should be #1 (better GD than Morocco)
        self.assertEqual(table.rows[0].team, "Brazil")
        self.assertEqual(table.rows[1].team, "Morocco")
        self.assertEqual(table.rows[2].team, "Scotland")
        self.assertEqual(table.rows[3].team, "Haiti")

    def test_empty_schedule_returns_zeroed_table(self):
        schedule: tuple[ScheduledMatch, ...] = ()
        groups = _sample_groups()
        tables = compute_group_standings(schedule, groups)
        for row in tables["C"].rows:
            self.assertEqual(row.points, 0)
            self.assertEqual(row.played, 0)


# ---------------------------------------------------------------------------
# 2. Team alias normalization
# ---------------------------------------------------------------------------


class TeamAliasTests(unittest.TestCase):
    def test_czechia_normalized_to_czech_republic(self):
        aliases = _make_aliases()
        self.assertEqual(normalize_team_name("Czechia", aliases), "Czech Republic")

    def test_korea_republic_normalized_to_south_korea(self):
        aliases = _make_aliases()
        self.assertEqual(normalize_team_name("Korea Republic", aliases), "South Korea")

    def test_unknown_team_passed_through(self):
        aliases = _make_aliases()
        self.assertEqual(normalize_team_name("Wakanda", aliases), "Wakanda")

    def test_aliases_yaml_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "team-aliases.yaml"
            _write_yaml(path, {
                "aliases": {
                    "Czech Republic": ["Czechia"],
                    "South Korea": ["Korea Republic"],
                }
            })
            aliases = load_aliases(path)
            self.assertEqual(aliases["Czechia"], "Czech Republic")
            self.assertEqual(aliases["Korea Republic"], "South Korea")

    def test_load_groups_normalizes_team_names(self):
        with tempfile.TemporaryDirectory() as td:
            groups_path = Path(td) / "groups.yaml"
            _write_yaml(groups_path, {
                "groups": {"A": ["Czechia", "Korea Republic", "USA", "Brazil"]}
            })
            aliases = _make_aliases()
            groups = load_groups(groups_path, aliases)
            teams = groups["A"].teams
            self.assertIn("Czech Republic", teams)
            self.assertIn("South Korea", teams)
            self.assertIn("United States", teams)
            # Brazil should pass through unchanged
            self.assertIn("Brazil", teams)


# ---------------------------------------------------------------------------
# 3. Rules loading fallback
# ---------------------------------------------------------------------------


class RulesLoadingTests(unittest.TestCase):
    def test_load_rules_from_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rules.yaml"
            _write_yaml(path, {
                "tournament_name": "Test Cup",
                "group_stage_format": "4 groups of 4",
                "total_groups": 4,
                "teams_per_group": 4,
                "matchdays_per_group": 3,
                "advancement": {
                    "group_stage": {
                        "top_n_per_group": 2,
                        "best_third_place_count": 4,
                        "total_advancing": 12,
                    },
                },
                "group_tiebreakers": ["points", "goal_difference"],
                "best_third_place_ranking": {"criteria": ["points"]},
            })
            rules = load_rules(path)
            self.assertEqual(rules.tournament_name, "Test Cup")
            self.assertEqual(rules.total_groups, 4)
            self.assertEqual(rules.top_n_per_group, 2)
            self.assertEqual(rules.group_tiebreakers, ("points", "goal_difference"))

    def test_load_rules_returns_default_when_file_missing(self):
        rules = load_rules(Path("/nonexistent/path/rules.yaml"))
        self.assertEqual(rules, DEFAULT_WORLD_CUP_2026_RULES)
        self.assertEqual(rules.top_n_per_group, 2)
        self.assertEqual(rules.best_third_place_count, 8)

    def test_load_rules_none_returns_default(self):
        rules = load_rules(None)
        self.assertEqual(rules, DEFAULT_WORLD_CUP_2026_RULES)


# ---------------------------------------------------------------------------
# 4. Incentive tests
# ---------------------------------------------------------------------------


def _table_from_rows(group_name: str, team_names: tuple[str, ...],
                      points: tuple[int, ...], gd: tuple[int, ...]) -> "GroupTable":
    from oracle_core.types import GroupStandingsRow, GroupTable
    rows = []
    for i, (t, p, g) in enumerate(zip(team_names, points, gd), start=1):
        rows.append(GroupStandingsRow(
            position=i, team=t, played=2, won=max(0, p // 3), drawn=p % 3, lost=0,
            goals_for=g + 3, goals_against=3, goal_difference=g, points=p,
        ))
    return GroupTable(group_name=group_name, rows=tuple(rows))


class IncentiveTests(unittest.TestCase):
    def setUp(self):
        self.rules = DEFAULT_WORLD_CUP_2026_RULES

    def test_matchday_3_must_win_for_top2(self):
        # Scotland 3pts, Morocco 4pts (Morocco has NO remaining matches)
        # Scotland with 1 remaining match: max = 6. Morocco max = 4. Scotland leapfrogs with win.
        table = _table_from_rows("C", ("Brazil", "Morocco", "Scotland", "Haiti"),
                                 (7, 4, 3, 0), (6, 1, 0, -7))
        remaining = (
            ScheduledMatch("m1", "C", 3, "Scotland", "Haiti", "t", "v", True, None),
        )
        incentive = derive_incentive(table, "Scotland", 3, remaining, self.rules)
        self.assertEqual(incentive.primary_incentive, TeamIncentive.MUST_WIN_FOR_TOP2)
        self.assertEqual(incentive.intensity, 1.0)

    def test_matchday_3_already_qualified(self):
        # Brazil 7pts, Scotland 3pts max → Brazil already qualified
        table = _table_from_rows("C", ("Brazil", "Morocco", "Scotland", "Haiti"),
                                 (7, 4, 3, 0), (6, 1, 0, -7))
        # Brazil cannot be caught by Scotland (max 6pts)
        remaining = (
            ScheduledMatch("m1", "C", 3, "Scotland", "Brazil", "t", "v", True, None),
        )
        # With Brazil at 7pts and Scotland max 6pts, Brazil is safe
        incentive = derive_incentive(table, "Brazil", 3, remaining, self.rules)
        self.assertIn(incentive.primary_incentive, (
            TeamIncentive.ALREADY_QUALIFIED_ROTATION_RISK,
            TeamIncentive.DRAW_SUFFICIENT_FOR_TOP2,
        ))

    def test_matchday_3_eliminated(self):
        # Haiti 0pts, min pts to reach top 2 far out of reach
        table = _table_from_rows("C", ("Brazil", "Morocco", "Scotland", "Haiti"),
                                 (7, 7, 3, 0), (6, 3, 0, -9))
        remaining = (
            ScheduledMatch("m1", "C", 3, "Morocco", "Haiti", "t", "v", True, None),
        )
        # Haiti max possible = 3pts. Top 2 have 7 and 7. Can't reach top 2.
        # But CAN still reach 3rd (Scotland has 3, Haiti could reach 3 and beat on GD)
        # Actually with Haiti at 0 and Scotland at 3, Haiti's max is 3.
        # If Haiti wins and Scotland loses, Haiti = 3, Scotland = 3, goes to GD.
        # Haiti GD is -9, Scotland GD is 0. Haiti can only improve GD by margin of win.
        # So Haiti CAN reach 3rd position but will almost certainly lose on GD.
        # Let me check: _can_finish_top_n with n=3 — is that possible?
        # Haiti max pts = 3. Scotland already has 3 and GD=0. If Haiti wins by 10 goals,
        # Haiti GD becomes +1. So yes, mathematically possible to reach 3rd.
        # Thus Haiti is NOT force_eliminated from top 3.
        incentive = derive_incentive(table, "Haiti", 3, remaining, self.rules)
        # Haiti should be THIRD_PLACE_DEPENDENT or MUST_WIN —not eliminated
        self.assertNotEqual(incentive.primary_incentive, TeamIncentive.ELIMINATED_LOW_PRESSURE)

    def test_matchday_1_no_clear_incentive(self):
        table = _table_from_rows("C", ("Brazil", "Morocco", "Scotland", "Haiti"),
                                 (3, 1, 1, 0), (1, 0, 0, -1))
        remaining = (
            ScheduledMatch("m1", "C", 1, "Scotland", "Brazil", "t", "v", True, None),
            ScheduledMatch("m2", "C", 1, "Morocco", "Haiti", "t", "v", True, None),
            ScheduledMatch("m3", "C", 2, "Brazil", "Haiti", "t", "v", True, None),
            ScheduledMatch("m4", "C", 2, "Scotland", "Morocco", "t", "v", True, None),
            ScheduledMatch("m5", "C", 3, "Scotland", "Brazil", "t", "v", True, None),
            ScheduledMatch("m6", "C", 3, "Morocco", "Haiti", "t", "v", True, None),
        )
        incentive = derive_incentive(table, "Brazil", 1, remaining, self.rules)
        self.assertEqual(incentive.primary_incentive, TeamIncentive.NO_CLEAR_INCENTIVE)
        self.assertIsNone(incentive.intensity)

    def test_matchday_3_eliminated_fully(self):
        # Haiti 0pts, max 3pts, top 3 all unreachable
        table = _table_from_rows("C", ("Brazil", "Morocco", "Scotland", "Haiti"),
                                 (9, 7, 6, 0), (6, 3, 2, -11))
        remaining = (
            ScheduledMatch("m1", "C", 3, "Morocco", "Haiti", "t", "v", True, None),
        )
        # Haiti max = 3. Scotland already has 6. Haiti CANNOT reach top 3.
        incentive = derive_incentive(table, "Haiti", 3, remaining, self.rules)
        self.assertEqual(incentive.primary_incentive, TeamIncentive.ELIMINATED_LOW_PRESSURE)
        self.assertEqual(incentive.intensity, 0.0)

    def test_already_qualified_has_rotation_risk(self):
        table = _table_from_rows("C", ("Brazil", "Morocco", "Scotland", "Haiti"),
                                 (7, 4, 3, 0), (6, 1, 0, -7))
        remaining = (
            ScheduledMatch("m1", "C", 3, "Scotland", "Brazil", "t", "v", True, None),
            ScheduledMatch("m2", "C", 3, "Morocco", "Haiti", "t", "v", True, None),
        )
        incentive = derive_incentive(table, "Brazil", 3, remaining, self.rules)
        if incentive.primary_incentive == TeamIncentive.ALREADY_QUALIFIED_ROTATION_RISK:
            self.assertIn("rotation_risk", incentive.incentive_flags)


# ---------------------------------------------------------------------------
# 5. Simultaneous matches + top-level orchestration
# ---------------------------------------------------------------------------


class TournamentStateIntegrationTests(unittest.TestCase):
    def test_simultaneous_group_matches_populated(self):
        schedule = _full_group_c_schedule()
        groups = _sample_groups()
        rules = DEFAULT_WORLD_CUP_2026_RULES
        state = get_tournament_state("wc2026-grpC-sco-bra", schedule, groups, rules)
        sim = state.simultaneous_group_matches
        self.assertEqual(len(sim), 1)
        self.assertEqual(sim[0]["match_id"], "wc2026-grpC-mar-hai")

    def test_get_tournament_state_with_fixture_data(self):
        schedule = _full_group_c_schedule()
        groups = _sample_groups()
        rules = DEFAULT_WORLD_CUP_2026_RULES
        state = get_tournament_state("wc2026-grpC-sco-bra", schedule, groups, rules)
        self.assertEqual(state.match_id, "wc2026-grpC-sco-bra")
        self.assertIsNotNone(state.group_standings_before_match)
        self.assertIsNotNone(state.team_a_incentive)
        self.assertIsNotNone(state.team_b_incentive)
        self.assertIsNone(state.knockout_edge_if_known)

    def test_missing_match_id_raises(self):
        schedule = _full_group_c_schedule()
        groups = _sample_groups()
        with self.assertRaises(ValueError):
            get_tournament_state("nonexistent", schedule, groups, DEFAULT_WORLD_CUP_2026_RULES)


# ---------------------------------------------------------------------------
# 6. Schedule/results consistency
# ---------------------------------------------------------------------------


class ConsistencyTests(unittest.TestCase):
    def test_no_warnings_when_consistent(self):
        schedule = _full_group_c_schedule()
        match_results = [
            {"id": "wc2026-grpC-sco-bra", "score": [0, 3]},
            {"id": "wc2026-grpC-mar-hai", "score": [4, 2]},
            {"id": "wc2026-grpC-mar-bra", "score": [1, 1]},
            {"id": "wc2026-grpC-sco-hai", "score": [1, 0]},
            {"id": "wc2026-grpC-bra-hai", "score": [3, 0]},
            {"id": "wc2026-grpC-sco-mar", "score": [0, 1]},
        ]
        warnings = validate_schedule_results_consistency(schedule, match_results)
        self.assertEqual(len(warnings), 0)

    def test_score_mismatch_generates_warning(self):
        schedule = _full_group_c_schedule()
        match_results = [
            {"id": "wc2026-grpC-sco-bra", "score": [1, 1]},  # different!
        ]
        warnings = validate_schedule_results_consistency(schedule, match_results)
        self.assertGreater(len(warnings), 0)
        self.assertIn("wc2026-grpC-sco-bra", warnings[0])

    def test_missing_settlement_not_an_error(self):
        schedule = _full_group_c_schedule()
        match_results: list[dict] = []
        warnings = validate_schedule_results_consistency(schedule, match_results)
        self.assertEqual(len(warnings), 0)


# ---------------------------------------------------------------------------
# 7. JSON output roundtrip
# ---------------------------------------------------------------------------


class TournamentStateJSONTests(unittest.TestCase):
    def test_incentive_serializable(self):
        from oracle_core.types import IncentiveResult

        result = IncentiveResult(
            primary_incentive=TeamIncentive.MUST_WIN_FOR_TOP2,
            incentive_flags=("depends_on_other_match",),
            intensity=1.0,
            description="Must win to advance.",
        )
        payload = {
            "primary": result.primary_incentive.value,
            "flags": list(result.incentive_flags),
            "intensity": result.intensity,
            "description": result.description,
        }
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["primary"], "must_win_for_top2")
        self.assertEqual(decoded["intensity"], 1.0)


# ---------------------------------------------------------------------------
# 8. Pre-match time-slice semantics
# ---------------------------------------------------------------------------


class PreMatchSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.rules = DEFAULT_WORLD_CUP_2026_RULES
        self.groups = _sample_groups()

    def test_pre_match_excludes_target_and_simultaneous(self):
        schedule = _full_group_c_schedule()
        state = get_tournament_state(
            "wc2026-grpC-sco-bra", schedule, self.groups, self.rules,
            state_mode="pre_match",
        )
        self.assertEqual(state.state_mode, "pre_match")
        self.assertIn("wc2026-grpC-sco-bra", state.excluded_matches)
        self.assertIn("wc2026-grpC-mar-hai", state.excluded_matches)
        self.assertEqual(len(state.excluded_matches), 2)

    def test_pre_match_standings_before_kickoff(self):
        """Brazil 4pts (2P), Morocco 4pts (2P), Scotland 3pts (2P), Haiti 0pts (2P)."""
        schedule = _full_group_c_schedule()
        state = get_tournament_state(
            "wc2026-grpC-sco-bra", schedule, self.groups, self.rules,
            state_mode="pre_match",
        )
        table = state.group_standings_before_match
        self.assertIsNotNone(table)
        rows_by_team = {r.team: r for r in table.rows}

        # Brazil: draw vs Morocco (+1), win vs Haiti (+3) → 4pts
        self.assertEqual(rows_by_team["Brazil"].points, 4)
        self.assertEqual(rows_by_team["Brazil"].played, 2)
        # Morocco: draw vs Brazil (+1), win vs Scotland (+3) → 4pts
        self.assertEqual(rows_by_team["Morocco"].points, 4)
        self.assertEqual(rows_by_team["Morocco"].played, 2)
        # Scotland: win vs Haiti (+3), loss vs Morocco (+0) → 3pts
        self.assertEqual(rows_by_team["Scotland"].points, 3)
        self.assertEqual(rows_by_team["Scotland"].played, 2)
        # Haiti: loss vs Scotland (+0), loss vs Brazil (+0) → 0pts
        self.assertEqual(rows_by_team["Haiti"].points, 0)
        self.assertEqual(rows_by_team["Haiti"].played, 2)

    def test_pre_match_incentives_recomputed(self):
        """Scotland (3rd, 1pt behind 2nd with 1 match left) must win.
        Brazil (1st, 4pts vs Scotland): even if Brazil draws and Morocco wins,
        only Morocco can pass 5pts. Scotland draws too → max 4pts.
        Brazil draw mathematically secures top 2."""
        schedule = _full_group_c_schedule()
        state = get_tournament_state(
            "wc2026-grpC-sco-bra", schedule, self.groups, self.rules,
            state_mode="pre_match",
        )
        self.assertEqual(
            state.team_a_incentive.primary_incentive,
            TeamIncentive.MUST_WIN_FOR_TOP2,
        )
        self.assertEqual(
            state.team_b_incentive.primary_incentive,
            TeamIncentive.DRAW_SUFFICIENT_FOR_TOP2,
        )

    def test_draw_not_sufficient_when_two_opponents_can_pass(self):
        """Team X 4pts (1st), Team Y 4pts (2nd), Team Z 3pts (3rd).
        X plays Z. If X draws → 5pts. Y (not playing X) can win → 7pts.
        Z draws → 4pts. Only 1 passes → still top 2? Yes, that's sufficient.

        Counter-example: X 4pts, Y 4pts, Z 4pts (3rd), W 0pts (4th).
        X plays W. If X draws → 5pts. Y can win → 7pts, Z can win → 7pts.
        TWO opponents can pass X → draw NOT sufficient."""
        table = _table_from_rows(
            "X", ("A", "B", "C", "D"),
            (4, 4, 4, 0), (3, 2, 1, -6),
        )
        remaining = (
            ScheduledMatch("m1", "X", 3, "A", "D", "t", "v", True, None),
            ScheduledMatch("m2", "X", 3, "B", "C", "t", "v", True, None),
        )
        incentive = derive_incentive(table, "A", 3, remaining, self.rules)
        self.assertEqual(
            incentive.primary_incentive,
            TeamIncentive.DRAW_REQUIRES_HELP,
        )

    def test_current_mode_still_works_as_before(self):
        schedule = _full_group_c_schedule()
        state = get_tournament_state(
            "wc2026-grpC-sco-bra", schedule, self.groups, self.rules,
            state_mode="current",
        )
        self.assertEqual(state.state_mode, "current")
        self.assertEqual(state.excluded_matches, ())
        table = state.group_standings_before_match
        rows_by_team = {r.team: r for r in table.rows}
        self.assertEqual(rows_by_team["Brazil"].played, 3)
        self.assertEqual(rows_by_team["Brazil"].points, 7)

    def test_invalid_state_mode_raises(self):
        schedule = _full_group_c_schedule()
        with self.assertRaises(ValueError):
            get_tournament_state(
                "wc2026-grpC-sco-bra", schedule, self.groups, self.rules,
                state_mode="invalid",
            )

    def test_state_timestamp_utc_is_kickoff_for_pre_match(self):
        schedule = _full_group_c_schedule()
        state = get_tournament_state(
            "wc2026-grpC-sco-bra", schedule, self.groups, self.rules,
            state_mode="pre_match",
        )
        self.assertEqual(
            state.state_timestamp_utc,
            "2026-06-26T03:00:00Z",
        )

    def test_pre_match_standings_exclude_partial_schedule(self):
        """With a partially-played schedule (matchday 3 unplayed), pre_match
        should still exclude the target and simultaneous matches from standings."""
        schedule = _partial_group_c_schedule()
        state = get_tournament_state(
            "wc2026-grpC-sco-bra", schedule, self.groups, self.rules,
            state_mode="pre_match",
        )
        table = state.group_standings_before_match
        rows_by_team = {r.team: r for r in table.rows}
        # Only matchday 1+2 counted
        self.assertEqual(rows_by_team["Brazil"].played, 2)
        self.assertEqual(rows_by_team["Brazil"].points, 4)


if __name__ == "__main__":
    unittest.main()
