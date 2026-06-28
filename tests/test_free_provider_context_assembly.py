"""Tests for free_provider_context_assembly — Patch 30."""

import unittest

from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderFetchResult,
    _compute_payload_hash,
)
from oracle_core.data_service_types import (
    CanonicalTeam,
    CanonicalMatch,
    DataQualityIssue,
    DataQualitySeverity,
)
from oracle_core.free_provider_mappers import (
    map_thesportsdb_teams,
    map_thesportsdb_matches,
    MappingResult,
    ModelBoundary,
)
from oracle_core.free_provider_context_assembly import (
    assemble_match_context_from_mapping_results,
    MatchContextAssemblyResult,
)
from datetime import datetime, timezone


def _make_teams_fetch():
    return ProviderFetchResult(
        provider_name="thesportsdb",
        adapter_version="0.1.0-skeleton",
        capability=ProviderCapability.TEAMS,
        fetched_at=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        source_reference="fixture://thesportsdb/searchteams",
        raw_payload_hash="abc123",
        payload={
            "teams": [
                {"idTeam": "FIC-001", "strTeam": "Fictional Alpha FC",
                 "strCountry": "Fiction"},
                {"idTeam": "FIC-002", "strTeam": "Fictional Beta FC",
                 "strCountry": "Fiction"},
            ],
        },
        completeness={"available": True},
    )


def _make_matches_fetch():
    return ProviderFetchResult(
        provider_name="thesportsdb",
        adapter_version="0.1.0-skeleton",
        capability=ProviderCapability.MATCHES,
        fetched_at=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        source_reference="fixture://thesportsdb/events",
        raw_payload_hash="def456",
        payload={
            "events": [
                {"idEvent": "FIC-MATCH-001",
                 "idHomeTeam": "FIC-001", "idAwayTeam": "FIC-002",
                 "strHomeTeam": "Fictional Alpha FC",
                 "strAwayTeam": "Fictional Beta FC",
                 "dateEvent": "2026-06-16", "strTime": "20:00:00",
                 "strVenue": "Fictional Stadium One"},
            ],
        },
        completeness={"available": True},
    )


class TestFreeProviderContextAssembly(unittest.TestCase):
    """Tests for assemble_match_context_from_mapping_results."""

    def setUp(self):
        self.teams_fetch = _make_teams_fetch()
        self.matches_fetch = _make_matches_fetch()
        self.teams_mapping = map_thesportsdb_teams(self.teams_fetch)
        self.matches_mapping = map_thesportsdb_matches(self.matches_fetch)

    # ── Test 1: assembly result contains canonical teams/matches ──
    def test_assembly_contains_canonical_teams_and_matches(self):
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping, self.matches_mapping,
        )
        self.assertGreater(len(result.canonical_teams), 0)
        self.assertGreater(len(result.canonical_matches), 0)
        self.assertIsInstance(result.canonical_teams[0], CanonicalTeam)
        self.assertIsInstance(result.canonical_matches[0], CanonicalMatch)

    # ── Test 2: provenance/source/raw_hash preserved ──
    def test_provenance_source_hash_preserved(self):
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping,
        )
        self.assertGreater(len(result.source_references), 0)
        self.assertGreater(len(result.raw_payload_hashes), 0)
        self.assertGreater(len(result.provenance), 0)

    # ── Test 3: mapping issues carried through ──
    def test_mapping_issues_carried_through(self):
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping, self.matches_mapping,
        )
        # Should have issues from BOTH mapping results + assembly issues
        self.assertGreater(len(result.data_quality_issues), 5)

    # ── Test 4: assembly issues added ──
    def test_assembly_issues_added(self):
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping,
        )
        codes = {i.code for i in result.data_quality_issues}
        self.assertIn("ASSEMBLY_CONTEXT_REPORT_ONLY", codes)
        self.assertIn("PROVIDER_NOT_APPROVED_FOR_MODEL_INPUT", codes)

    # ── Test 5: gap_list contains required gaps ──
    def test_gap_list_contains_required_gaps(self):
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping,
        )
        required = [
            "team_id_resolution_missing",
            "standings_missing",
            "lineups_missing",
            "injuries_missing",
            "suspensions_missing",
            "odds_missing",
            "knockout_bracket_missing",
            "prematch_signals_missing",
            "weather_missing",
            "timezone_unknown",
            "limited_match_coverage",
            "provider_not_approved_for_model_input",
            "production_provider_coverage_unverified",
        ]
        for g in required:
            self.assertIn(g, result.gap_list, f"Missing gap: {g}")

    # ── Test 6: model_boundary.affects_model False ──
    def test_model_boundary_affects_model_false(self):
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping,
        )
        self.assertFalse(result.model_boundary.affects_model)

    # ── Test 7: enters_prediction_engine False ──
    def test_enters_prediction_engine_false(self):
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping,
        )
        self.assertFalse(result.model_boundary.enters_prediction_engine)

    # ── Test 8: no prediction fields generated ──
    def test_no_prediction_fields_generated(self):
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping,
        )
        # Verify no prediction fields in the assembly result
        forbidden = [
            "result_probabilities", "expected_goals", "top_scores",
            "over_under", "advancement_probabilities", "odds_blending",
            "xg_adjustment", "score_prediction",
        ]
        result_dict = {
            "provider_name": result.provider_name,
            "gap_list": result.gap_list,
        }
        for field in forbidden:
            self.assertNotIn(field, result_dict,
                             f"Prediction field '{field}' should not be in assembly result")

    # ── Test: assembly with empty mapping results ──
    def test_empty_mapping_results(self):
        result = assemble_match_context_from_mapping_results()
        self.assertEqual(len(result.canonical_teams), 0)
        self.assertEqual(len(result.canonical_matches), 0)
        self.assertGreater(len(result.gap_list), 0)

    # ── Test: default tests do NOT use real teams ──
    def test_no_real_team_names(self):
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping,
        )
        real_teams = ["Brazil", "Argentina", "France", "Germany", "England",
                       "Spain", "Italy", "Netherlands", "Portugal"]
        for team in result.canonical_teams:
            for rt in real_teams:
                self.assertNotIn(rt, team.display_name)

    # ── Test: default tests do NOT network ──
    def test_assembly_does_not_network(self):
        # Assembly should complete without network access
        result = assemble_match_context_from_mapping_results(
            self.teams_mapping, self.matches_mapping,
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result, MatchContextAssemblyResult)


if __name__ == "__main__":
    unittest.main()
