"""Patch 29 — TheSportsDB canonical mapper offline tests.

All offline.  No network.  No real data.  No skipped tests.
Uses synthetic TheSportsDB-shaped payloads (FIC-* fictional data only).
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from oracle_core.data_service_providers import (
    DeterministicFakeProvider,
    ProviderCapability,
    ProviderFetchResult,
)
from oracle_core.data_service_types import (
    CanonicalTeam,
    CanonicalMatch,
    DataQualityIssue,
    DataQualitySeverity,
    ProviderProvenance,
    _fixed_datetime,
    _synthetic_hash,
)
from oracle_core.data_service_store import DataServiceLocalStore
from oracle_core.free_provider_mappers import (
    MappingResult,
    ModelBoundary,
    map_thesportsdb_teams,
    map_thesportsdb_matches,
    _common_issues,
    _issue,
)

from tests.provider_contract_helpers import (
    assert_provider_does_not_import_prediction_runtime,
)

REPO = pathlib.Path(__file__).parent.parent


# ==========================================================================
# Synthetic TheSportsDB-shaped payloads (FIC-* fictional data only)
# ==========================================================================

_SYNTH_TEAMS_PAYLOAD = {
    "teams": [
        {
            "idTeam": "FIC-TEAM-ALPHA",
            "strTeam": "Fictional Alpha FC",
            "strCountry": "Fiction",
            "strLeague": "Fake Cup",
            "strSport": "Soccer",
            "strBadge": "https://example.com/badge/alpha.png",
        },
        {
            "idTeam": "FIC-TEAM-BETA",
            "strTeam": "Fictional Beta FC",
            "strCountry": "Fiction",
            "strLeague": "Fake Cup",
            "strSport": "Soccer",
        },
    ],
}

_SYNTH_MATCHES_PAYLOAD = {
    "events": [
        {
            "idEvent": "FIC-MATCH-001",
            "strEvent": "Fictional Alpha FC vs Fictional Beta FC",
            "idHomeTeam": "FIC-TEAM-ALPHA",
            "idAwayTeam": "FIC-TEAM-BETA",
            "strHomeTeam": "Fictional Alpha FC",
            "strAwayTeam": "Fictional Beta FC",
            "dateEvent": "2026-06-16",
            "strTime": "20:00:00",
            "strVenue": "Fictional Stadium One",
            "strSeason": "Fake Season",
            "strLeague": "Fake Cup",
        },
        {
            "idEvent": "FIC-MATCH-002",
            "strEvent": "Fictional Gamma FC vs Fictional Delta FC",
            "idHomeTeam": "FIC-TEAM-GAMMA",
            "idAwayTeam": "FIC-TEAM-DELTA",
            "strHomeTeam": "Fictional Gamma FC",
            "strAwayTeam": "Fictional Delta FC",
            "dateEvent": "2026-06-17",
            "strTime": "23:00:00",
            "strVenue": "Fictional Stadium Two",
            "strSeason": "Fake Season",
            "strLeague": "Fake Cup",
        },
    ],
}


def _make_teams_result(
    payload: dict | None = None,
    *,
    source_reference: str = "fixture://thesportsdb/searchteams",
) -> ProviderFetchResult:
    """Build a synthetic TheSportsDB TEAMS ProviderFetchResult."""
    if payload is None:
        payload = _SYNTH_TEAMS_PAYLOAD
    raw_hash = _synthetic_hash(f"thesportsdb-teams:{source_reference}")
    return ProviderFetchResult(
        provider_name="thesportsdb",
        adapter_version="0.1.0-skeleton",
        capability=ProviderCapability.TEAMS,
        fetched_at=_fixed_datetime(2026, 6, 15, 12, 0, 0),
        source_reference=source_reference,
        raw_payload_hash=raw_hash,
        payload=payload,
        license_notes="Free tier — license review pending (<needs_human_review>)",
        completeness={"available": True},
    )


def _make_matches_result(
    payload: dict | None = None,
    *,
    source_reference: str = "fixture://thesportsdb/events",
) -> ProviderFetchResult:
    """Build a synthetic TheSportsDB MATCHES ProviderFetchResult."""
    if payload is None:
        payload = _SYNTH_MATCHES_PAYLOAD
    raw_hash = _synthetic_hash(f"thesportsdb-matches:{source_reference}")
    return ProviderFetchResult(
        provider_name="thesportsdb",
        adapter_version="0.1.0-skeleton",
        capability=ProviderCapability.MATCHES,
        fetched_at=_fixed_datetime(2026, 6, 15, 12, 0, 0),
        source_reference=source_reference,
        raw_payload_hash=raw_hash,
        payload=payload,
        license_notes="Free tier — license review pending (<needs_human_review>)",
        completeness={"available": True},
    )


# ==========================================================================
# 1. Module existence
# ==========================================================================


class MapperModuleExistenceTests(unittest.TestCase):
    def test_01_mapper_module_exists(self):
        mod_path = REPO / "oracle_core" / "free_provider_mappers.py"
        self.assertTrue(mod_path.exists(),
                        "free_provider_mappers.py must exist")

    def test_02_mapping_result_class_exists(self):
        m = MappingResult(provider_name="test", capability="teams")
        self.assertTrue(hasattr(m, "provider_name"))
        self.assertTrue(hasattr(m, "canonical_items"))
        self.assertTrue(hasattr(m, "model_boundary"))

    def test_03_model_boundary_class_exists(self):
        self.assertTrue(hasattr(ModelBoundary, "affects_model"))
        self.assertTrue(hasattr(ModelBoundary, "enters_prediction_engine"))


# ==========================================================================
# 2. Import boundary — mapper does not import prediction runtime
# ==========================================================================


class MapperImportBoundaryTests(unittest.TestCase):
    def test_01_mapper_does_not_import_prediction(self):
        mod_path = REPO / "oracle_core" / "free_provider_mappers.py"
        assert_provider_does_not_import_prediction_runtime(mod_path)

    def test_02_prediction_modules_do_not_import_mapper(self):
        """Prediction/engine modules must not import the mapper module."""
        engine_root = REPO / "oracle_core"
        for mod_name in ("engine.py", "types.py", "knockout.py",
                          "tournament.py", "odds.py"):
            mp = engine_root / mod_name
            if not mp.exists():
                continue
            source = mp.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("free_provider_mappers", alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertNotIn("free_provider_mappers", node.module)


# ==========================================================================
# 3–4. map_thesportsdb_teams / map_thesportsdb_matches return MappingResult
# ==========================================================================


class MappingResultReturnTypeTests(unittest.TestCase):
    def test_01_teams_returns_mapping_result(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertIsInstance(m, MappingResult)

    def test_02_matches_returns_mapping_result(self):
        r = _make_matches_result()
        m = map_thesportsdb_matches(r)
        self.assertIsInstance(m, MappingResult)


# ==========================================================================
# 5. Teams mapping produces CanonicalTeam items from synthetic payload
# ==========================================================================


class TeamsMappingCanonicalTests(unittest.TestCase):
    def setUp(self):
        self.r = _make_teams_result()
        self.m = map_thesportsdb_teams(self.r)

    def test_01_produces_canonical_teams(self):
        self.assertGreater(len(self.m.canonical_items), 0)
        for item in self.m.canonical_items:
            self.assertIsInstance(item, CanonicalTeam)

    def test_02_team_id_is_from_id_team(self):
        ids = {t.team_id for t in self.m.canonical_items}
        self.assertIn("FIC-TEAM-ALPHA", ids)
        self.assertIn("FIC-TEAM-BETA", ids)

    def test_03_display_name_is_from_str_team(self):
        names = {t.display_name for t in self.m.canonical_items}
        self.assertIn("Fictional Alpha FC", names)
        self.assertIn("Fictional Beta FC", names)

    def test_04_external_ids_contains_thesportsdb_key(self):
        for t in self.m.canonical_items:
            self.assertIn("thesportsdb", t.external_ids)

    def test_05_country_code_is_none(self):
        """strCountry is full name, not ISO code."""
        for t in self.m.canonical_items:
            self.assertIsNone(t.country_code)

    def test_06_country_not_iso_issue_present(self):
        country_issues = [
            i for i in self.m.data_quality_issues
            if i.code == "COUNTRY_NOT_ISO"
        ]
        # One per team entry that has strCountry
        self.assertGreater(len(country_issues), 0)

    def test_07_badge_info_issue_present(self):
        """strBadge triggers BADGE_REPORT_ONLY info issue."""
        badge_issues = [
            i for i in self.m.data_quality_issues
            if i.code == "BADGE_REPORT_ONLY"
        ]
        self.assertGreater(len(badge_issues), 0)

    def test_08_provenance_per_item(self):
        for t in self.m.canonical_items:
            self.assertGreater(len(t.provenance_refs), 0)
            prov = t.provenance_refs[0]
            self.assertEqual(prov.provider_name, "thesportsdb")


# ==========================================================================
# 6. Matches mapping produces CanonicalMatch items from synthetic payload
# ==========================================================================


class MatchesMappingCanonicalTests(unittest.TestCase):
    def setUp(self):
        self.r = _make_matches_result()
        self.m = map_thesportsdb_matches(self.r)

    def test_01_produces_canonical_matches(self):
        self.assertGreater(len(self.m.canonical_items), 0)
        for item in self.m.canonical_items:
            self.assertIsInstance(item, CanonicalMatch)

    def test_02_match_id_is_from_id_event(self):
        ids = {m.match_id for m in self.m.canonical_items}
        self.assertIn("FIC-MATCH-001", ids)
        self.assertIn("FIC-MATCH-002", ids)

    def test_03_team_ids_use_provider_ids(self):
        """Should prefer idHomeTeam/idAwayTeam over strHomeTeam/strAwayTeam."""
        match = self.m.canonical_items[0]
        self.assertEqual(match.team_a_id, "FIC-TEAM-ALPHA")
        self.assertEqual(match.team_b_id, "FIC-TEAM-BETA")

    def test_04_kickoff_is_aware_datetime(self):
        for m in self.m.canonical_items:
            self.assertIsNotNone(m.kickoff_at.tzinfo)

    def test_05_venue_is_mapped(self):
        venues = {m.venue for m in self.m.canonical_items}
        self.assertIn("Fictional Stadium One", venues)

    def test_06_timezone_unknown_warning_present(self):
        """TheSportsDB dateEvent has no timezone — TIMEZONE_UNKNOWN expected."""
        tz_issues = [
            i for i in self.m.data_quality_issues
            if i.code == "TIMEZONE_UNKNOWN"
        ]
        self.assertGreater(len(tz_issues), 0)
        for issue in tz_issues:
            self.assertEqual(issue.severity, DataQualitySeverity.WARNING)

    def test_07_neutral_site_is_true(self):
        for m in self.m.canonical_items:
            self.assertTrue(m.neutral_site)

    def test_08_provenance_per_item(self):
        for m in self.m.canonical_items:
            self.assertGreater(len(m.provenance_refs), 0)
            prov = m.provenance_refs[0]
            self.assertEqual(prov.provider_name, "thesportsdb")


# ==========================================================================
# 7. Missing team id produces DataQualityIssue
# ==========================================================================


class MissingTeamIdTests(unittest.TestCase):
    def test_01_missing_id_team_blocking(self):
        payload = {"teams": [{"strTeam": "No ID Team"}]}
        r = _make_teams_result(payload)
        m = map_thesportsdb_teams(r)
        blocking = [i for i in m.data_quality_issues if i.code == "MISSING_TEAM_PROVIDER_ID"]
        self.assertGreater(len(blocking), 0)
        self.assertEqual(blocking[0].severity, DataQualitySeverity.BLOCKING)

    def test_02_empty_id_team_blocking(self):
        payload = {"teams": [{"idTeam": "", "strTeam": "Empty ID Team"}]}
        r = _make_teams_result(payload)
        m = map_thesportsdb_teams(r)
        blocking = [i for i in m.data_quality_issues if i.code == "MISSING_TEAM_PROVIDER_ID"]
        self.assertGreater(len(blocking), 0)


# ==========================================================================
# 8. Missing team name produces DataQualityIssue
# ==========================================================================


class MissingTeamNameTests(unittest.TestCase):
    def test_01_missing_str_team_blocking(self):
        payload = {"teams": [{"idTeam": "FIC-001"}]}
        r = _make_teams_result(payload)
        m = map_thesportsdb_teams(r)
        blocking = [i for i in m.data_quality_issues if i.code == "MISSING_TEAM_NAME"]
        self.assertGreater(len(blocking), 0)
        self.assertEqual(blocking[0].severity, DataQualitySeverity.BLOCKING)

    def test_02_empty_str_team_blocking(self):
        payload = {"teams": [{"idTeam": "FIC-001", "strTeam": "   "}]}
        r = _make_teams_result(payload)
        m = map_thesportsdb_teams(r)
        blocking = [i for i in m.data_quality_issues if i.code == "MISSING_TEAM_NAME"]
        self.assertGreater(len(blocking), 0)


# ==========================================================================
# 9. Missing match id produces DataQualityIssue
# ==========================================================================


class MissingMatchIdTests(unittest.TestCase):
    def test_01_missing_id_event_blocking(self):
        payload = {"events": [{"strHomeTeam": "A", "strAwayTeam": "B",
                                "dateEvent": "2026-06-16", "strTime": "20:00:00"}]}
        r = _make_matches_result(payload)
        m = map_thesportsdb_matches(r)
        blocking = [i for i in m.data_quality_issues if i.code == "MISSING_MATCH_PROVIDER_ID"]
        self.assertGreater(len(blocking), 0)
        self.assertEqual(blocking[0].severity, DataQualitySeverity.BLOCKING)


# ==========================================================================
# 10. Missing home/away team produces DataQualityIssue
# ==========================================================================


class MissingHomeAwayTeamTests(unittest.TestCase):
    def test_01_missing_home_team_blocking(self):
        payload = {"events": [{"idEvent": "FIC-001",
                                "strAwayTeam": "Away FC",
                                "dateEvent": "2026-06-16", "strTime": "20:00:00"}]}
        r = _make_matches_result(payload)
        m = map_thesportsdb_matches(r)
        blocking = [i for i in m.data_quality_issues if i.code == "MISSING_HOME_TEAM"]
        self.assertGreater(len(blocking), 0)
        self.assertEqual(blocking[0].severity, DataQualitySeverity.BLOCKING)

    def test_02_missing_away_team_blocking(self):
        payload = {"events": [{"idEvent": "FIC-001",
                                "strHomeTeam": "Home FC",
                                "dateEvent": "2026-06-16", "strTime": "20:00:00"}]}
        r = _make_matches_result(payload)
        m = map_thesportsdb_matches(r)
        blocking = [i for i in m.data_quality_issues if i.code == "MISSING_AWAY_TEAM"]
        self.assertGreater(len(blocking), 0)
        self.assertEqual(blocking[0].severity, DataQualitySeverity.BLOCKING)

    def test_03_both_missing_produces_two_issues(self):
        payload = {"events": [{"idEvent": "FIC-001",
                                "dateEvent": "2026-06-16", "strTime": "20:00:00"}]}
        r = _make_matches_result(payload)
        m = map_thesportsdb_matches(r)
        home = [i for i in m.data_quality_issues if i.code == "MISSING_HOME_TEAM"]
        away = [i for i in m.data_quality_issues if i.code == "MISSING_AWAY_TEAM"]
        self.assertEqual(len(home), 1)
        self.assertEqual(len(away), 1)


# ==========================================================================
# 11. Missing kickoff time produces DataQualityIssue
# ==========================================================================


class MissingKickoffTimeTests(unittest.TestCase):
    def test_01_missing_date_event_blocking(self):
        payload = {"events": [{"idEvent": "FIC-001",
                                "strHomeTeam": "Home FC",
                                "strAwayTeam": "Away FC"}]}
        r = _make_matches_result(payload)
        m = map_thesportsdb_matches(r)
        blocking = [i for i in m.data_quality_issues if i.code == "MISSING_KICKOFF"]
        self.assertGreater(len(blocking), 0)
        self.assertEqual(blocking[0].severity, DataQualitySeverity.BLOCKING)

    def test_02_unparseable_date_event_blocking(self):
        payload = {"events": [{"idEvent": "FIC-001",
                                "strHomeTeam": "Home FC",
                                "strAwayTeam": "Away FC",
                                "dateEvent": "not-a-date",
                                "strTime": "20:00:00"}]}
        r = _make_matches_result(payload)
        m = map_thesportsdb_matches(r)
        blocking = [i for i in m.data_quality_issues if i.code == "KICKOFF_UNPARSEABLE"]
        self.assertGreater(len(blocking), 0)


# ==========================================================================
# 12. Empty payload produces DataQualityIssue
# ==========================================================================


class EmptyPayloadTests(unittest.TestCase):
    def test_01_empty_teams_payload_blocking(self):
        payload = {"teams": []}
        r = _make_teams_result(payload)
        m = map_thesportsdb_teams(r)
        blocking = [i for i in m.data_quality_issues if i.code == "EMPTY_TEAMS_PAYLOAD"]
        self.assertGreater(len(blocking), 0)
        self.assertEqual(blocking[0].severity, DataQualitySeverity.BLOCKING)

    def test_02_empty_matches_payload_blocking(self):
        payload = {"events": []}
        r = _make_matches_result(payload)
        m = map_thesportsdb_matches(r)
        blocking = [i for i in m.data_quality_issues if i.code == "EMPTY_MATCHES_PAYLOAD"]
        self.assertGreater(len(blocking), 0)
        self.assertEqual(blocking[0].severity, DataQualitySeverity.BLOCKING)


# ==========================================================================
# 13. Unknown schema produces DataQualityIssue
# ==========================================================================


class UnknownSchemaTests(unittest.TestCase):
    def test_01_teams_no_teams_key(self):
        payload = {"something_else": []}
        r = _make_teams_result(payload)
        m = map_thesportsdb_teams(r)
        issues = [i for i in m.data_quality_issues if i.code == "UNKNOWN_SCHEMA"]
        self.assertGreater(len(issues), 0)

    def test_02_teams_not_a_list(self):
        payload = {"teams": "not_a_list"}
        r = _make_teams_result(payload)
        m = map_thesportsdb_teams(r)
        issues = [i for i in m.data_quality_issues if i.code == "UNKNOWN_SCHEMA"]
        self.assertGreater(len(issues), 0)

    def test_03_matches_no_events_key(self):
        payload = {"something_else": []}
        r = _make_matches_result(payload)
        m = map_thesportsdb_matches(r)
        issues = [i for i in m.data_quality_issues if i.code == "UNKNOWN_SCHEMA"]
        self.assertGreater(len(issues), 0)

    def test_04_matches_not_a_list(self):
        payload = {"events": "not_a_list"}
        r = _make_matches_result(payload)
        m = map_thesportsdb_matches(r)
        issues = [i for i in m.data_quality_issues if i.code == "UNKNOWN_SCHEMA"]
        self.assertGreater(len(issues), 0)

    def test_05_non_dict_entry_in_list(self):
        payload = {"teams": ["not_a_dict"]}
        r = _make_teams_result(payload)
        m = map_thesportsdb_teams(r)
        issues = [i for i in m.data_quality_issues if i.code == "UNKNOWN_SCHEMA"]
        self.assertGreater(len(issues), 0)


# ==========================================================================
# 14. eventsnextleague limited coverage produces warning issue
# ==========================================================================


class LimitedCoverageWarningTests(unittest.TestCase):
    def test_01_eventsnextleague_in_source_triggers_warning(self):
        r = _make_matches_result(
            source_reference="https://www.thesportsdb.com/api/v1/json/<public_test_key>/eventsnextleague.php?id=4328")
        m = map_thesportsdb_matches(r)
        warnings = [i for i in m.data_quality_issues if i.code == "LIMITED_MATCH_COVERAGE"]
        self.assertGreater(len(warnings), 0)
        self.assertEqual(warnings[0].severity, DataQualitySeverity.WARNING)

    def test_02_no_warning_for_non_eventsnextleague_source(self):
        r = _make_matches_result(
            source_reference="fixture://thesportsdb/events")
        m = map_thesportsdb_matches(r)
        warnings = [i for i in m.data_quality_issues if i.code == "LIMITED_MATCH_COVERAGE"]
        self.assertEqual(len(warnings), 0)


# ==========================================================================
# 15–16. model_boundary tests
# ==========================================================================


class ModelBoundaryTests(unittest.TestCase):
    def test_01_affects_model_always_false_teams(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertFalse(m.model_boundary.affects_model)

    def test_02_affects_model_always_false_matches(self):
        r = _make_matches_result()
        m = map_thesportsdb_matches(r)
        self.assertFalse(m.model_boundary.affects_model)

    def test_03_enters_prediction_engine_always_false_teams(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertFalse(m.model_boundary.enters_prediction_engine)

    def test_04_enters_prediction_engine_always_false_matches(self):
        r = _make_matches_result()
        m = map_thesportsdb_matches(r)
        self.assertFalse(m.model_boundary.enters_prediction_engine)

    def test_05_report_only_always_true(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertTrue(m.model_boundary.report_only_or_context_only)

    def test_06_boundary_info_issue_present(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        issues = [i for i in m.data_quality_issues
                   if i.code == "MODEL_BOUNDARY_REPORT_ONLY"]
        self.assertGreater(len(issues), 0)
        self.assertEqual(issues[0].severity, DataQualitySeverity.INFO)


# ==========================================================================
# 17. No forbidden model output keys in mapping result
# ==========================================================================


class NoModelOutputKeysTests(unittest.TestCase):
    _BANNED = (
        "result_probabilities", "expected_goals", "top_scores",
        "over_under", "over_under_probabilities", "advancement_probabilities",
        "prediction", "predicted_score", "model_probability", "model_probabilities",
    )

    def test_01_teams_canonical_items_no_banned_keys(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        for item in m.canonical_items:
            d = item.to_dict()
            # Check dict keys (not values/messages)
            self._assert_no_banned_keys(d, "teams item")

    def test_02_matches_canonical_items_no_banned_keys(self):
        r = _make_matches_result()
        m = map_thesportsdb_matches(r)
        for item in m.canonical_items:
            d = item.to_dict()
            self._assert_no_banned_keys(d, "matches item")

    def test_03_mapping_result_level_no_banned_keys(self):
        """MappingResult itself must not have banned keys as top-level fields."""
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        # Only check top-level MappingResult fields (not messages/descriptions)
        result_keys = {"provider_name", "capability", "canonical_items",
                        "data_quality_issues", "provenance", "source_reference",
                        "raw_payload_hash", "mapped_at", "model_boundary"}
        for key in self._BANNED:
            self.assertNotIn(key, result_keys,
                             f"Forbidden key '{key}' would be a MappingResult field")

    def _assert_no_banned_keys(self, d: dict, label: str):
        """Recursively check dict keys for banned model output keys."""
        for key in d:
            self.assertNotIn(key, self._BANNED,
                             f"Forbidden key '{key}' found in {label} dict keys")


# ==========================================================================
# 18–19. No odds blending / xG adjustment fields
# ==========================================================================


class NoOddsOrXgFieldsTests(unittest.TestCase):
    def test_01_teams_no_odds_fields(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        result_str = str(m)
        for term in ("odds_blend", "market_blend", "xG_adjustment",
                      "xG", "xg_adjustment", "expected_goals_adjustment"):
            self.assertNotIn(term, result_str.lower())

    def test_02_matches_no_odds_fields(self):
        r = _make_matches_result()
        m = map_thesportsdb_matches(r)
        result_str = str(m)
        for term in ("odds_blend", "market_blend", "xG_adjustment",
                      "xG", "xg_adjustment", "expected_goals_adjustment"):
            self.assertNotIn(term, result_str.lower())


# ==========================================================================
# 20. No narrative prediction
# ==========================================================================


class NoNarrativePredictionTests(unittest.TestCase):
    _NARRATIVE_RE = re.compile(
        r"(I predict|will win|is going to win|predicted winner"
        r"|final score prediction|most likely outcome is"
        r"|likely score|expected winner|forecast)",
        re.IGNORECASE,
    )

    def test_01_teams_no_narrative(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        result_str = str(m)
        self.assertIsNone(self._NARRATIVE_RE.search(result_str))

    def test_02_matches_no_narrative(self):
        r = _make_matches_result()
        m = map_thesportsdb_matches(r)
        result_str = str(m)
        self.assertIsNone(self._NARRATIVE_RE.search(result_str))


# ==========================================================================
# 21. Source reference remains redacted for live-like result
# ==========================================================================


class SourceReferenceRedactionTests(unittest.TestCase):
    def test_01_redacted_source_preserved(self):
        ref = "https://www.thesportsdb.com/api/v1/json/<public_test_key>/searchteams.php"
        r = _make_teams_result(source_reference=ref)
        m = map_thesportsdb_teams(r)
        self.assertEqual(m.source_reference, ref)
        self.assertIn("<public_test_key>", m.source_reference)

    def test_02_redacted_source_in_provenance(self):
        ref = "https://www.thesportsdb.com/api/v1/json/<public_test_key>/searchteams.php"
        r = _make_teams_result(source_reference=ref)
        m = map_thesportsdb_teams(r)
        self.assertEqual(m.provenance.source_reference, ref)


# ==========================================================================
# 22. Unredacted source_reference is rejected/blocking
# ==========================================================================


class UnredactedSourceReferenceTests(unittest.TestCase):
    def test_01_unredacted_123_key_blocking(self):
        r = _make_teams_result(
            source_reference="https://www.thesportsdb.com/api/v1/json/123/searchteams.php")
        m = map_thesportsdb_teams(r)
        blocking = [i for i in m.data_quality_issues
                     if i.code == "UNREDACTED_SOURCE_REFERENCE"]
        self.assertGreater(len(blocking), 0)
        self.assertEqual(blocking[0].severity, DataQualitySeverity.BLOCKING)


# ==========================================================================
# 23. raw_payload_hash is preserved from ProviderFetchResult
# ==========================================================================


class RawPayloadHashPreservationTests(unittest.TestCase):
    def test_01_teams_hash_preserved(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertEqual(m.raw_payload_hash, r.raw_payload_hash)

    def test_02_matches_hash_preserved(self):
        r = _make_matches_result()
        m = map_thesportsdb_matches(r)
        self.assertEqual(m.raw_payload_hash, r.raw_payload_hash)

    def test_03_hash_in_item_provenance(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        for item in m.canonical_items:
            for prov in item.provenance_refs:
                self.assertEqual(prov.raw_payload_hash, r.raw_payload_hash)


# ==========================================================================
# 24. Provider provenance is preserved
# ==========================================================================


class ProvenancePreservationTests(unittest.TestCase):
    def test_01_provider_name_in_result(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertEqual(m.provider_name, "thesportsdb")

    def test_02_item_provenance_has_provider_name(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        for item in m.canonical_items:
            self.assertGreater(len(item.provenance_refs), 0)
            self.assertEqual(item.provenance_refs[0].provider_name, "thesportsdb")

    def test_03_item_provenance_has_adapter_version(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        for item in m.canonical_items:
            self.assertEqual(
                item.provenance_refs[0].adapter_version,
                r.adapter_version)

    def test_04_mapping_provenance_not_none(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertIsNotNone(m.provenance)
        self.assertIsInstance(m.provenance, ProviderProvenance)


# ==========================================================================
# 25. No filesystem writes outside tempdir
# ==========================================================================


class NoFilesystemWriteTests(unittest.TestCase):
    """Verify mapper functions are pure — they do not write to filesystem."""

    def test_01_teams_mapper_does_not_write_files(self):
        """map_thesportsdb_teams should not create any files on disk."""
        r = _make_teams_result()
        # Mapping is pure — no side effects
        m = map_thesportsdb_teams(r)
        self.assertIsInstance(m, MappingResult)

    def test_02_matches_mapper_does_not_write_files(self):
        r = _make_matches_result()
        m = map_thesportsdb_matches(r)
        self.assertIsInstance(m, MappingResult)


# ==========================================================================
# 26. Prediction modules do not import mapper module
# ==========================================================================


class PredictionDoesNotImportMapperTests(unittest.TestCase):
    def test_01_prediction_modules_no_mapper_import(self):
        engine_root = REPO / "oracle_core"
        for mod_name in ("engine.py", "types.py", "knockout.py",
                          "tournament.py", "odds.py"):
            mp = engine_root / mod_name
            if not mp.exists():
                continue
            source = mp.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(
                            "free_provider_mappers", alias.name,
                            f"{mod_name} imports free_provider_mappers")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertNotIn(
                            "free_provider_mappers", node.module,
                            f"{mod_name} imports from free_provider_mappers")


# ==========================================================================
# Additional: data_quality_issues format validation
# ==========================================================================


class DataQualityIssueFormatTests(unittest.TestCase):
    def test_01_all_issues_have_severity(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        for issue in m.data_quality_issues:
            self.assertIsInstance(issue.severity, DataQualitySeverity)

    def test_02_all_issues_have_code(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        for issue in m.data_quality_issues:
            self.assertTrue(issue.code)
            self.assertIsInstance(issue.code, str)

    def test_03_all_issues_have_message(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        for issue in m.data_quality_issues:
            self.assertTrue(issue.message)

    def test_04_provenance_refs_has_thesportsdb(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        for issue in m.data_quality_issues:
            self.assertIn("thesportsdb", issue.provenance_refs)

    def test_05_common_issues_includes_needs_more_info(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        codes = {i.code for i in m.data_quality_issues}
        self.assertIn("PROVIDER_NEEDS_MORE_INFO", codes)

    def test_06_common_issues_includes_live_not_approved(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        codes = {i.code for i in m.data_quality_issues}
        self.assertIn("LIVE_DATA_NOT_APPROVED_FOR_MODEL", codes)


# ==========================================================================
# Additional: MappingResult fields
# ==========================================================================


class MappingResultFieldTests(unittest.TestCase):
    def test_01_capability_is_string(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertEqual(m.capability, "teams")

    def test_02_mapped_at_is_aware(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertIsNotNone(m.mapped_at.tzinfo)

    def test_03_canonical_items_is_tuple(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertIsInstance(m.canonical_items, tuple)

    def test_04_data_quality_issues_is_tuple(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertIsInstance(m.data_quality_issues, tuple)

    def test_05_has_blocking_issues_property(self):
        r = _make_teams_result()
        m = map_thesportsdb_teams(r)
        self.assertIsInstance(m.has_blocking_issues, bool)

    def test_06_teams_capability_string(self):
        r = _make_matches_result()
        m = map_thesportsdb_matches(r)
        self.assertEqual(m.capability, "matches")


if __name__ == "__main__":
    unittest.main()
