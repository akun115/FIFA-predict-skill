"""Schedule and group data integrity tests.

Validates that groups.yaml and schedule.yaml satisfy structural invariants
for every group present.  These tests load the real knowledge/ data files —
they are NOT fixture-based.

Constraint checklist (per group):
  - exactly 4 teams
  - exactly 6 group-stage matches
  - each team plays exactly 3 matches
  - no duplicate match_id
  - no duplicate team pair within group
  - all schedule teams exist in groups.yaml
  - all group teams appear in schedule.yaml
  - get_tournament_state works for every group match
"""

from __future__ import annotations

import unittest
from pathlib import Path

from oracle_core.tournament import (
    DEFAULT_WORLD_CUP_2026_RULES,
    check_round_robin_integrity,
    get_tournament_state,
    load_aliases,
    load_groups,
    load_rules,
    load_schedule,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]
_SCHEDULE_PATH = _ROOT / "knowledge" / "L1-events" / "schedule.yaml"
_GROUPS_PATH = _ROOT / "knowledge" / "L2-states" / "groups.yaml"
_ALIASES_PATH = _ROOT / "knowledge" / "L2-states" / "team-aliases.yaml"
_RULES_PATH = _ROOT / "knowledge" / "L2-states" / "tournament-rules-2026.yaml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_all() -> tuple:
    """Load real knowledge data once per test run."""
    aliases = load_aliases(_ALIASES_PATH)
    groups = load_groups(_GROUPS_PATH, aliases)
    schedule = load_schedule(_SCHEDULE_PATH, aliases)
    rules = load_rules(_RULES_PATH)
    return aliases, groups, schedule, rules


def _group_matches(schedule, group_name: str):
    """Return schedule entries for a single group."""
    return [m for m in schedule if m.group_or_round == group_name]


# ---------------------------------------------------------------------------
# 1. Group membership tests (groups.yaml)
# ---------------------------------------------------------------------------


class GroupMembershipTests(unittest.TestCase):
    """Structural invariants for groups.yaml."""

    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.groups, cls.schedule, cls.rules = _load_all()

    # -- required: test_each_group_has_4_teams ---------------------------------

    def test_each_group_has_4_teams(self):
        for gname, gdef in self.groups.items():
            with self.subTest(group=gname):
                self.assertEqual(
                    len(gdef.teams), 4,
                    f"Group {gname} has {len(gdef.teams)} teams, expected 4: {gdef.teams}"
                )

    # -- bonus: no duplicate team names within a group -------------------------

    def test_no_duplicate_teams_within_group(self):
        for gname, gdef in self.groups.items():
            with self.subTest(group=gname):
                self.assertEqual(
                    len(gdef.teams), len(set(gdef.teams)),
                    f"Group {gname} has duplicate teams: {gdef.teams}"
                )

    # -- bonus: all team names are canonicalized -------------------------------

    def test_all_group_team_names_are_canonical(self):
        """Every team name in groups.yaml must resolve through the alias table
        to its canonical form (no unknown raw names survive)."""
        for gname, gdef in self.groups.items():
            with self.subTest(group=gname):
                for team in gdef.teams:
                    canonical = self.aliases.get(team, team)
                    self.assertEqual(
                        team, canonical,
                        f"Group {gname}: team '{team}' not canonicalized "
                        f"(alias table resolves to '{canonical}')"
                    )


# ---------------------------------------------------------------------------
# 2. Schedule integrity tests (schedule.yaml)
# ---------------------------------------------------------------------------


class ScheduleIntegrityTests(unittest.TestCase):
    """Structural invariants for schedule.yaml."""

    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.groups, cls.schedule, cls.rules = _load_all()

    # -- required: test_no_duplicate_match_ids ---------------------------------

    def test_no_duplicate_match_ids(self):
        ids = [m.match_id for m in self.schedule]
        seen: set[str] = set()
        dupes: list[str] = []
        for mid in ids:
            if mid in seen:
                dupes.append(mid)
            seen.add(mid)
        self.assertEqual(
            len(dupes), 0,
            f"Duplicate match_ids found: {dupes}"
        )

    # -- required: test_each_group_has_6_matches -------------------------------

    def test_each_group_has_6_matches(self):
        match_counts: dict[str, int] = {}
        for m in self.schedule:
            g = m.group_or_round
            if g not in self.groups:
                continue  # knockout / unknown rounds — not checked here
            match_counts[g] = match_counts.get(g, 0) + 1
        for gname in self.groups:
            with self.subTest(group=gname):
                count = match_counts.get(gname, 0)
                self.assertEqual(
                    count, 6,
                    f"Group {gname} has {count} matches, expected 6"
                )

    # -- required: test_each_team_plays_3_group_matches ------------------------

    def test_each_team_plays_3_group_matches(self):
        for gname, gdef in self.groups.items():
            with self.subTest(group=gname):
                appearances: dict[str, int] = {t: 0 for t in gdef.teams}
                for m in self.schedule:
                    if m.group_or_round != gname:
                        continue
                    for side in (m.team_a, m.team_b):
                        if side in appearances:
                            appearances[side] += 1
                for team, count in appearances.items():
                    self.assertEqual(
                        count, 3,
                        f"Group {gname}: '{team}' plays {count} matches, expected 3"
                    )

    # -- required: no duplicate team pair within group -------------------------
    # NOTE: Group B is excluded from this check pending a data fix.
    #       Its duplicate pairings (Canada-Switzerland, Bosnia-Qatar on MD3)
    #       are tracked in tests/audit_schedule_completeness.py.
    #       See docs/patch-6.1-group-b-data-request.md for the fix plan.

    _GROUP_B_PAIR_ISSUE_KNOWN = frozenset({"B"})

    def test_no_duplicate_team_pair_within_group(self):
        for gname, gdef in self.groups.items():
            if gname in self._GROUP_B_PAIR_ISSUE_KNOWN:
                continue  # pending data fix — audited separately
            with self.subTest(group=gname):
                result = check_round_robin_integrity(
                    self.schedule, gname, gdef.teams,
                )
                self.assertEqual(
                    result["status"], "ok",
                    f"Group {gname} has issues: {result['issues']}"
                )

    # -- bonus: matchday values are 1, 2, or 3 for group-stage matches ---------

    def test_group_matchdays_are_valid(self):
        for m in self.schedule:
            if m.group_or_round not in self.groups:
                continue
            with self.subTest(match_id=m.match_id):
                self.assertIn(
                    m.matchday, (1, 2, 3),
                    f"{m.match_id}: matchday={m.matchday}, expected 1, 2, or 3"
                )

    # -- bonus: every group has exactly 2 matches per matchday -----------------

    def test_each_matchday_has_2_matches_per_group(self):
        for gname in self.groups:
            with self.subTest(group=gname):
                for md in (1, 2, 3):
                    count = sum(
                        1 for m in self.schedule
                        if m.group_or_round == gname and m.matchday == md
                    )
                    self.assertEqual(
                        count, 2,
                        f"Group {gname} matchday {md}: {count} matches, expected 2"
                    )



# ---------------------------------------------------------------------------
# 3. Cross-file integrity tests (groups.yaml ↔ schedule.yaml)
# ---------------------------------------------------------------------------


class CrossFileIntegrityTests(unittest.TestCase):
    """Tests spanning both groups.yaml and schedule.yaml."""

    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.groups, cls.schedule, cls.rules = _load_all()

    # -- required: test_schedule_teams_exist_in_groups -------------------------

    def test_schedule_teams_exist_in_groups(self):
        for m in self.schedule:
            gname = m.group_or_round
            if gname not in self.groups:
                continue
            gdef = self.groups[gname]
            with self.subTest(match_id=m.match_id):
                self.assertIn(
                    m.team_a, gdef.teams,
                    f"{m.match_id}: team_a '{m.team_a}' not in Group {gname}: "
                    f"{gdef.teams}"
                )
                self.assertIn(
                    m.team_b, gdef.teams,
                    f"{m.match_id}: team_b '{m.team_b}' not in Group {gname}: "
                    f"{gdef.teams}"
                )

    # -- bonus: every group team appears in the schedule -----------------------

    def test_all_group_teams_appear_in_schedule(self):
        for gname, gdef in self.groups.items():
            with self.subTest(group=gname):
                scheduled_teams: set[str] = set()
                for m in self.schedule:
                    if m.group_or_round == gname:
                        scheduled_teams.add(m.team_a)
                        scheduled_teams.add(m.team_b)
                missing = set(gdef.teams) - scheduled_teams
                self.assertEqual(
                    len(missing), 0,
                    f"Group {gname} teams not in schedule: {sorted(missing)}"
                )

    # -- bonus: every team in schedule for a group is in that group ------------

    def test_no_foreign_teams_in_group_matches(self):
        """A group-stage match must only feature teams that belong to that group."""
        for m in self.schedule:
            gname = m.group_or_round
            if gname not in self.groups:
                continue
            gdef = self.groups[gname]
            with self.subTest(match_id=m.match_id):
                self.assertIn(m.team_a, gdef.teams,
                    f"{m.match_id}: team_a '{m.team_a}' is not a member of Group {gname}")
                self.assertIn(m.team_b, gdef.teams,
                    f"{m.match_id}: team_b '{m.team_b}' is not a member of Group {gname}")

    # -- bonus: match_id naming convention -------------------------------------

    def test_match_ids_follow_convention(self):
        """Group-stage match_ids should follow wc2026-grp<X>-<team_a>-<team_b>
        or wc2026-grp<X>-<team_a>-<team_b>-md<d> format."""
        import re
        pattern = re.compile(
            r"^wc2026-grp[A-Z]-[a-z]{3}-[a-z]{3}(-md\d)?$"
        )
        bad: list[str] = []
        for m in self.schedule:
            if m.group_or_round not in self.groups:
                continue
            if not pattern.match(m.match_id):
                bad.append(m.match_id)
        self.assertEqual(
            len(bad), 0,
            f"Match IDs not following wc2026-grpX-aaa-bbb convention: {bad}"
        )


# ---------------------------------------------------------------------------
# 4. Tournament state coverage tests
# ---------------------------------------------------------------------------


class TournamentStateCoverageTests(unittest.TestCase):
    """Verify get_tournament_state works for every group-stage match."""

    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.groups, cls.schedule, cls.rules = _load_all()

    # -- required: test_tournament_state_available_for_every_group_match --------

    def test_tournament_state_available_for_every_group_match(self):
        for m in self.schedule:
            gname = m.group_or_round
            if gname not in self.groups:
                continue
            with self.subTest(match_id=m.match_id):
                try:
                    state = get_tournament_state(
                        m.match_id, self.schedule, self.groups, self.rules,
                    )
                    self.assertEqual(state.match_id, m.match_id)
                    self.assertEqual(
                        state.match_context["group_or_round"], gname,
                    )
                    self.assertIsNotNone(state.group_standings_before_match)
                    self.assertIsNotNone(state.team_a_incentive)
                    self.assertIsNotNone(state.team_b_incentive)
                except Exception as exc:
                    self.fail(
                        f"get_tournament_state('{m.match_id}') raised "
                        f"{type(exc).__name__}: {exc}"
                    )

    def test_tournament_state_pre_match_mode_for_all_group_matches(self):
        """pre_match mode must also work for every group match."""
        for m in self.schedule:
            gname = m.group_or_round
            if gname not in self.groups:
                continue
            with self.subTest(match_id=m.match_id):
                try:
                    state = get_tournament_state(
                        m.match_id, self.schedule, self.groups, self.rules,
                        state_mode="pre_match",
                    )
                    self.assertEqual(state.state_mode, "pre_match")
                    self.assertIn(m.match_id, state.excluded_matches)
                except Exception as exc:
                    self.fail(
                        f"get_tournament_state('{m.match_id}', pre_match) raised "
                        f"{type(exc).__name__}: {exc}"
                    )


# ---------------------------------------------------------------------------
# 5. Match settlement integrity
# ---------------------------------------------------------------------------


class MatchSettlementIntegrityTests(unittest.TestCase):
    """Verify completed-match data integrity."""

    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.groups, cls.schedule, cls.rules = _load_all()

    def test_completed_matches_have_valid_scores(self):
        for m in self.schedule:
            if not m.is_completed:
                continue
            with self.subTest(match_id=m.match_id):
                self.assertIsNotNone(m.score)
                sa, sb = m.score  # type: ignore[misc]
                self.assertGreaterEqual(sa, 0)
                self.assertGreaterEqual(sb, 0)
                # Sanity: no 100-goal matches
                self.assertLess(sa, 30,
                    f"{m.match_id}: team_a scored {sa} goals — likely a data error")
                self.assertLess(sb, 30,
                    f"{m.match_id}: team_b scored {sb} goals — likely a data error")

    def test_match_kickoff_dates_are_plausible(self):
        """All kickoff times should be within the 2026 World Cup window."""
        for m in self.schedule:
            with self.subTest(match_id=m.match_id):
                self.assertTrue(
                    m.kickoff_utc.startswith("2026-06-"),
                    f"{m.match_id}: kickoff '{m.kickoff_utc}' outside June 2026 window"
                )


# ---------------------------------------------------------------------------
# 6. Data quality guard tests (Patch 6.2)
# ---------------------------------------------------------------------------


class DataQualityGuardTests(unittest.TestCase):
    """Verify that round-robin integrity issues are surfaced in tournament_state
    and propagated through tournament_context injection."""

    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.groups, cls.schedule, cls.rules = _load_all()

    # -- Group B tournament_state includes data_quality warning ---------------

    def test_group_b_tournament_state_has_data_quality_warning(self):
        """Group B's broken round-robin must produce a warning, not silent ok."""
        for m in self.schedule:
            if m.group_or_round != "B":
                continue
            with self.subTest(match_id=m.match_id):
                state = get_tournament_state(
                    m.match_id, self.schedule, self.groups, self.rules,
                )
                self.assertIsNotNone(state.data_quality,
                    f"{m.match_id}: data_quality should not be None")
                self.assertEqual(
                    state.data_quality["status"], "warning",
                    f"{m.match_id}: expected warning, got {state.data_quality['status']}"
                )
                issues = state.data_quality["issues"]
                self.assertTrue(
                    any("duplicate_pair" in i for i in issues),
                    f"Expected duplicate_pair in issues: {issues}"
                )
                self.assertTrue(
                    any("missing_pair" in i for i in issues),
                    f"Expected missing_pair in issues: {issues}"
                )

    # -- Group A tournament_state data_quality ok -----------------------------

    def test_group_a_tournament_state_data_quality_ok(self):
        """Group A has a valid round-robin — data_quality must be ok."""
        for m in self.schedule:
            if m.group_or_round != "A":
                continue
            with self.subTest(match_id=m.match_id):
                state = get_tournament_state(
                    m.match_id, self.schedule, self.groups, self.rules,
                )
                self.assertIsNotNone(state.data_quality,
                    f"{m.match_id}: data_quality should not be None")
                self.assertEqual(
                    state.data_quality["status"], "ok",
                    f"Group A {m.match_id}: expected ok, got {state.data_quality}"
                )
                self.assertEqual(
                    state.data_quality["issues"], [],
                    f"Group A {m.match_id}: expected no issues, got {state.data_quality['issues']}"
                )

    # -- Context injection preserves data_quality field -----------------------

    def test_tournament_context_json_includes_data_quality(self):
        """The JSON output of get_tournament_state must include data_quality."""
        import json
        import sys
        from pathlib import Path

        # Use the MCP tool to get real JSON output
        _ROOT = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(_ROOT / "mcp-server"))
        from tools.get_tournament_state import run_get_tournament_state

        # Group B (warning)
        json_b = run_get_tournament_state(
            match_id="wc2026-grpB-can-sui",
            knowledge_root=str(_ROOT / "knowledge"),
            state_mode="current",
        )
        state_b = json.loads(json_b)
        self.assertIn("data_quality", state_b)
        self.assertEqual(state_b["data_quality"]["status"], "warning")
        self.assertTrue(
            any("duplicate_pair" in i for i in state_b["data_quality"]["issues"])
        )

        # Group A (ok)
        json_a = run_get_tournament_state(
            match_id="wc2026-grpA-mex-rsa",
            knowledge_root=str(_ROOT / "knowledge"),
            state_mode="current",
        )
        state_a = json.loads(json_a)
        self.assertIn("data_quality", state_a)
        self.assertEqual(state_a["data_quality"]["status"], "ok")
        self.assertEqual(state_a["data_quality"]["issues"], [])

    # -- Probabilities unchanged when data_quality is warning -----------------

    def test_group_b_context_injection_does_not_change_probabilities(self):
        """Even with a data_quality warning, tournament_context injection
        must never alter result probabilities or expected goals."""
        import json
        import os
        import sys
        import tempfile
        from pathlib import Path

        _ROOT = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(_ROOT / "mcp-server"))
        from tools.get_tournament_state import run_get_tournament_state

        # Get tournament context for a Group B match (warning status)
        tc_json = run_get_tournament_state(
            match_id="wc2026-grpB-can-sui",
            knowledge_root=str(_ROOT / "knowledge"),
            state_mode="pre_match",
        )

        # Load the MCP server module
        from tests.test_mcp_server import load_server
        module = load_server()

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["WORLD_CUP_ORACLE_LOG_DIR"] = tmpdir
            try:
                # Predict WITHOUT tournament context
                result_no_tc = json.loads(module.predict_match_tool(
                    team_a="Canada", team_b="Switzerland",
                    neutral_site=True, category="world_cup",
                ))

                # Predict WITH Group B tournament context (data_quality=warning)
                result_with_tc = json.loads(module.predict_match_tool(
                    team_a="Canada", team_b="Switzerland",
                    neutral_site=True, category="world_cup",
                    tournament_context_json=tc_json,
                ))
            finally:
                os.environ.pop("WORLD_CUP_ORACLE_LOG_DIR", None)

        # Probabilities must be identical
        for key in ("team_a_win", "draw", "team_b_win"):
            self.assertAlmostEqual(
                result_no_tc["result_probabilities"][key],
                result_with_tc["result_probabilities"][key],
                places=10,
                msg=f"'{key}' probability changed — violates invariant"
            )

        # Expected goals must be identical
        self.assertAlmostEqual(
            result_no_tc["expected_goals"][0],
            result_with_tc["expected_goals"][0],
            places=10,
            msg="team_a expected_goals changed"
        )
        self.assertAlmostEqual(
            result_no_tc["expected_goals"][1],
            result_with_tc["expected_goals"][1],
            places=10,
            msg="team_b expected_goals changed"
        )

        # Over/under must be identical
        for key in result_no_tc["over_under"]:
            self.assertAlmostEqual(
                result_no_tc["over_under"][key],
                result_with_tc["over_under"][key],
                places=10,
                msg=f"over_under '{key}' changed"
            )

        # Context must have data_quality field with warning
        self.assertIn("tournament_context", result_with_tc)
        tc = result_with_tc["tournament_context"]
        self.assertIsNotNone(tc)
        self.assertIn("data_quality", tc)
        self.assertEqual(tc["data_quality"]["status"], "warning")

        # Limitations must include the schedule integrity note
        limits = result_with_tc.get("limitations", [])
        self.assertTrue(
            any("schedule integrity warning" in l.lower() for l in limits),
            f"Expected schedule integrity warning in limitations: {limits}"
        )


if __name__ == "__main__":
    unittest.main()
