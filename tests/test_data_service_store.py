"""Tests for Data Service v1 local store + snapshot writer/reader (Patch 16).

All tests use temporary directories.  No real data.  No network.
No prediction integration.  No skipped tests.
"""

from __future__ import annotations

import ast
import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from oracle_core.data_service_providers import DeterministicFakeProvider
from oracle_core.data_service_store import (
    DataServiceLocalStore,
    DataServiceStoreError,
    InvalidStorePayloadError,
    RawFetchResultNotFoundError,
    SnapshotAlreadyExistsError,
    SnapshotNotFoundError,
    _canonicalize_store_dict,
    _datetime_to_iso,
    _ensure_under_root,
    _json_safe,
    _parse_iso,
    _read_json,
    _validate_capability_segment,
    _validate_path_segment,
    _validate_raw_payload_hash,
    _write_json,
)

from tests.fixtures.data_service import (
    FAKE_PROVENANCE,
    FICTIONAL_MATCH_ALPHA_BETA,
    FICTIONAL_ODDS,
    FICTIONAL_TEAM_ALPHA,
    FICTIONAL_TEAM_BETA,
    FIXED_NOW,
    make_full_snapshot,
    make_minimal_snapshot,
)


# ==========================================================================
# Import boundary
# ==========================================================================


class StoreImportBoundaryTests(unittest.TestCase):
    """data_service_store must not import prediction engine modules."""

    _PREDICTION_MODULES = (
        "oracle_core.engine",
        "oracle_core.scoring",
        "oracle_core.fitted",
        "oracle_core.knockout",
        "oracle_core.tournament",
        "oracle_core.odds",
    )

    def test_01_store_module_does_not_import_prediction(self):
        import oracle_core.data_service_store as mod

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

    def test_02_prediction_modules_do_not_import_store(self):
        engine_root = pathlib.Path(__file__).parent.parent / "oracle_core"
        modules_to_check = [
            "engine.py", "types.py", "knockout.py", "tournament.py",
            "odds.py", "evaluation.py", "scoring.py", "fitted.py",
        ]
        for mod_name in modules_to_check:
            mod_path = engine_root / mod_name
            if not mod_path.exists():
                continue
            source = mod_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("data_service_store", alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertNotIn("data_service_store", node.module)


# ==========================================================================
# Serialization helpers
# ==========================================================================


class SerializationHelperTests(unittest.TestCase):
    """_datetime_to_iso, _parse_iso, _json_safe, _canonicalize_store_dict."""

    def test_01_datetime_to_iso_utc(self):
        dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        iso = _datetime_to_iso(dt)
        self.assertIn("2026-06-15", iso)
        self.assertIn("12:00:00", iso)

    def test_02_datetime_to_iso_rejects_non_datetime(self):
        with self.assertRaises(InvalidStorePayloadError):
            _datetime_to_iso("not a datetime")

    def test_03_datetime_to_iso_rejects_naive(self):
        with self.assertRaises(InvalidStorePayloadError):
            _datetime_to_iso(datetime(2026, 6, 15, 12, 0, 0))

    def test_04_parse_iso_roundtrip(self):
        dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        iso = _datetime_to_iso(dt)
        parsed = _parse_iso(iso)
        self.assertEqual(parsed, dt)

    def test_05_parse_iso_naive_becomes_utc(self):
        parsed = _parse_iso("2026-06-15T12:00:00")
        self.assertIsNotNone(parsed.tzinfo)

    def test_06_json_safe_allows_primitives(self):
        _json_safe(None)
        _json_safe(True)
        _json_safe(42)
        _json_safe(3.14)
        _json_safe("hello")

    def test_07_json_safe_allows_lists_and_dicts(self):
        _json_safe([1, "two", 3.0])
        _json_safe({"a": 1, "b": [2, 3]})

    def test_08_json_safe_rejects_datetime(self):
        dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        with self.assertRaises(InvalidStorePayloadError):
            _json_safe({"ts": dt})

    def test_09_json_safe_rejects_bytes(self):
        with self.assertRaises(InvalidStorePayloadError):
            _json_safe({"data": b"binary"})

    def test_10_json_safe_rejects_set(self):
        with self.assertRaises(InvalidStorePayloadError):
            _json_safe({1, 2, 3})

    def test_11_json_safe_rejects_non_string_dict_key(self):
        with self.assertRaises(InvalidStorePayloadError):
            _json_safe({42: "value"})


# ==========================================================================
# Raw fetch result persistence
# ==========================================================================


class RawFetchResultStoreTests(unittest.TestCase):
    """write_raw_fetch_result / read_raw_fetch_result / list_raw_fetch_results."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))
        self.provider = DeterministicFakeProvider()

    def tearDown(self):
        self.temp.cleanup()

    def test_01_write_returns_path(self):
        result = self.provider.fetch_teams()
        path = self.store.write_raw_fetch_result(result)
        self.assertTrue(path.exists())
        self.assertIn("raw", str(path))
        self.assertIn("fake_provider_v1", str(path))

    def test_02_write_then_read_roundtrip(self):
        result = self.provider.fetch_teams()
        path = self.store.write_raw_fetch_result(result)
        data = self.store.read_raw_fetch_result(
            provider_name="fake_provider_v1",
            capability="teams",
            raw_payload_hash=result.raw_payload_hash,
        )
        self.assertEqual(data["provider_name"], "fake_provider_v1")
        self.assertEqual(data["capability"], "teams")
        self.assertEqual(data["raw_payload_hash"], result.raw_payload_hash)

    def test_03_read_nonexistent_raises(self):
        with self.assertRaises(RawFetchResultNotFoundError):
            self.store.read_raw_fetch_result(
                provider_name="nonexistent",
                capability="teams",
                raw_payload_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )

    def test_04_provenance_fields_in_json(self):
        result = self.provider.fetch_matches()
        self.store.write_raw_fetch_result(result)
        data = self.store.read_raw_fetch_result(
            "fake_provider_v1", "matches", result.raw_payload_hash,
        )
        self.assertIn("provider_name", data)
        self.assertIn("adapter_version", data)
        self.assertIn("fetched_at", data)
        self.assertIn("source_reference", data)
        self.assertIn("raw_payload_hash", data)

    def test_05_source_reference_uses_fixture(self):
        """Raw result JSON must use fixture:// not http(s):// source."""
        result = self.provider.fetch_odds()
        self.store.write_raw_fetch_result(result)
        data = self.store.read_raw_fetch_result(
            "fake_provider_v1", "odds", result.raw_payload_hash,
        )
        self.assertTrue(data["source_reference"].startswith("fixture://"))

    def test_06_no_model_output_keys_in_raw_json(self):
        """Raw fetch result JSON must not contain prediction engine keys as dict keys."""
        banned = (
            "result_probabilities", "expected_goals", "top_scores",
            "over_under", "advancement_probabilities",
        )
        def _check_keys(obj, path: str = "$"):
            if isinstance(obj, dict):
                for key in obj:
                    self.assertNotIn(key, banned,
                                     f"Raw JSON key '{key}' at {path} is a banned model output key")
                    _check_keys(obj[key], f"{path}.{key}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _check_keys(item, f"{path}[{i}]")

        # Test all 9 capabilities
        for method_name in [
            "fetch_teams", "fetch_matches", "fetch_group_standings",
            "fetch_knockout_bracket", "fetch_odds", "fetch_lineups",
            "fetch_injuries", "fetch_suspensions", "fetch_prematch_signals",
        ]:
            result = getattr(self.provider, method_name)()
            path = self.store.write_raw_fetch_result(result)
            raw_data = json.loads(path.read_text(encoding="utf-8"))
            _check_keys(raw_data)

    def test_07_payload_preserved_in_roundtrip(self):
        result = self.provider.fetch_teams()
        self.store.write_raw_fetch_result(result)
        data = self.store.read_raw_fetch_result(
            "fake_provider_v1", "teams", result.raw_payload_hash,
        )
        self.assertIn("teams", data["payload"])
        self.assertEqual(len(data["payload"]["teams"]), 4)

    def test_08_list_empty_store(self):
        results = self.store.list_raw_fetch_results()
        self.assertEqual(results, [])

    def test_09_list_all_results(self):
        self.store.write_raw_fetch_result(self.provider.fetch_teams())
        self.store.write_raw_fetch_result(self.provider.fetch_matches())
        results = self.store.list_raw_fetch_results()
        self.assertEqual(len(results), 2)

    def test_10_list_filter_by_provider(self):
        self.store.write_raw_fetch_result(self.provider.fetch_teams())
        results = self.store.list_raw_fetch_results(provider_name="fake_provider_v1")
        self.assertEqual(len(results), 1)
        results_empty = self.store.list_raw_fetch_results(provider_name="other")
        self.assertEqual(results_empty, [])

    def test_11_list_filter_by_capability(self):
        self.store.write_raw_fetch_result(self.provider.fetch_teams())
        self.store.write_raw_fetch_result(self.provider.fetch_odds())
        results = self.store.list_raw_fetch_results(capability="teams")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["capability"], "teams")

    def test_12_list_metadata_keys(self):
        self.store.write_raw_fetch_result(self.provider.fetch_teams())
        results = self.store.list_raw_fetch_results()
        entry = results[0]
        for key in ("provider_name", "capability", "raw_payload_hash", "path"):
            self.assertIn(key, entry)

    def test_13_list_results_sorted(self):
        """Results should be in deterministic (sorted) order."""
        self.store.write_raw_fetch_result(self.provider.fetch_odds())
        self.store.write_raw_fetch_result(self.provider.fetch_teams())
        results = self.store.list_raw_fetch_results()
        # 'odds' sorts before 'teams' alphabetically
        self.assertEqual(results[0]["capability"], "odds")
        self.assertEqual(results[1]["capability"], "teams")


# ==========================================================================
# MatchContextSnapshot writer / reader
# ==========================================================================


class SnapshotStoreTests(unittest.TestCase):
    """write/read/list/latest MatchContextSnapshot."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    # ── Basic write / read ──

    def test_01_write_minimal_snapshot(self):
        snap = make_minimal_snapshot()
        path = self.store.write_match_context_snapshot(snap)
        self.assertTrue(path.exists())
        self.assertIn("snapshots", str(path))
        self.assertIn("match_context", str(path))
        self.assertIn(snap.snapshot_id, str(path))

    def test_02_write_then_read_minimal_snapshot(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        data = self.store.read_match_context_snapshot(
            snap.match.match_id, snap.snapshot_id,
        )
        self.assertEqual(data["snapshot_id"], snap.snapshot_id)
        self.assertEqual(data["snapshot_version"], "1.0.0")
        self.assertEqual(data["match"]["match_id"], "FIC-001")

    def test_03_write_then_read_full_snapshot(self):
        snap = make_full_snapshot()
        self.store.write_match_context_snapshot(snap)
        data = self.store.read_match_context_snapshot(
            snap.match.match_id, snap.snapshot_id,
        )
        self.assertEqual(data["snapshot_id"], "FIC-SNAP-FULL-001")

    # ── Field integrity ──

    def test_04_snapshot_id_preserved(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        data = self.store.read_match_context_snapshot(
            "FIC-001", "FIC-SNAP-MINIMAL-001",
        )
        self.assertEqual(data["snapshot_id"], "FIC-SNAP-MINIMAL-001")

    def test_05_snapshot_version_preserved(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        data = self.store.read_match_context_snapshot(
            "FIC-001", "FIC-SNAP-MINIMAL-001",
        )
        self.assertEqual(data["snapshot_version"], "1.0.0")

    def test_06_snapshot_created_at_preserved(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        data = self.store.read_match_context_snapshot(
            "FIC-001", "FIC-SNAP-MINIMAL-001",
        )
        self.assertIn("snapshot_created_at", data)
        # Should be an ISO string
        self.assertIsInstance(data["snapshot_created_at"], str)

    def test_07_match_identity_fields_preserved(self):
        snap = make_full_snapshot()
        self.store.write_match_context_snapshot(snap)
        data = self.store.read_match_context_snapshot(
            "FIC-001", "FIC-SNAP-FULL-001",
        )
        self.assertEqual(data["match"]["match_id"], "FIC-001")
        self.assertEqual(data["match"]["team_a_id"], "FIC-ALPHA")
        self.assertEqual(data["match"]["team_b_id"], "FIC-BETA")

    # ── Immutability — no overwrite ──

    def test_08_duplicate_write_raises(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        with self.assertRaises(SnapshotAlreadyExistsError):
            self.store.write_match_context_snapshot(snap)

    def test_09_duplicate_write_preserves_original(self):
        """After duplicate error, original snapshot data is intact."""
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        try:
            # Create a different snapshot with same IDs (simulate collision)
            import copy
            snap2 = make_minimal_snapshot()
            self.store.write_match_context_snapshot(snap2)
        except SnapshotAlreadyExistsError:
            pass
        data = self.store.read_match_context_snapshot(
            "FIC-001", "FIC-SNAP-MINIMAL-001",
        )
        self.assertEqual(data["snapshot_id"], "FIC-SNAP-MINIMAL-001")

    # ── List ──

    def test_10_list_empty_for_nonexistent_match(self):
        results = self.store.list_match_context_snapshots("NONEXISTENT")
        self.assertEqual(results, [])

    def test_11_list_single_snapshot(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        results = self.store.list_match_context_snapshots("FIC-001")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["snapshot_id"], "FIC-SNAP-MINIMAL-001")

    def test_12_list_multiple_snapshots_sorted_by_created_at(self):
        """Multiple snapshots for same match are sorted by created_at."""
        snap1 = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap1)

        # Write a second snapshot with a slightly different ID to avoid collision
        from oracle_core.data_service_types import MatchContextSnapshot
        snap2 = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-MINIMAL-002",
            snapshot_version="1.0.0",
            snapshot_created_at=datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc),
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )
        self.store.write_match_context_snapshot(snap2)

        results = self.store.list_match_context_snapshots("FIC-001")
        self.assertEqual(len(results), 2)
        # snap1 created at FIXED_NOW (June 15), snap2 at June 16
        self.assertLess(
            results[0]["snapshot_created_at"],
            results[1]["snapshot_created_at"],
        )

    def test_13_list_metadata_keys(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        results = self.store.list_match_context_snapshots("FIC-001")
        entry = results[0]
        for key in ("snapshot_id", "snapshot_version", "snapshot_created_at", "match_id"):
            self.assertIn(key, entry)

    # ── Latest ──

    def test_14_latest_returns_none_for_nonexistent(self):
        result = self.store.latest_match_context_snapshot("NONEXISTENT")
        self.assertIsNone(result)

    def test_15_latest_returns_single_snapshot(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        latest = self.store.latest_match_context_snapshot("FIC-001")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["snapshot_id"], "FIC-SNAP-MINIMAL-001")

    def test_16_latest_returns_most_recent(self):
        snap1 = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap1)

        from oracle_core.data_service_types import MatchContextSnapshot
        snap2 = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-LATER-001",
            snapshot_version="1.0.0",
            snapshot_created_at=datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc),
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )
        self.store.write_match_context_snapshot(snap2)

        latest = self.store.latest_match_context_snapshot("FIC-001")
        self.assertEqual(latest["snapshot_id"], "FIC-SNAP-LATER-001")

    # ── Read nonexistent ──

    def test_17_read_nonexistent_snapshot_raises(self):
        with self.assertRaises(SnapshotNotFoundError):
            self.store.read_match_context_snapshot("FIC-001", "NONEXISTENT")


# ==========================================================================
# Snapshot content boundary — no model output keys
# ==========================================================================


class SnapshotModelOutputBoundaryTests(unittest.TestCase):
    """Snapshot JSON must not contain prediction engine output keys."""

    _BANNED = (
        "result_probabilities", "expected_goals", "top_scores",
        "over_under", "advancement_probabilities",
    )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_01_minimal_snapshot_json_no_model_keys(self):
        snap = make_minimal_snapshot()
        path = self.store.write_match_context_snapshot(snap)
        data = json.loads(path.read_text(encoding="utf-8"))
        self._assert_no_banned_keys(data, "$")

    def test_02_full_snapshot_json_no_model_keys(self):
        snap = make_full_snapshot()
        path = self.store.write_match_context_snapshot(snap)
        data = json.loads(path.read_text(encoding="utf-8"))
        self._assert_no_banned_keys(data, "$")

    def _assert_no_banned_keys(self, obj, path):
        if isinstance(obj, dict):
            for key in obj:
                self.assertNotIn(
                    key, self._BANNED,
                    f"Snapshot JSON key '{key}' at {path} is a banned model output key",
                )
                self._assert_no_banned_keys(obj[key], f"{path}.{key}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self._assert_no_banned_keys(item, f"{path}[{i}]")

    def test_03_full_snapshot_report_only_preserved(self):
        """odds/lineup/injury/suspension/signal fields keep report_only=true."""
        snap = make_full_snapshot()
        self.store.write_match_context_snapshot(snap)
        data = self.store.read_match_context_snapshot(
            "FIC-001", "FIC-SNAP-FULL-001",
        )
        # odds
        self.assertTrue(data["odds_context"]["report_only"])
        # lineups
        for lc in data["lineup_context"]:
            self.assertTrue(lc["report_only"])
        # injuries
        for ic in data["injury_context"]:
            self.assertTrue(ic["report_only"])
        # suspensions
        for sc in data["suspension_context"]:
            self.assertTrue(sc["report_only"])
        # prematch signals
        for ps in data["prematch_signals"]:
            self.assertTrue(ps["report_only"])


# ==========================================================================
# JSON serialization determinism
# ==========================================================================


class DeterministicJsonTests(unittest.TestCase):
    """Store writes deterministic JSON (sorted keys, stable output)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_01_write_same_snapshot_twice_different_ids(self):
        """Same content with different snapshot_id → same structure."""
        snap1 = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap1)

        from oracle_core.data_service_types import MatchContextSnapshot
        snap2 = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-ID2",
            snapshot_version="1.0.0",
            snapshot_created_at=FIXED_NOW,
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )
        self.store.write_match_context_snapshot(snap2)

        # Both files should be valid JSON
        for sid in ("FIC-SNAP-MINIMAL-001", "FIC-SNAP-ID2"):
            data = self.store.read_match_context_snapshot("FIC-001", sid)
            self.assertIsInstance(data, dict)

    def test_02_json_indent_is_2(self):
        snap = make_minimal_snapshot()
        path = self.store.write_match_context_snapshot(snap)
        raw = path.read_text(encoding="utf-8")
        self.assertIn('  "', raw)  # has indentation

    def test_03_write_json_then_read_json_helpers(self):
        """_write_json/_read_json roundtrip."""
        import tempfile as tf
        with tf.TemporaryDirectory() as td:
            p = Path(td) / "test.json"
            _write_json(p, {"a": 1, "b": [2, 3]})
            data = _read_json(p)
            self.assertEqual(data, {"a": 1, "b": [2, 3]})

    def test_04_canonicalize_handles_nested_datetime(self):
        """_canonicalize_store_dict converts nested datetimes."""
        from datetime import timezone as tz
        dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=tz.utc)
        data = {"meta": {"created": dt, "items": [{"ts": dt}]}}
        result = _canonicalize_store_dict(data)
        self.assertIsInstance(result["meta"]["created"], str)
        self.assertIsInstance(result["meta"]["items"][0]["ts"], str)


# ==========================================================================
# Replay isolation — no provider dependency
# ==========================================================================


class ReplayIsolationTests(unittest.TestCase):
    """Replay reads must not call the provider — store is self-contained."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_01_read_snapshot_without_provider(self):
        """Can read a snapshot without any provider instance in scope."""
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)

        # Create a fresh store with no provider reference
        store2 = DataServiceLocalStore(root_path=Path(self.temp.name))
        data = store2.read_match_context_snapshot("FIC-001", "FIC-SNAP-MINIMAL-001")
        self.assertEqual(data["snapshot_id"], "FIC-SNAP-MINIMAL-001")
        self.assertIsNotNone(data["match"])

    def test_02_latest_snapshot_without_provider(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)

        store2 = DataServiceLocalStore(root_path=Path(self.temp.name))
        latest = store2.latest_match_context_snapshot("FIC-001")
        self.assertIsNotNone(latest)

    def test_03_list_snapshots_without_provider(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)

        store2 = DataServiceLocalStore(root_path=Path(self.temp.name))
        results = store2.list_match_context_snapshots("FIC-001")
        self.assertEqual(len(results), 1)


# ==========================================================================
# Error hierarchy
# ==========================================================================


class StoreErrorTests(unittest.TestCase):
    """Store error types are proper exceptions."""

    def test_01_base_error_is_runtime_error(self):
        with self.assertRaises(RuntimeError):
            raise DataServiceStoreError("base")

    def test_02_snapshot_already_exists(self):
        err = SnapshotAlreadyExistsError("dup")
        self.assertIsInstance(err, DataServiceStoreError)
        self.assertIn("dup", str(err))

    def test_03_snapshot_not_found(self):
        err = SnapshotNotFoundError("missing")
        self.assertIsInstance(err, DataServiceStoreError)

    def test_04_raw_not_found(self):
        err = RawFetchResultNotFoundError("missing")
        self.assertIsInstance(err, DataServiceStoreError)

    def test_05_invalid_payload(self):
        err = InvalidStorePayloadError("bad type")
        self.assertIsInstance(err, DataServiceStoreError)


# ==========================================================================
# Patch 16.1 — Path segment validation
# ==========================================================================


class PathSegmentValidationTests(unittest.TestCase):
    """_validate_path_segment rejects dangerous inputs."""

    # ── Valid segments ──

    def test_01_valid_simple(self):
        self.assertEqual(_validate_path_segment("hello", "test"), "hello")

    def test_02_valid_with_dash(self):
        self.assertEqual(_validate_path_segment("fake_provider_v1", "pn"), "fake_provider_v1")

    def test_03_valid_with_digits(self):
        self.assertEqual(_validate_path_segment("FIC-001", "mid"), "FIC-001")

    def test_04_valid_snapshot_id(self):
        self.assertEqual(_validate_path_segment("FIC-SNAP-MINIMAL-001", "sid"), "FIC-SNAP-MINIMAL-001")

    def test_05_valid_hash_like(self):
        # 64-char hex is valid as a segment (characters pass the regex)
        self.assertEqual(
            _validate_path_segment("e21ec3300d4e8207ed552cde57b7d742164219c06575b47029abad4c0d490b5a", "h"),
            "e21ec3300d4e8207ed552cde57b7d742164219c06575b47029abad4c0d490b5a",
        )

    # ── Reject empty / whitespace ──

    def test_06_reject_empty(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("", "field")

    def test_07_reject_whitespace_only(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("   ", "field")

    # ── Reject path traversal ──

    def test_08_reject_dot(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment(".", "field")

    def test_09_reject_dotdot(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("..", "field")

    def test_10_reject_slash(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("a/b", "field")

    def test_11_reject_backslash(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("a\\b", "field")

    def test_12_reject_leading_slash(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("/etc/passwd", "field")

    def test_13_reject_dotdot_path(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("../../etc", "field")

    # ── Reject control / special characters ──

    def test_14_reject_null(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("a\x00b", "field")

    def test_15_reject_space(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("has space", "field")

    def test_16_reject_newline(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("a\nb", "field")

    def test_17_reject_colon(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_path_segment("C:file", "field")


# ==========================================================================
# Patch 16.1 — Root containment
# ==========================================================================


class RootContainmentTests(unittest.TestCase):
    """_ensure_under_root prevents path traversal escapes."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_01_valid_path_passes(self):
        p = self.root / "snapshots" / "FIC-001"
        result = _ensure_under_root(p, self.root)
        self.assertTrue(result.is_absolute())

    def test_02_dotdot_escapes_root(self):
        p = self.root / ".." / "escaped"
        with self.assertRaises(InvalidStorePayloadError):
            _ensure_under_root(p, self.root)

    def test_03_deep_traversal_rejected(self):
        p = self.root / "a" / ".." / ".." / ".." / "etc"
        with self.assertRaises(InvalidStorePayloadError):
            _ensure_under_root(p, self.root)

    def test_04_absolute_path_outside_root(self):
        p = Path("/tmp/escaped")
        with self.assertRaises(InvalidStorePayloadError):
            _ensure_under_root(p, self.root)


# ==========================================================================
# Patch 16.1 — Raw payload hash validation
# ==========================================================================


class RawPayloadHashValidationTests(unittest.TestCase):
    """_validate_raw_payload_hash checks 64-char hex."""

    def test_01_valid_64_hex(self):
        h = "e21ec3300d4e8207ed552cde57b7d742164219c06575b47029abad4c0d490b5a"
        self.assertEqual(_validate_raw_payload_hash(h), h)

    def test_02_reject_short(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_raw_payload_hash("abc123")

    def test_03_reject_long(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_raw_payload_hash("a" * 65)

    def test_04_reject_non_hex(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_raw_payload_hash("g" * 64)

    def test_05_reject_uppercase(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_raw_payload_hash("A" * 64)


# ==========================================================================
# Patch 16.1 — Capability segment validation
# ==========================================================================


class CapabilitySegmentValidationTests(unittest.TestCase):
    """_validate_capability_segment only allows ProviderCapability values."""

    def test_01_valid_teams(self):
        self.assertEqual(_validate_capability_segment("teams"), "teams")

    def test_02_valid_odds(self):
        self.assertEqual(_validate_capability_segment("odds"), "odds")

    def test_03_valid_prematch_signals(self):
        self.assertEqual(_validate_capability_segment("prematch_signals"), "prematch_signals")

    def test_04_reject_unknown(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_capability_segment("unknown_capability")

    def test_05_reject_arbitrary_string(self):
        with self.assertRaises(InvalidStorePayloadError):
            _validate_capability_segment("anything_else")


# ==========================================================================
# Patch 16.1 — Store path validation integration
# ==========================================================================


class StorePathValidationIntegrationTests(unittest.TestCase):
    """Path segment validation is enforced in store operations."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))
        self.provider = DeterministicFakeProvider()

    def tearDown(self):
        self.temp.cleanup()

    # ── Malicious provider_name ──

    def test_01_write_rejects_traversal_provider(self):
        """Cannot write with provider_name containing .."""
        result = self.provider.fetch_teams()
        # Mutate the provider_name in to_dict result
        data = result.to_dict()
        data["provider_name"] = "../evil"
        # Monkey-patch to_dict to return malicious data
        import types
        evil_result = types.SimpleNamespace(to_dict=lambda: data)
        with self.assertRaises(InvalidStorePayloadError):
            self.store.write_raw_fetch_result(evil_result)

    def test_02_read_rejects_traversal_provider(self):
        with self.assertRaises(InvalidStorePayloadError):
            self.store.read_raw_fetch_result(
                provider_name="../evil",
                capability="teams",
                raw_payload_hash="e21ec3300d4e8207ed552cde57b7d742164219c06575b47029abad4c0d490b5a",
            )

    def test_03_write_rejects_slash_in_provider(self):
        data = self.provider.fetch_teams().to_dict()
        data["provider_name"] = "evil/name"
        import types
        evil_result = types.SimpleNamespace(to_dict=lambda: data)
        with self.assertRaises(InvalidStorePayloadError):
            self.store.write_raw_fetch_result(evil_result)

    # ── Malicious match_id / snapshot_id ──

    def test_04_snapshot_write_rejects_path_traversal_match_id(self):
        """Cannot write snapshot with match_id containing .."""
        from oracle_core.data_service_types import MatchContextSnapshot
        from tests.fixtures.data_service import (
            FICTIONAL_MATCH_ALPHA_BETA,
            FICTIONAL_TEAM_ALPHA,
            FICTIONAL_TEAM_BETA,
            FIXED_NOW,
        )
        import copy
        match = copy.deepcopy(FICTIONAL_MATCH_ALPHA_BETA)
        # We can't modify frozen dataclass, so create a malicious dict via to_dict
        snap = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-EVIL",
            snapshot_created_at=FIXED_NOW,
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )
        data = snap.to_dict()
        data["match"]["match_id"] = "../escape"
        import types
        evil_snap = types.SimpleNamespace(to_dict=lambda: data)
        with self.assertRaises(InvalidStorePayloadError):
            self.store.write_match_context_snapshot(evil_snap)

    def test_05_snapshot_read_rejects_traversal_match_id(self):
        with self.assertRaises(InvalidStorePayloadError):
            self.store.read_match_context_snapshot("../escape", "FIC-SNAP-001")

    def test_06_snapshot_write_rejects_traversal_snapshot_id(self):
        snap = make_minimal_snapshot()
        data = snap.to_dict()
        data["snapshot_id"] = "../../evil"
        import types
        evil_snap = types.SimpleNamespace(to_dict=lambda: data)
        with self.assertRaises(InvalidStorePayloadError):
            self.store.write_match_context_snapshot(evil_snap)

    # ── Malicious raw_payload_hash ──

    def test_07_read_rejects_non_hex_hash(self):
        with self.assertRaises(InvalidStorePayloadError):
            self.store.read_raw_fetch_result(
                provider_name="fake_provider_v1",
                capability="teams",
                raw_payload_hash="not-a-valid-hash!!!",
            )

    def test_08_read_rejects_short_hash(self):
        with self.assertRaises(InvalidStorePayloadError):
            self.store.read_raw_fetch_result(
                provider_name="fake_provider_v1",
                capability="teams",
                raw_payload_hash="abc123",
            )

    # ── Valid IDs still work ──

    def test_09_valid_fixture_ids_still_work_write_read(self):
        """Existing fake provider and fixture IDs pass validation and roundtrip."""
        result = self.provider.fetch_teams()
        path = self.store.write_raw_fetch_result(result)
        self.assertTrue(path.exists())
        data = self.store.read_raw_fetch_result(
            "fake_provider_v1", "teams", result.raw_payload_hash,
        )
        self.assertEqual(data["provider_name"], "fake_provider_v1")

    def test_10_valid_snapshot_ids_still_work(self):
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)
        data = self.store.read_match_context_snapshot("FIC-001", "FIC-SNAP-MINIMAL-001")
        self.assertEqual(data["snapshot_id"], "FIC-SNAP-MINIMAL-001")

    def test_11_no_file_created_outside_root(self):
        """After rejection, no file should exist outside temp root."""
        import types
        # Try to write with malicious provider_name
        data = self.provider.fetch_teams().to_dict()
        data["provider_name"] = "../evil"
        evil_result = types.SimpleNamespace(to_dict=lambda: data)
        try:
            self.store.write_raw_fetch_result(evil_result)
        except InvalidStorePayloadError:
            pass
        # No "evil" directory should exist in parent of temp root
        parent_dir = Path(self.temp.name).parent
        evil_path = parent_dir / "evil"
        self.assertFalse(
            evil_path.exists(),
            f"Path traversal created file outside root: {evil_path}",
        )


# ==========================================================================
# Patch 16.1 — Timestamp canonicalization and sorting
# ==========================================================================


class TimestampSortingTests(unittest.TestCase):
    """Snapshot listing sorts by parsed aware datetime, not string order."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_01_different_timezone_offsets_sort_by_instant(self):
        """Snapshots with different UTC offsets sort by real instant."""
        from oracle_core.data_service_types import MatchContextSnapshot
        from tests.fixtures.data_service import (
            FICTIONAL_MATCH_ALPHA_BETA,
            FICTIONAL_TEAM_ALPHA,
            FICTIONAL_TEAM_BETA,
        )

        # Create snapshots with different timezone offsets
        # +05:00 (09:00 UTC) — earlier in real time
        snap_earlier = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-TZ-EARLY",
            snapshot_version="1.0.0",
            snapshot_created_at=datetime(2026, 6, 15, 14, 0, 0,
                                         tzinfo=timezone(offset=__import__("datetime").timedelta(hours=5))),
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )
        # +02:00 (11:00 UTC) — later in real time
        snap_later = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-TZ-LATER",
            snapshot_version="1.0.0",
            snapshot_created_at=datetime(2026, 6, 15, 13, 0, 0,
                                         tzinfo=timezone(offset=__import__("datetime").timedelta(hours=2))),
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )

        # Write later first (reverse order)
        self.store.write_match_context_snapshot(snap_later)
        self.store.write_match_context_snapshot(snap_earlier)

        snapshots = self.store.list_match_context_snapshots("FIC-001")
        self.assertEqual(len(snapshots), 2)
        # snap_earlier (+05:00, 09:00 UTC) should come first
        self.assertEqual(snapshots[0]["snapshot_id"], "FIC-SNAP-TZ-EARLY")
        # snap_later (+02:00, 11:00 UTC) should come second
        self.assertEqual(snapshots[1]["snapshot_id"], "FIC-SNAP-TZ-LATER")

    def test_02_latest_uses_parsed_datetime(self):
        """Latest returns the snapshot with greatest real instant."""
        from oracle_core.data_service_types import MatchContextSnapshot
        from tests.fixtures.data_service import (
            FICTIONAL_MATCH_ALPHA_BETA,
            FICTIONAL_TEAM_ALPHA,
            FICTIONAL_TEAM_BETA,
        )
        from datetime import timedelta

        snap1 = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-LATEST-TEST-1",
            snapshot_version="1.0.0",
            snapshot_created_at=datetime(2026, 6, 15, 10, 0, 0,
                                         tzinfo=timezone(timedelta(hours=3))),
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )
        snap2 = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-LATEST-TEST-2",
            snapshot_version="1.0.0",
            snapshot_created_at=datetime(2026, 6, 15, 8, 0, 0,
                                         tzinfo=timezone.utc),
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )

        self.store.write_match_context_snapshot(snap1)
        self.store.write_match_context_snapshot(snap2)

        # snap1: +03:00 10:00 = 07:00 UTC
        # snap2: +00:00 08:00 = 08:00 UTC → later
        latest = self.store.latest_match_context_snapshot("FIC-001")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["snapshot_id"], "FIC-SNAP-LATEST-TEST-2")

    def test_03_naive_datetime_rejected(self):
        """Writing a snapshot with naive datetime is rejected."""
        snap = make_minimal_snapshot()
        data = snap.to_dict()
        # Replace with naive datetime
        data["snapshot_created_at"] = datetime(2026, 6, 15, 12, 0, 0)  # naive
        # _canonicalize_store_dict would reject it via _datetime_to_iso
        import types
        from oracle_core.data_service_store import _canonicalize_store_dict
        with self.assertRaises(InvalidStorePayloadError):
            _canonicalize_store_dict(data)

    def test_04_list_returns_sorted_by_real_instant(self):
        """String order would be wrong; parsed datetime order is correct."""
        from oracle_core.data_service_types import MatchContextSnapshot
        from tests.fixtures.data_service import (
            FICTIONAL_MATCH_ALPHA_BETA,
            FICTIONAL_TEAM_ALPHA,
            FICTIONAL_TEAM_BETA,
        )
        from datetime import timedelta

        # Create snapshots where string sort gives wrong order
        # "+02:00T10:00" sorts BEFORE "+05:00T09:00" as strings
        # but +05:00T09:00 = 04:00 UTC, +02:00T10:00 = 08:00 UTC
        snap_early_real = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-STR-EARLY",
            snapshot_created_at=datetime(2026, 6, 15, 9, 0, 0,
                                         tzinfo=timezone(timedelta(hours=5))),
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )
        snap_late_real = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-STR-LATE",
            snapshot_created_at=datetime(2026, 6, 15, 10, 0, 0,
                                         tzinfo=timezone(timedelta(hours=2))),
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )
        self.store.write_match_context_snapshot(snap_late_real)
        self.store.write_match_context_snapshot(snap_early_real)

        snapshots = self.store.list_match_context_snapshots("FIC-001")
        # Early real = +05:00 09:00 = 04:00 UTC → first
        self.assertEqual(snapshots[0]["snapshot_id"], "FIC-SNAP-STR-EARLY")
        # Late real = +02:00 10:00 = 08:00 UTC → second
        self.assertEqual(snapshots[1]["snapshot_id"], "FIC-SNAP-STR-LATE")

    def test_05_invalid_timestamp_in_index_raises(self):
        """If a stored snapshot has an unparseable timestamp, index rebuild raises."""
        snap = make_minimal_snapshot()
        self.store.write_match_context_snapshot(snap)

        # Manually write a corrupt snapshot file
        snap_dir = self.store._snapshots_dir("FIC-001")
        corrupt_path = snap_dir / "FIC-SNAP-CORRUPT.json"
        corrupt_path.write_text(
            json.dumps({
                "snapshot_id": "FIC-SNAP-CORRUPT",
                "snapshot_version": "1.0.0",
                "snapshot_created_at": "not-a-valid-timestamp",
                "match": {"match_id": "FIC-001"},
            }),
            encoding="utf-8",
        )

        # Now writing another snapshot should trigger index rebuild → raise
        from oracle_core.data_service_types import MatchContextSnapshot
        from tests.fixtures.data_service import (
            FICTIONAL_MATCH_ALPHA_BETA,
            FICTIONAL_TEAM_ALPHA,
            FICTIONAL_TEAM_BETA,
        )
        snap2 = MatchContextSnapshot(
            snapshot_id="FIC-SNAP-TRIGGER-REBUILD",
            snapshot_created_at=datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc),
            match=FICTIONAL_MATCH_ALPHA_BETA,
            team_a=FICTIONAL_TEAM_ALPHA,
            team_b=FICTIONAL_TEAM_BETA,
        )
        with self.assertRaises(InvalidStorePayloadError):
            self.store.write_match_context_snapshot(snap2)

    def test_06_parse_iso_rejects_non_string(self):
        """_parse_iso raises on non-string input."""
        with self.assertRaises(InvalidStorePayloadError):
            _parse_iso(42)

    def test_07_parse_iso_rejects_garbage(self):
        with self.assertRaises(InvalidStorePayloadError):
            _parse_iso("garbage-not-a-date")


if __name__ == "__main__":
    unittest.main()
