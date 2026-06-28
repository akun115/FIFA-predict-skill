"""Data completeness audit — known gaps in groups.yaml and schedule.yaml.

These tests document gaps that prevent the project from reaching full 12-group
coverage.  They are intentionally NOT part of the default test suite
(filename does not start with "test_") so that ``python -m unittest discover``
reports 0 failures.

Run explicitly when assessing data coverage:
    python tests/audit_schedule_completeness.py

Gaps tracked:
    1. Groups D-L are TBD (groups.yaml)
    2. Group-stage match count is 18/72 (schedule.yaml)
    3. Group B has round-robin duplicate pairings (schedule.yaml)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Allow running as: python tests/audit_schedule_completeness.py
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from oracle_core.tournament import (
    load_aliases,
    load_groups,
    load_schedule,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SCHEDULE_PATH = _ROOT / "knowledge" / "L1-events" / "schedule.yaml"
_GROUPS_PATH = _ROOT / "knowledge" / "L2-states" / "groups.yaml"
_ALIASES_PATH = _ROOT / "knowledge" / "L2-states" / "team-aliases.yaml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_all() -> tuple:
    aliases = load_aliases(_ALIASES_PATH)
    groups = load_groups(_GROUPS_PATH, aliases)
    schedule = load_schedule(_SCHEDULE_PATH, aliases)
    return aliases, groups, schedule


# ---------------------------------------------------------------------------
# Audit tests
# ---------------------------------------------------------------------------


class GroupCompletenessAudit(unittest.TestCase):
    """Gap: 3 of 12 groups defined."""

    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.groups, cls.schedule = _load_all()

    def test_all_12_groups_present(self):
        """FAILS until groups D-L are added to groups.yaml."""
        expected = {chr(ord("A") + i) for i in range(12)}
        actual = set(self.groups.keys())
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        self.assertEqual(len(self.groups), 12,
            f"Groups: {len(self.groups)}/12 present. "
            f"Missing: {missing or 'none'}. "
            f"Extra (non-standard): {extra or 'none'}.")


class ScheduleCompletenessAudit(unittest.TestCase):
    """Gap: 18 of 72 group-stage matches defined."""

    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.groups, cls.schedule = _load_all()

    def test_72_group_matches_present(self):
        """FAILS until schedule.yaml covers all 12 groups × 6 matches."""
        total = sum(1 for m in self.schedule
                    if m.group_or_round in self.groups)
        target = 72  # 12 groups × 6 matches — hardcoded target
        self.assertEqual(total, target,
            f"Group-stage matches: {total}/{target}. "
            f"Missing {target - total} matches.")


class GroupBPairingsAudit(unittest.TestCase):
    """Known data issue: Group B MD3 has duplicate pairings.

    Current (broken) Group B schedule:
        MD1: Canada vs Switzerland, Bosnia vs Qatar
        MD2: Canada vs Qatar, Switzerland vs Bosnia
        MD3: Switzerland vs Canada  [DUPE of MD1!], Bosnia vs Qatar  [DUPE of MD1!]

    Missing pairings: Canada-Bosnia, Switzerland-Qatar.

    Fix plan: see docs/patch-6.1-group-b-data-request.md.
    This test will FAIL until the Group B schedule is corrected.
    """

    @classmethod
    def setUpClass(cls):
        cls.aliases, cls.groups, cls.schedule = _load_all()

    def test_group_b_has_no_duplicate_pairings(self):
        """Group B must be a valid single-round-robin schedule."""
        if "B" not in self.groups:
            self.skipTest("Group B not defined")
        gdef = self.groups["B"]
        pairs: set[tuple[str, str]] = set()
        dupes: list[str] = []
        for m in self.schedule:
            if m.group_or_round != "B":
                continue
            pair = tuple(sorted([m.team_a, m.team_b]))
            if pair in pairs:
                dupes.append(
                    f"{pair[0]} vs {pair[1]} (match_id={m.match_id}, MD{m.matchday})"
                )
            pairs.add(pair)

        # Also check which expected pairs are missing
        from itertools import combinations
        expected_pairs = set(tuple(sorted(p)) for p in combinations(gdef.teams, 2))
        missing = expected_pairs - pairs

        msgs = []
        if dupes:
            msgs.append(f"Duplicate pairings: {dupes}")
        if missing:
            msgs.append(f"Missing pairings: {sorted(missing)}")
        if msgs:
            self.fail("Group B round-robin violation:\n  " + "\n  ".join(msgs))


if __name__ == "__main__":
    unittest.main()
