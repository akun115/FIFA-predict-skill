"""Tests for Data Service v1 validator (Patch 17 + 17.1).

All fixtures fictional. No real data. No network. No prediction integration.
"""

from __future__ import annotations

import ast
import pathlib
import unittest
from datetime import datetime, timedelta, timezone

from oracle_core.data_service_types import DataQualityIssue, DataQualitySeverity

from oracle_core.data_service_validator import (
    ValidationReport,
    _check_context_report_only,
    _check_knockout_missing_bracket,
    _check_stale_lineup,
    _scan_forbidden_model_keys,
    has_blocking_issues,
    validate_canonical_match,
    validate_canonical_team,
    validate_match_context_snapshot,
    validate_provenance_chain,
    validate_provider_fetch_result,
    validate_provider_provenance,
    validate_snapshot_dict,
)

from tests.fixtures.data_service import (
    FAKE_PROVENANCE,
    make_full_snapshot,
    make_minimal_snapshot,
)


# ==========================================================================
# Import boundary
# ==========================================================================


class ValidatorImportBoundaryTests(unittest.TestCase):
    _PREDICTION_MODULES = (
        "oracle_core.engine", "oracle_core.scoring", "oracle_core.fitted",
        "oracle_core.knockout", "oracle_core.tournament", "oracle_core.odds",
    )

    def test_01_validator_does_not_import_prediction(self):
        import oracle_core.data_service_validator as mod
        source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for banned in self._PREDICTION_MODULES:
                        self.assertNotIn(banned, alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for banned in self._PREDICTION_MODULES:
                        self.assertNotIn(banned, node.module)

    def test_02_prediction_modules_do_not_import_validator(self):
        engine_root = pathlib.Path(__file__).parent.parent / "oracle_core"
        for mod_name in ("engine.py", "types.py", "knockout.py", "tournament.py",
                          "odds.py", "evaluation.py", "scoring.py", "fitted.py"):
            mp = engine_root / mod_name
            if not mp.exists():
                continue
            source = mp.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("data_service_validator", alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertNotIn("data_service_validator", node.module)


# ==========================================================================
# ValidationReport + has_blocking_issues
# ==========================================================================


class ValidationReportTests(unittest.TestCase):
    def test_01_empty_report(self):
        r = ValidationReport(subject_id="t", subject_type="T")
        self.assertFalse(r.has_blocking)
        self.assertFalse(r.has_errors)

    def test_02_blocking_detected(self):
        r = ValidationReport(subject_id="t", subject_type="T",
            issues=(DataQualityIssue(severity=DataQualitySeverity.BLOCKING, code="B", message="b"),))
        self.assertTrue(r.has_blocking)
        self.assertTrue(r.has_errors)
        self.assertEqual(r.blocking_count, 1)

    def test_03_warning_not_blocking(self):
        r = ValidationReport(subject_id="t", subject_type="T",
            issues=(DataQualityIssue(severity=DataQualitySeverity.WARNING, code="W", message="w"),))
        self.assertFalse(r.has_blocking)
        self.assertEqual(r.warning_count, 1)

    def test_04_by_severity(self):
        r = ValidationReport(subject_id="t", subject_type="T", issues=(
            DataQualityIssue(severity=DataQualitySeverity.WARNING, code="W1", message="w1"),
            DataQualityIssue(severity=DataQualitySeverity.WARNING, code="W2", message="w2"),
            DataQualityIssue(severity=DataQualitySeverity.ERROR, code="E1", message="e1"),
        ))
        self.assertEqual(len(r.by_severity(DataQualitySeverity.WARNING)), 2)

    def test_05_to_dict(self):
        r = ValidationReport(subject_id="t", subject_type="T", issues=(
            DataQualityIssue(severity=DataQualitySeverity.INFO, code="I", message="i"),
            DataQualityIssue(severity=DataQualitySeverity.BLOCKING, code="B", message="b"),
        ))
        d = r.to_dict()
        self.assertEqual(d["counts"]["total"], 2)
        self.assertTrue(d["has_blocking"])

    def test_06_has_blocking_issues_helper(self):
        issues = (
            DataQualityIssue(severity=DataQualitySeverity.WARNING, code="W", message="w"),
        )
        self.assertFalse(has_blocking_issues(issues))
        issues2 = (
            DataQualityIssue(severity=DataQualitySeverity.BLOCKING, code="B", message="b"),
        )
        self.assertTrue(has_blocking_issues(issues2))


# ==========================================================================
# Provider provenance validation
# ==========================================================================


class ProviderProvenanceValidationTests(unittest.TestCase):
    _VALID_PROV = {
        "provider_name": "fake_provider_v1",
        "adapter_version": "1.0.0",
        "fetched_at": "2026-06-15T12:00:00+00:00",
        "source_reference": "fixture://test",
        "raw_payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    }

    def test_01_valid_no_blocking(self):
        issues = validate_provider_provenance(self._VALID_PROV)
        self.assertFalse(has_blocking_issues(issues))

    def test_02_provider_name_missing_blocking(self):
        d = dict(self._VALID_PROV, provider_name="")
        issues = validate_provider_provenance(d)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(i.code == "PROV_PROVIDER_NAME_MISSING" for i in issues))

    def test_03_fetched_at_naive_blocking(self):
        d = dict(self._VALID_PROV, fetched_at="2026-06-15T12:00:00")
        issues = validate_provider_provenance(d)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(i.code == "PROV_FETCHED_AT_NAIVE" for i in issues))

    def test_04_fetched_at_unparseable_blocking(self):
        d = dict(self._VALID_PROV, fetched_at="not-a-date")
        issues = validate_provider_provenance(d)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(i.code == "PROV_FETCHED_AT_INVALID" for i in issues))

    def test_05_raw_hash_invalid_blocking(self):
        d = dict(self._VALID_PROV, raw_payload_hash="abc123")
        issues = validate_provider_provenance(d)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(i.code == "PROV_RAW_HASH_INVALID" for i in issues))

    def test_06_raw_hash_missing_blocking(self):
        d = dict(self._VALID_PROV, raw_payload_hash="")
        issues = validate_provider_provenance(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_07_source_reference_missing_blocking(self):
        d = dict(self._VALID_PROV, source_reference="")
        issues = validate_provider_provenance(d)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(i.code == "PROV_SOURCE_REFERENCE_MISSING" for i in issues))

    def test_08_adapter_version_missing_blocking(self):
        d = dict(self._VALID_PROV, adapter_version="")
        issues = validate_provider_provenance(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_09_fetched_at_missing_none_blocking(self):
        d = dict(self._VALID_PROV, fetched_at=None)
        issues = validate_provider_provenance(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_10_dataclass_provenance_valid(self):
        issues = validate_provider_provenance(FAKE_PROVENANCE)
        self.assertFalse(has_blocking_issues(issues))


# ==========================================================================
# Provider fetch result validation
# ==========================================================================


class ProviderFetchResultValidationTests(unittest.TestCase):
    def _valid_result_dict(self):
        from oracle_core.data_service_providers import DeterministicFakeProvider
        return DeterministicFakeProvider().fetch_teams().to_dict()

    def test_01_valid_fake_result_no_blocking(self):
        d = self._valid_result_dict()
        issues = validate_provider_fetch_result(d)
        self.assertFalse(has_blocking_issues(issues))

    def test_02_provider_name_missing_blocking(self):
        d = self._valid_result_dict()
        d["provider_name"] = ""
        issues = validate_provider_fetch_result(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_03_raw_hash_invalid_blocking(self):
        d = self._valid_result_dict()
        d["raw_payload_hash"] = "bad"
        issues = validate_provider_fetch_result(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_04_source_reference_missing_blocking(self):
        d = self._valid_result_dict()
        d["source_reference"] = ""
        issues = validate_provider_fetch_result(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_05_capability_missing_blocking(self):
        d = self._valid_result_dict()
        d["capability"] = ""
        issues = validate_provider_fetch_result(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_06_fetched_at_naive_blocking(self):
        d = self._valid_result_dict()
        d["fetched_at"] = "2026-06-15T12:00:00"
        issues = validate_provider_fetch_result(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_07_completeness_empty_warning(self):
        d = self._valid_result_dict()
        d["completeness"] = {}
        issues = validate_provider_fetch_result(d)
        self.assertTrue(any(
            i.code == "RESULT_COMPLETENESS_EMPTY" for i in issues))

    def test_08_warnings_present_info(self):
        d = self._valid_result_dict()
        d["warnings"] = ["test_warning"]
        issues = validate_provider_fetch_result(d)
        self.assertTrue(any(i.code == "RESULT_HAS_WARNINGS" for i in issues))

    def test_09_payload_contains_expected_goals_blocking(self):
        d = self._valid_result_dict()
        d["payload"] = {"expected_goals": [1.5, 0.8]}
        issues = validate_provider_fetch_result(d)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(
            "MODEL_BOUNDARY_FORBIDDEN_MODEL_OUTPUT" in i.code for i in issues))

    def test_10_payload_contains_result_probabilities_blocking(self):
        d = self._valid_result_dict()
        d["payload"] = {"data": {"result_probabilities": {"home": 0.5}}}
        issues = validate_provider_fetch_result(d)
        self.assertTrue(has_blocking_issues(issues))


# ==========================================================================
# Canonical team validation
# ==========================================================================


class CanonicalTeamValidationTests(unittest.TestCase):
    _VALID_TEAM = {
        "team_id": "FIC-ALPHA",
        "display_name": "Fictional Alpha FC",
        "country_code": "FIC",
        "provenance_refs": [{"provider_name": "fake_provider_v1"}],
        "data_quality": [],
    }

    def test_01_valid_no_blocking(self):
        issues = validate_canonical_team(self._VALID_TEAM)
        self.assertFalse(has_blocking_issues(issues))

    def test_02_team_id_missing_blocking(self):
        d = dict(self._VALID_TEAM, team_id="")
        issues = validate_canonical_team(d)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(i.code == "TEAM_ID_MISSING" for i in issues))

    def test_03_display_name_missing_blocking(self):
        d = dict(self._VALID_TEAM, display_name="")
        issues = validate_canonical_team(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_04_provenance_refs_empty_blocking(self):
        d = dict(self._VALID_TEAM, provenance_refs=[])
        issues = validate_canonical_team(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_05_data_quality_has_blocking(self):
        d = dict(self._VALID_TEAM, data_quality=[
            {"severity": "blocking", "code": "X", "message": "prior issue"},
        ])
        issues = validate_canonical_team(d)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(i.code == "TEAM_HAS_BLOCKING_DQ" for i in issues))

    def test_06_country_code_missing_info(self):
        d = dict(self._VALID_TEAM, country_code=None)
        issues = validate_canonical_team(d)
        self.assertTrue(any(
            i.severity == DataQualitySeverity.INFO and
            i.code == "TEAM_COUNTRY_CODE_MISSING" for i in issues))

    def test_07_dataclass_team_valid(self):
        from tests.fixtures.data_service import FICTIONAL_TEAM_ALPHA
        issues = validate_canonical_team(FICTIONAL_TEAM_ALPHA)
        self.assertFalse(has_blocking_issues(issues))


# ==========================================================================
# Canonical match validation
# ==========================================================================


class CanonicalMatchValidationTests(unittest.TestCase):
    _VALID_MATCH = {
        "match_id": "FIC-001",
        "team_a_id": "FIC-ALPHA",
        "team_b_id": "FIC-BETA",
        "kickoff_at": "2026-06-16T20:00:00+00:00",
        "stage": "group",
        "group": "Fictional Group A",
        "venue": "Fictional Stadium",
        "neutral_site": True,
        "provenance_refs": [{"provider_name": "fake_provider_v1"}],
        "data_quality": [],
    }

    def test_01_valid_no_blocking(self):
        issues = validate_canonical_match(self._VALID_MATCH)
        self.assertFalse(has_blocking_issues(issues))

    def test_02_match_id_missing_blocking(self):
        d = dict(self._VALID_MATCH, match_id="")
        issues = validate_canonical_match(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_03_same_team_blocking(self):
        d = dict(self._VALID_MATCH, team_a_id="FIC-ALPHA", team_b_id="FIC-ALPHA")
        issues = validate_canonical_match(d)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(i.code == "MATCH_SAME_TEAM" for i in issues))

    def test_04_naive_kickoff_blocking(self):
        d = dict(self._VALID_MATCH, kickoff_at="2026-06-16T20:00:00")
        issues = validate_canonical_match(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_05_kickoff_missing_blocking(self):
        d = dict(self._VALID_MATCH, kickoff_at=None)
        issues = validate_canonical_match(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_06_provenance_empty_blocking(self):
        d = dict(self._VALID_MATCH, provenance_refs=[])
        issues = validate_canonical_match(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_07_data_quality_blocking_propagated(self):
        d = dict(self._VALID_MATCH, data_quality=[
            {"severity": "blocking", "code": "X", "message": "prior"},
        ])
        issues = validate_canonical_match(d)
        self.assertTrue(has_blocking_issues(issues))

    def test_08_stage_missing_error(self):
        d = dict(self._VALID_MATCH, stage="")
        issues = validate_canonical_match(d)
        self.assertTrue(any(
            i.severity == DataQualitySeverity.ERROR and
            i.code == "MATCH_STAGE_MISSING" for i in issues))

    def test_09_venue_missing_info(self):
        d = dict(self._VALID_MATCH, venue=None)
        issues = validate_canonical_match(d)
        self.assertTrue(any(
            i.severity == DataQualitySeverity.INFO and
            i.code == "MATCH_VENUE_MISSING" for i in issues))

    def test_10_group_stage_missing_group_warning(self):
        d = dict(self._VALID_MATCH, stage="group", group=None)
        issues = validate_canonical_match(d)
        self.assertTrue(any(
            i.code == "MATCH_GROUP_MISSING" for i in issues))

    def test_11_knockout_missing_round_name_warning(self):
        d = dict(self._VALID_MATCH, stage="QF", round_name=None)
        issues = validate_canonical_match(d)
        self.assertTrue(any(
            i.code == "MATCH_ROUND_NAME_MISSING" for i in issues))

    def test_12_dataclass_match_valid(self):
        from tests.fixtures.data_service import FICTIONAL_MATCH_ALPHA_BETA
        issues = validate_canonical_match(FICTIONAL_MATCH_ALPHA_BETA)
        self.assertFalse(has_blocking_issues(issues))


# ==========================================================================
# MatchContextSnapshot / snapshot dict validation
# ==========================================================================


class SnapshotDictValidationTests(unittest.TestCase):
    def test_01_valid_minimal_no_blocking(self):
        snap = make_minimal_snapshot().to_dict()
        report = validate_snapshot_dict(snap)
        self.assertFalse(report.has_blocking)

    def test_02_valid_full_no_blocking(self):
        snap = make_full_snapshot().to_dict()
        report = validate_snapshot_dict(snap)
        self.assertFalse(report.has_blocking)

    def test_03_missing_match_id_blocking(self):
        snap = make_minimal_snapshot().to_dict()
        snap["match"]["match_id"] = None
        report = validate_snapshot_dict(snap)
        self.assertTrue(report.has_blocking)

    def test_04_missing_kickoff_blocking(self):
        snap = make_minimal_snapshot().to_dict()
        snap["match"]["kickoff_at"] = None
        report = validate_snapshot_dict(snap)
        self.assertTrue(report.has_blocking)

    def test_05_missing_team_blocking(self):
        snap = make_minimal_snapshot().to_dict()
        snap["team_a"] = None
        report = validate_snapshot_dict(snap)
        self.assertTrue(report.has_blocking)

    def test_06_knockout_missing_bracket_default_warning(self):
        """Knockout missing bracket → WARNING by default (not blocking)."""
        snap = make_minimal_snapshot().to_dict()
        snap["match"]["stage"] = "QF"
        snap["knockout_context"] = None
        report = validate_snapshot_dict(snap)
        ko_issues = [i for i in report.issues if i.code == "KNOCKOUT_MISSING_BRACKET"]
        self.assertTrue(ko_issues)
        self.assertEqual(ko_issues[0].severity, DataQualitySeverity.WARNING)

    def test_07_knockout_missing_bracket_strict_blocking(self):
        """With require_bracket=True → BLOCKING."""
        issues = _check_knockout_missing_bracket(
            {"match": {"stage": "QF"}, "knockout_context": None},
            require_bracket=True,
        )
        self.assertTrue(has_blocking_issues(issues))


# ==========================================================================
# Forbidden model output key checks
# ==========================================================================


class ForbiddenModelKeysTests(unittest.TestCase):
    def test_01_nested_result_probabilities_blocking(self):
        snap = make_minimal_snapshot().to_dict()
        snap["result_probabilities"] = {"team_a_win": 0.5}
        report = validate_snapshot_dict(snap)
        self.assertTrue(report.has_blocking)
        self.assertTrue(any(
            "FORBIDDEN_MODEL_OUTPUT" in i.code for i in report.issues))

    def test_02_nested_expected_goals_blocking(self):
        snap = make_minimal_snapshot().to_dict()
        snap["extra"] = {"nested": {"expected_goals": [1.0, 0.5]}}
        report = validate_snapshot_dict(snap)
        self.assertTrue(report.has_blocking)

    def test_03_nested_advancement_probabilities_blocking(self):
        snap = make_minimal_snapshot().to_dict()
        snap["context"] = {"advancement_probabilities": {"team_a": 0.7}}
        report = validate_snapshot_dict(snap)
        self.assertTrue(report.has_blocking)

    def test_04_model_probability_blocking(self):
        snap = make_minimal_snapshot().to_dict()
        snap["model_probabilities"] = [0.3, 0.3, 0.4]
        report = validate_snapshot_dict(snap)
        self.assertTrue(report.has_blocking)

    def test_05_prediction_key_blocking(self):
        snap = make_minimal_snapshot().to_dict()
        snap["prediction"] = {"score": "2-1"}
        report = validate_snapshot_dict(snap)
        self.assertTrue(report.has_blocking)

    def test_06_deeply_nested_forbidden_key(self):
        data = {"level1": {"level2": [{"level3": {"top_scores": [{"s": [2,0], "p": 0.5}]}}]}}
        issues = _scan_forbidden_model_keys(data)
        self.assertTrue(has_blocking_issues(issues))

    def test_07_valid_snapshot_no_forbidden_keys(self):
        snap = make_full_snapshot().to_dict()
        issues = _scan_forbidden_model_keys(snap)
        self.assertEqual(issues, [])


# ==========================================================================
# Model boundary report_only checks
# ==========================================================================


class ModelBoundaryReportOnlyTests(unittest.TestCase):
    def test_01_full_snapshot_report_only_pass(self):
        snap = make_full_snapshot().to_dict()
        issues = _check_context_report_only(snap)
        self.assertEqual(issues, [])

    def test_02_odds_report_only_false_model_boundary_issue(self):
        snap = make_full_snapshot().to_dict()
        snap["odds_context"]["report_only"] = False
        issues = _check_context_report_only(snap)
        self.assertTrue(has_blocking_issues(issues))
        self.assertTrue(any(
            "CONTEXT_NOT_REPORT_ONLY" in i.code for i in issues))

    def test_03_lineup_report_only_false_model_boundary(self):
        snap = make_full_snapshot().to_dict()
        snap["lineup_context"][0]["report_only"] = False
        issues = _check_context_report_only(snap)
        self.assertTrue(has_blocking_issues(issues))

    def test_04_injury_report_only_false_model_boundary(self):
        snap = make_full_snapshot().to_dict()
        snap["injury_context"][0]["report_only"] = False
        issues = _check_context_report_only(snap)
        self.assertTrue(has_blocking_issues(issues))

    def test_05_suspension_report_only_false_model_boundary(self):
        snap = make_full_snapshot().to_dict()
        snap["suspension_context"][0]["report_only"] = False
        issues = _check_context_report_only(snap)
        self.assertTrue(has_blocking_issues(issues))

    def test_06_signal_report_only_false_model_boundary(self):
        snap = make_full_snapshot().to_dict()
        snap["prematch_signals"][0]["report_only"] = False
        issues = _check_context_report_only(snap)
        self.assertTrue(has_blocking_issues(issues))

    def test_07_missing_report_only_flag_error(self):
        snap = make_minimal_snapshot().to_dict()
        snap["odds_context"] = {"market_type": "1X2"}
        issues = _check_context_report_only(snap)
        self.assertTrue(any(
            i.severity == DataQualitySeverity.ERROR for i in issues))

    def test_08_missing_context_fields_not_blocking(self):
        """Missing odds/lineup/injury/suspension/signals is not a boundary issue."""
        snap = make_minimal_snapshot().to_dict()
        report = validate_snapshot_dict(snap)
        self.assertFalse(report.has_blocking)


# ==========================================================================
# Stale lineup malformed timestamp behavior
# ==========================================================================


class StaleLineupTimestampTests(unittest.TestCase):
    def test_01_invalid_last_updated_produces_warning(self):
        """Malformed last_updated no longer silently skipped."""
        snap = make_minimal_snapshot().to_dict()
        snap["match"]["kickoff_at"] = "2026-06-16T20:00:00+00:00"
        snap["lineup_context"] = [{
            "team_id": "FIC-ALPHA",
            "last_updated": "not-a-valid-date",
        }]
        issues = _check_stale_lineup(snap)
        self.assertTrue(issues)
        self.assertTrue(any(
            "LAST_UPDATED_INVALID" in i.code or "LAST_UPDATED_NAIVE" in i.code
            for i in issues))

    def test_02_naive_last_updated_warning(self):
        snap = make_minimal_snapshot().to_dict()
        snap["match"]["kickoff_at"] = "2026-06-16T20:00:00+00:00"
        snap["lineup_context"] = [{
            "team_id": "FIC-ALPHA",
            "last_updated": "2026-06-15T10:00:00",
        }]
        issues = _check_stale_lineup(snap)
        self.assertTrue(any(
            i.code == "LINEUP_LAST_UPDATED_NAIVE" for i in issues))

    def test_03_non_string_last_updated_warning(self):
        snap = make_minimal_snapshot().to_dict()
        snap["match"]["kickoff_at"] = "2026-06-16T20:00:00+00:00"
        snap["lineup_context"] = [{"team_id": "FIC-ALPHA", "last_updated": 42}]
        issues = _check_stale_lineup(snap)
        self.assertTrue(any(
            i.code == "LINEUP_LAST_UPDATED_INVALID" for i in issues))

    def test_04_missing_last_updated_no_issue(self):
        snap = make_minimal_snapshot().to_dict()
        snap["match"]["kickoff_at"] = "2026-06-16T20:00:00+00:00"
        snap["lineup_context"] = [{"team_id": "FIC-ALPHA"}]
        issues = _check_stale_lineup(snap)
        # Missing last_updated is skipped (not an error per design)
        self.assertFalse(any(
            "LAST_UPDATED" in i.code for i in issues))


# ==========================================================================
# validate_match_context_snapshot (dataclass input)
# ==========================================================================


class MatchContextSnapshotValidationTests(unittest.TestCase):
    def test_01_dataclass_minimal_no_blocking(self):
        snap = make_minimal_snapshot()
        report = validate_match_context_snapshot(snap)
        self.assertFalse(report.has_blocking)

    def test_02_dataclass_full_no_blocking(self):
        snap = make_full_snapshot()
        report = validate_match_context_snapshot(snap)
        self.assertFalse(report.has_blocking)

    def test_03_dict_input_same_as_dataclass(self):
        snap = make_full_snapshot()
        report_dc = validate_match_context_snapshot(snap)
        report_dict = validate_match_context_snapshot(snap.to_dict())
        self.assertEqual(report_dc.blocking_count, report_dict.blocking_count)
        self.assertEqual(report_dc.warning_count, report_dict.warning_count)


# ==========================================================================
# Provenance chain
# ==========================================================================


class ProvenanceChainTests(unittest.TestCase):
    def test_01_matching_chain_ok(self):
        raw = {"provider_name": "p", "raw_payload_hash": "a" * 64}
        snap = make_minimal_snapshot().to_dict()
        snap["provenance_refs"] = [{"raw_payload_hash": "a" * 64}]
        report = validate_provenance_chain(raw, snap)
        self.assertFalse(report.has_errors)

    def test_02_broken_chain_error(self):
        raw = {"provider_name": "p", "raw_payload_hash": "a" * 64}
        snap = make_minimal_snapshot().to_dict()
        snap["provenance_refs"] = [{"raw_payload_hash": "b" * 64}]
        report = validate_provenance_chain(raw, snap)
        self.assertTrue(any(i.code == "PROVENANCE_CHAIN_BROKEN" for i in report.issues))

    def test_03_raw_missing_hash(self):
        raw = {"provider_name": "p"}
        snap = make_minimal_snapshot().to_dict()
        report = validate_provenance_chain(raw, snap)
        self.assertTrue(any(i.code == "RAW_MISSING_HASH" for i in report.issues))

    def test_04_snapshot_no_provenance(self):
        raw = {"provider_name": "p", "raw_payload_hash": "a" * 64}
        snap = make_minimal_snapshot().to_dict()
        snap["provenance_refs"] = []
        report = validate_provenance_chain(raw, snap)
        self.assertTrue(any(i.code == "SNAPSHOT_NO_PROVENANCE" for i in report.issues))


# ==========================================================================
# Immutability
# ==========================================================================


class ValidatorImmutabilityTests(unittest.TestCase):
    def test_01_snapshot_dict_not_modified(self):
        snap = make_full_snapshot().to_dict()
        import copy
        orig = copy.deepcopy(snap)
        validate_snapshot_dict(snap)
        self.assertEqual(snap, orig)

    def test_02_provider_result_not_modified(self):
        from oracle_core.data_service_providers import DeterministicFakeProvider
        d = DeterministicFakeProvider().fetch_teams().to_dict()
        import copy
        orig = copy.deepcopy(d)
        validate_provider_fetch_result(d)
        self.assertEqual(d, orig)


if __name__ == "__main__":
    unittest.main()
