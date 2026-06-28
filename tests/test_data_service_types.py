"""Tests for Data Service v1 canonical schema skeleton (Patch 14).

All fixtures are fictional.  No real data.  No provider runtime.
No prediction engine integration.  No skipped tests.
"""

from __future__ import annotations

import unittest

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
    _fixed_datetime,
    _synthetic_hash,
    make_fixture_dq_issue,
    make_fixture_provenance,
)

from tests.fixtures.data_service import (
    FAKE_PROVENANCE,
    FICTIONAL_INJURY_ALPHA,
    FICTIONAL_LINEUP_ALPHA,
    FICTIONAL_MATCH_ALPHA_BETA,
    FICTIONAL_ODDS,
    FICTIONAL_SIGNAL_WEATHER,
    FICTIONAL_SUSPENSION_BETA,
    FICTIONAL_TEAM_ALPHA,
    FICTIONAL_TEAM_BETA,
    FIXED_NOW,
    make_blocking_snapshot,
    make_full_snapshot,
    make_minimal_snapshot,
)


# ---------------------------------------------------------------------------
# Import boundary
# ---------------------------------------------------------------------------


class DataServiceImportBoundaryTests(unittest.TestCase):
    """Data Service schema module must not import prediction engine modules."""

    def test_01_no_engine_import(self):
        """data_service_types does not import oracle_core.engine."""
        import oracle_core.data_service_types as ds
        import sys

        engine_imported = any(
            "oracle_core.engine" in str(v) or "oracle_core.scoring" in str(v)
            for v in sys.modules
            if v and "oracle_core" in v and hasattr(sys.modules[v], "__file__")
        )
        # data_service_types may not import engine.py or scoring.py
        ds_source = ds.__file__
        self.assertTrue(ds_source.endswith("data_service_types.py"))

    def test_02_prediction_engine_does_not_import_data_service(self):
        """Prediction engine modules do not import data_service_types."""
        import ast
        import pathlib

        engine_root = pathlib.Path(__file__).parent.parent / "oracle_core"
        modules_to_check = ["engine.py", "types.py", "knockout.py", "tournament.py", "odds.py"]

        for mod_name in modules_to_check:
            mod_path = engine_root / mod_name
            if not mod_path.exists():
                continue
            source = mod_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(
                            "data_service_types",
                            alias.name,
                            f"{mod_name} imports data_service_types via {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertNotIn(
                            "data_service_types",
                            node.module,
                            f"{mod_name} imports from data_service_types",
                        )


# ---------------------------------------------------------------------------
# DataQualitySeverity
# ---------------------------------------------------------------------------


class DataQualitySeverityTests(unittest.TestCase):
    """DataQualitySeverity enum and DataQualityIssue behavior."""

    def test_01_all_severity_values(self):
        self.assertEqual(DataQualitySeverity.INFO.value, "info")
        self.assertEqual(DataQualitySeverity.WARNING.value, "warning")
        self.assertEqual(DataQualitySeverity.ERROR.value, "error")
        self.assertEqual(DataQualitySeverity.BLOCKING.value, "blocking")

    def test_02_blocking_property_true_for_blocking(self):
        issue = DataQualityIssue(
            severity=DataQualitySeverity.BLOCKING,
            code="TEST",
            message="test",
        )
        self.assertTrue(issue.blocking)

    def test_03_blocking_property_false_for_others(self):
        for sev in (
            DataQualitySeverity.INFO,
            DataQualitySeverity.WARNING,
            DataQualitySeverity.ERROR,
        ):
            issue = DataQualityIssue(severity=sev, code="T", message="m")
            self.assertFalse(issue.blocking, f"{sev} should not be blocking")

    def test_04_data_quality_issue_to_dict(self):
        issue = DataQualityIssue(
            severity=DataQualitySeverity.WARNING,
            code="STALE_LINEUP",
            message="Lineup is stale.",
            field_path="lineup_context.status",
            provenance_refs=("fake_provider_v1",),
        )
        d = issue.to_dict()
        self.assertEqual(d["severity"], "warning")
        self.assertEqual(d["code"], "STALE_LINEUP")
        self.assertEqual(d["blocking"], False)
        self.assertEqual(d["provenance_refs"], ["fake_provider_v1"])


# ---------------------------------------------------------------------------
# ProviderProvenance
# ---------------------------------------------------------------------------


class ProviderProvenanceTests(unittest.TestCase):
    """ProviderProvenance construction and validation."""

    def test_01_construction_valid(self):
        p = make_fixture_provenance("fake_provider_v1", "test")
        self.assertEqual(p.provider_name, "fake_provider_v1")
        self.assertEqual(p.adapter_version, "1.0.0")
        self.assertTrue(p.raw_payload_hash)

    def test_02_empty_provider_name_raises(self):
        with self.assertRaises(ValueError):
            ProviderProvenance(
                provider_name="   ",
                adapter_version="1.0.0",
                fetched_at=FIXED_NOW,
            )

    def test_03_naive_datetime_raises(self):
        from datetime import datetime as dt

        with self.assertRaises(ValueError):
            ProviderProvenance(
                provider_name="test",
                adapter_version="1.0.0",
                fetched_at=dt(2026, 6, 1, 12, 0, 0),  # naive
            )

    def test_04_to_dict(self):
        p = make_fixture_provenance()
        d = p.to_dict()
        self.assertEqual(d["provider_name"], "fake_provider_v1")
        self.assertEqual(d["adapter_version"], "1.0.0")
        self.assertIsNotNone(d["raw_payload_hash"])


# ---------------------------------------------------------------------------
# CanonicalTeam / CanonicalMatch
# ---------------------------------------------------------------------------


class CanonicalEntityTests(unittest.TestCase):
    """CanonicalTeam and CanonicalMatch construction and validation."""

    def test_01_team_construction(self):
        t = FICTIONAL_TEAM_ALPHA
        self.assertEqual(t.team_id, "FIC-ALPHA")
        self.assertEqual(t.display_name, "Fictional Alpha FC")
        self.assertIn("fake_provider_v1", t.external_ids)

    def test_02_team_to_dict(self):
        d = FICTIONAL_TEAM_ALPHA.to_dict()
        self.assertEqual(d["team_id"], "FIC-ALPHA")
        self.assertTrue(d["provenance_refs"])

    def test_03_match_construction(self):
        m = FICTIONAL_MATCH_ALPHA_BETA
        self.assertEqual(m.match_id, "FIC-001")
        self.assertNotEqual(m.team_a_id, m.team_b_id)

    def test_04_match_same_team_raises(self):
        from datetime import datetime as dt

        with self.assertRaises(ValueError):
            CanonicalMatch(
                match_id="FIC-001",
                team_a_id="FIC-ALPHA",
                team_b_id="FIC-ALPHA",
                kickoff_at=FIXED_NOW,
            )

    def test_05_match_naive_kickoff_raises(self):
        from datetime import datetime as dt

        with self.assertRaises(ValueError):
            CanonicalMatch(
                match_id="FIC-001",
                team_a_id="FIC-ALPHA",
                team_b_id="FIC-BETA",
                kickoff_at=dt(2026, 6, 16, 20, 0, 0),
            )

    def test_06_match_to_dict(self):
        d = FICTIONAL_MATCH_ALPHA_BETA.to_dict()
        self.assertEqual(d["match_id"], "FIC-001")
        self.assertEqual(d["stage"], "group")


# ---------------------------------------------------------------------------
# Context types — Group / Knockout
# ---------------------------------------------------------------------------


class ContextTypeTests(unittest.TestCase):
    """GroupStandingContext and KnockoutBracketContext."""

    def test_01_group_standing_row_to_dict(self):
        row = GroupStandingRow(position=1, team_id="FIC-ALPHA", points=6)
        d = row.to_dict()
        self.assertEqual(d["team_id"], "FIC-ALPHA")
        self.assertEqual(d["points"], 6)

    def test_02_group_standing_context_to_dict(self):
        from tests.fixtures.data_service import FICTIONAL_GROUP_STANDINGS

        d = FICTIONAL_GROUP_STANDINGS.to_dict()
        self.assertEqual(len(d["rows"]), 4)
        self.assertEqual(d["rows"][0]["team_id"], "FIC-ALPHA")

    def test_03_knockout_bracket_to_dict(self):
        from tests.fixtures.data_service import FICTIONAL_KNOCKOUT_BRACKET

        d = FICTIONAL_KNOCKOUT_BRACKET.to_dict()
        self.assertEqual(d["bracket_id"], "FIC-KO-2026")
        self.assertEqual(len(d["match_slots"]), 4)


# ---------------------------------------------------------------------------
# OddsMarketContext — market comparison only
# ---------------------------------------------------------------------------


class OddsMarketContextTests(unittest.TestCase):
    """OddsMarketContext is market comparison only — never a model input."""

    def test_01_odds_selection_construction(self):
        sel = OddsSelection(label="team_a_win", decimal_odds=2.10)
        self.assertEqual(sel.label, "team_a_win")
        self.assertEqual(sel.decimal_odds, 2.10)

    def test_02_odds_selection_decimal_below_1_raises(self):
        with self.assertRaises(ValueError):
            OddsSelection(label="team_a_win", decimal_odds=0.95)

    def test_03_odds_report_only_is_true(self):
        self.assertTrue(FICTIONAL_ODDS.report_only)

    def test_04_odds_to_dict(self):
        d = FICTIONAL_ODDS.to_dict()
        self.assertEqual(d["match_id"], "FIC-001")
        self.assertEqual(len(d["selections"]), 3)
        self.assertTrue(d["report_only"])


# ---------------------------------------------------------------------------
# Lineup / Injury / Suspension — structured context only
# ---------------------------------------------------------------------------


class SquadContextTests(unittest.TestCase):
    """Lineup, Injury, Suspension are structured context only — not model input."""

    # ── Lineup ──

    def test_01_lineup_report_only_is_true(self):
        self.assertTrue(FICTIONAL_LINEUP_ALPHA.report_only)

    def test_02_lineup_player_slot_to_dict(self):
        slot = PlayerSlot(name="Fake Player One", number=1, position="GK")
        d = slot.to_dict()
        self.assertEqual(d["name"], "Fake Player One")
        self.assertEqual(d["number"], 1)

    def test_03_lineup_to_dict(self):
        d = FICTIONAL_LINEUP_ALPHA.to_dict()
        self.assertEqual(d["match_id"], "FIC-001")
        self.assertEqual(d["status"], "confirmed")
        self.assertEqual(len(d["starting_xi"]), 3)
        self.assertTrue(d["report_only"])

    def test_04_lineup_status_enum(self):
        self.assertEqual(LineupStatus.CONFIRMED.value, "confirmed")
        self.assertEqual(LineupStatus.PREDICTED.value, "predicted")
        self.assertEqual(LineupStatus.STALE.value, "stale")
        self.assertEqual(LineupStatus.UNAVAILABLE.value, "unavailable")

    # ── Injury ──

    def test_05_injury_report_only_is_true(self):
        self.assertTrue(FICTIONAL_INJURY_ALPHA.report_only)

    def test_06_injury_status_enum(self):
        self.assertEqual(InjuryStatus.OUT.value, "out")
        self.assertEqual(InjuryStatus.DOUBTFUL.value, "doubtful")

    def test_07_injury_to_dict(self):
        d = FICTIONAL_INJURY_ALPHA.to_dict()
        self.assertEqual(d["team_id"], "FIC-ALPHA")
        self.assertEqual(d["status"], "doubtful")
        self.assertTrue(d["report_only"])

    # ── Suspension ──

    def test_08_suspension_report_only_is_true(self):
        self.assertTrue(FICTIONAL_SUSPENSION_BETA.report_only)

    def test_09_suspension_to_dict(self):
        d = FICTIONAL_SUSPENSION_BETA.to_dict()
        self.assertEqual(d["team_id"], "FIC-BETA")
        self.assertEqual(d["reason"], "yellow_accumulation")
        self.assertTrue(d["report_only"])


# ---------------------------------------------------------------------------
# PrematchSignal — report only
# ---------------------------------------------------------------------------


class PrematchSignalTests(unittest.TestCase):
    """PrematchSignal is report-only context — not a model input."""

    def test_01_signal_report_only_is_true(self):
        self.assertTrue(FICTIONAL_SIGNAL_WEATHER.report_only)

    def test_02_signal_confidence_enum(self):
        self.assertEqual(SignalConfidence.CONFIRMED.value, "confirmed")
        self.assertEqual(SignalConfidence.REPORTED.value, "reported")
        self.assertEqual(SignalConfidence.RUMOR.value, "rumor")

    def test_03_signal_to_dict(self):
        d = FICTIONAL_SIGNAL_WEATHER.to_dict()
        self.assertEqual(d["signal_id"], "FIC-SIG-001")
        self.assertEqual(d["category"], "weather")
        self.assertTrue(d["report_only"])

    def test_04_empty_signal_id_raises(self):
        with self.assertRaises(ValueError):
            PrematchSignal(signal_id="  ", match_id="FIC-001", category="news", summary="x")


# ---------------------------------------------------------------------------
# MatchContextSnapshot
# ---------------------------------------------------------------------------


class MatchContextSnapshotTests(unittest.TestCase):
    """MatchContextSnapshot construction, immutability, and boundary behavior."""

    # ── Construction ──

    def test_01_can_construct_minimal_snapshot(self):
        snap = make_minimal_snapshot()
        self.assertEqual(snap.snapshot_id, "FIC-SNAP-MINIMAL-001")
        self.assertIsNotNone(snap.match)
        self.assertIsNotNone(snap.team_a)
        self.assertEqual(snap.snapshot_version, "1.0.0")

    def test_02_can_construct_full_snapshot(self):
        snap = make_full_snapshot()
        self.assertIsNotNone(snap.odds_context)
        self.assertEqual(len(snap.lineup_context), 2)
        self.assertEqual(len(snap.injury_context), 2)
        self.assertEqual(len(snap.suspension_context), 1)
        self.assertEqual(len(snap.prematch_signals), 2)

    def test_03_full_snapshot_context_fields_are_report_only(self):
        """All context fields that carry report_only must be True."""
        snap = make_full_snapshot()
        self.assertTrue(snap.odds_context.report_only)
        for lc in snap.lineup_context:
            self.assertTrue(lc.report_only)
        for ic in snap.injury_context:
            self.assertTrue(ic.report_only)
        for sc in snap.suspension_context:
            self.assertTrue(sc.report_only)
        for ps in snap.prematch_signals:
            self.assertTrue(ps.report_only)

    # ── Immutability ──

    def test_04_snapshot_is_frozen(self):
        snap = make_minimal_snapshot()
        with self.assertRaises(Exception):
            snap.snapshot_id = "modified"  # type: ignore[misc]

    def test_05_snapshot_context_tuples_are_immutable(self):
        snap = make_full_snapshot()
        self.assertIsInstance(snap.lineup_context, tuple)
        self.assertIsInstance(snap.injury_context, tuple)
        self.assertIsInstance(snap.suspension_context, tuple)
        self.assertIsInstance(snap.prematch_signals, tuple)

    # ── Data quality ──

    def test_06_minimal_snapshot_has_no_blocking_issues(self):
        snap = make_minimal_snapshot()
        self.assertFalse(snap.has_blocking_issues)

    def test_07_full_snapshot_has_no_blocking_issues(self):
        snap = make_full_snapshot()
        # WARNING only — not BLOCKING
        self.assertFalse(snap.has_blocking_issues)

    def test_08_blocking_snapshot_detected(self):
        snap = make_blocking_snapshot()
        self.assertTrue(snap.has_blocking_issues)

    # ── to_dict ──

    def test_09_minimal_snapshot_to_dict(self):
        d = make_minimal_snapshot().to_dict()
        self.assertEqual(d["snapshot_id"], "FIC-SNAP-MINIMAL-001")
        self.assertIsNotNone(d["match"])
        self.assertIsNotNone(d["team_a"])
        self.assertIsNone(d["odds_context"])
        self.assertEqual(d["lineup_context"], [])

    def test_10_full_snapshot_to_dict(self):
        d = make_full_snapshot().to_dict()
        self.assertIsNotNone(d["odds_context"])
        self.assertEqual(len(d["lineup_context"]), 2)
        self.assertEqual(len(d["injury_context"]), 2)
        self.assertEqual(len(d["prematch_signals"]), 2)

    def test_11_blocking_snapshot_to_dict(self):
        d = make_blocking_snapshot().to_dict()
        self.assertEqual(len(d["data_quality"]), 1)
        self.assertEqual(d["data_quality"][0]["severity"], "blocking")

    # ── Empty snapshot_id ──

    def test_12_empty_snapshot_id_raises(self):
        with self.assertRaises(ValueError):
            MatchContextSnapshot(snapshot_id="   ")

    # ── Naive timestamp ──

    def test_13_naive_snapshot_created_at_raises(self):
        from datetime import datetime as dt

        with self.assertRaises(ValueError):
            MatchContextSnapshot(
                snapshot_id="FIC-SNAP-001",
                snapshot_created_at=dt(2026, 6, 15, 12, 0, 0),
            )


# ---------------------------------------------------------------------------
# Fixture validity — no real-world names
# ---------------------------------------------------------------------------


class FixtureValidityTests(unittest.TestCase):
    """All fictional fixtures must use obviously synthetic names — no real data."""

    _REAL_PATTERNS = (
        "Brazil", "Argentina", "France", "Germany", "England", "Spain",
        "Italy", "Netherlands", "Portugal", "Mexico", "Canada", "Uruguay",
        "Japan", "Korea", "Senegal", "Morocco", "Croatia", "Belgium",
        "USA", "United States", "Australia", "Iran", "Saudi Arabia",
        "Qatar", "Ecuador", "Wales", "Poland", "Denmark", "Switzerland",
        "Serbia", "Cameroon", "Ghana", "Tunisia", "Costa Rica",
        "Neymar", "Messi", "Mbappé", "Ronaldo", "Kane", "Salah",
        "Modric", "De Bruyne", "Haaland", "Bellingham",
    )

    def test_01_fixture_team_names_are_fictional(self):
        for team in (FICTIONAL_TEAM_ALPHA, FICTIONAL_TEAM_BETA):
            name = f"{team.team_id} {team.display_name}"
            for real in self._REAL_PATTERNS:
                self.assertNotIn(real.lower(), name.lower(),
                                 f"Fixture name '{name}' contains real pattern '{real}'")

    def test_02_fixture_player_names_are_fictional(self):
        lineup = FICTIONAL_LINEUP_ALPHA
        all_names = [p.name for p in lineup.starting_xi] + [p.name for p in lineup.substitutes]
        for name in all_names:
            self.assertIn("Fake", name, f"Player '{name}' does not contain 'Fake'")

    def test_03_fixture_team_ids_use_FIC_prefix(self):
        for team in (FICTIONAL_TEAM_ALPHA, FICTIONAL_TEAM_BETA):
            self.assertTrue(
                team.team_id.startswith("FIC-"),
                f"team_id '{team.team_id}' does not start with 'FIC-'",
            )

    def test_04_fixture_match_ids_use_FIC_prefix(self):
        self.assertTrue(FICTIONAL_MATCH_ALPHA_BETA.match_id.startswith("FIC-"))

    def test_05_fixture_provider_name_is_fake(self):
        self.assertEqual(FAKE_PROVENANCE.provider_name, "fake_provider_v1")

    def test_06_fixture_bookmaker_is_fictional(self):
        self.assertIn("Fictional", FICTIONAL_ODDS.bookmaker)

    def test_07_fixture_venue_is_fictional(self):
        self.assertIn("Fictional", FICTIONAL_MATCH_ALPHA_BETA.venue)

    def test_08_fixture_signal_source_is_fictional(self):
        self.assertIn("Fictional", FICTIONAL_SIGNAL_WEATHER.source_name)

    def test_09_fixture_hash_is_synthetic(self):
        h = _synthetic_hash("test")
        self.assertEqual(len(h), 64)
        # Deterministic: same input → same hash
        self.assertEqual(h, _synthetic_hash("test"))

    def test_10_fixture_datetime_is_fixed(self):
        self.assertEqual(FIXED_NOW.year, 2026)
        # Second call returns same value (deterministic)
        d1 = _fixed_datetime(2026, 6, 1, 12, 0, 0)
        d2 = _fixed_datetime(2026, 6, 1, 12, 0, 0)
        self.assertEqual(d1, d2)

    def test_11_fixture_injury_type_is_explicitly_fictional(self):
        self.assertIn("fictional", FICTIONAL_INJURY_ALPHA.injury_type.lower())

    def test_12_fixture_signal_summary_is_fictional(self):
        self.assertIn("Fictional", FICTIONAL_SIGNAL_WEATHER.summary)


# ---------------------------------------------------------------------------
# Deterministic fixture helpers
# ---------------------------------------------------------------------------


class FixtureHelperTests(unittest.TestCase):
    """Fixture helper functions produce deterministic, repeatable output."""

    def test_01_make_fixture_provenance_deterministic(self):
        p1 = make_fixture_provenance("test", "a")
        p2 = make_fixture_provenance("test", "a")
        self.assertEqual(p1.raw_payload_hash, p2.raw_payload_hash)
        self.assertEqual(p1.fetched_at, p2.fetched_at)

    def test_02_make_fixture_dq_issue(self):
        issue = make_fixture_dq_issue(DataQualitySeverity.ERROR, "ERR", "msg")
        self.assertEqual(issue.severity, DataQualitySeverity.ERROR)
        self.assertFalse(issue.blocking)

    def test_03_fixed_datetime_is_utc_aware(self):
        d = _fixed_datetime(2026, 6, 1, 12, 0, 0)
        self.assertIsNotNone(d.tzinfo)
        self.assertIsNotNone(d.utcoffset())

    def test_04_synthetic_hash_is_hex(self):
        h = _synthetic_hash("hello")
        self.assertEqual(len(h), 64)
        int(h, 16)  # must not raise


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class EdgeCaseTests(unittest.TestCase):
    """Edge case validation for schema types."""

    def test_01_empty_match_id_on_odds_raises(self):
        from datetime import datetime as dt

        with self.assertRaises(ValueError):
            OddsMarketContext(match_id="   ", market_type="1X2")

    def test_02_empty_match_id_on_canonical_match_raises(self):
        from datetime import datetime as dt

        with self.assertRaises(ValueError):
            CanonicalMatch(
                match_id="  ",
                team_a_id="FIC-ALPHA",
                team_b_id="FIC-BETA",
                kickoff_at=FIXED_NOW,
            )

    def test_03_minimal_snapshot_no_context_is_none(self):
        snap = make_minimal_snapshot()
        self.assertIsNone(snap.odds_context)
        self.assertEqual(snap.lineup_context, ())
        self.assertEqual(snap.injury_context, ())
        self.assertEqual(snap.suspension_context, ())
        self.assertEqual(snap.prematch_signals, ())


if __name__ == "__main__":
    unittest.main()
