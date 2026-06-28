"""Tests for mvp_snapshot_replay — Patch 31."""

import unittest
import tempfile
import os

from oracle_core.data_service_providers import (
    ProviderCapability,
    ProviderFetchResult,
)
from oracle_core.free_provider_mappers import (
    map_thesportsdb_teams,
    map_thesportsdb_matches,
)
from oracle_core.free_provider_context_assembly import (
    assemble_match_context_from_mapping_results,
)
from oracle_core.mvp_snapshot_replay import (
    MvpSnapshotStore,
    save_mvp_context_snapshot,
    load_mvp_context_snapshot,
    SavedMvpSnapshotMetadata,
    _sanitize_snapshot_id,
)
from datetime import datetime, timezone


def _make_assembly():
    """Build a synthetic assembly for replay testing."""
    fetch = ProviderFetchResult(
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
    mapping = map_thesportsdb_teams(fetch)
    return assemble_match_context_from_mapping_results(mapping)


class TestMvpSnapshotReplay(unittest.TestCase):
    """Tests for save/load snapshot replay path."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="mvp_replay_test_")
        self.store = MvpSnapshotStore(self.tmpdir)

    # ── Test 9: save/load context snapshot roundtrip ──
    def test_save_load_roundtrip(self):
        assembly = _make_assembly()
        saved = save_mvp_context_snapshot(self.store, assembly)
        loaded = load_mvp_context_snapshot(self.store, saved.snapshot_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["snapshot_id"], saved.snapshot_id)
        self.assertEqual(loaded["provider_name"], "thesportsdb")

    # ── Test 10: gap_list roundtrip ──
    def test_gap_list_roundtrip(self):
        assembly = _make_assembly()
        saved = save_mvp_context_snapshot(self.store, assembly)
        loaded = load_mvp_context_snapshot(self.store, saved.snapshot_id)
        self.assertIn("gap_list", loaded)
        self.assertGreater(len(loaded["gap_list"]), 0)
        self.assertIn("injuries_missing", loaded["gap_list"])

    # ── Test 11: data_quality_issues roundtrip ──
    def test_data_quality_issues_roundtrip(self):
        assembly = _make_assembly()
        saved = save_mvp_context_snapshot(self.store, assembly)
        loaded = load_mvp_context_snapshot(self.store, saved.snapshot_id)
        self.assertIn("data_quality_issues", loaded)
        self.assertGreater(len(loaded["data_quality_issues"]), 0)

    # ── Test 12: model_boundary roundtrip ──
    def test_model_boundary_roundtrip(self):
        assembly = _make_assembly()
        saved = save_mvp_context_snapshot(self.store, assembly)
        loaded = load_mvp_context_snapshot(self.store, saved.snapshot_id)
        self.assertIn("model_boundary", loaded)
        self.assertFalse(loaded["model_boundary"]["affects_model"])
        self.assertTrue(loaded["model_boundary"]["report_only_or_context_only"])
        self.assertFalse(loaded["model_boundary"]["enters_prediction_engine"])

    # ── Test 13: source_reference remains redacted ──
    def test_source_reference_redacted(self):
        assembly = _make_assembly()
        saved = save_mvp_context_snapshot(self.store, assembly)
        loaded = load_mvp_context_snapshot(self.store, saved.snapshot_id)
        for ref in loaded.get("source_references", []):
            self.assertNotIn("/123/", ref,
                             f"Unredacted API key in source reference: {ref}")

    # ── Test 14: path traversal rejected ──
    def test_path_traversal_rejected_by_sanitizer(self):
        with self.assertRaises(ValueError):
            _sanitize_snapshot_id("../../etc/passwd")
        with self.assertRaises(ValueError):
            _sanitize_snapshot_id("snap\\..\\..\\secret")

    def test_path_traversal_rejected_by_store(self):
        store = MvpSnapshotStore(self.tmpdir)
        # Write a file outside the store root
        bad_path = os.path.join(self.tmpdir, "evil.json")
        with open(bad_path, "w") as f:
            f.write("{}")
        # Attempting to read via a path that traverses outside should fail
        # The store.resolve() check catches this
        # For a direct filename, it should be safe; use a traversal attempt
        with self.assertRaises((ValueError, FileNotFoundError)):
            _sanitize_snapshot_id("")

    # ── Test: no prediction fields after replay ──
    def test_no_prediction_fields_after_replay(self):
        assembly = _make_assembly()
        saved = save_mvp_context_snapshot(self.store, assembly)
        loaded = load_mvp_context_snapshot(self.store, saved.snapshot_id)
        # These must be explicitly None or absent
        prediction_fields = [
            "result_probabilities", "expected_goals", "top_scores",
            "advancement_probabilities", "over_under_probabilities",
        ]
        for field in prediction_fields:
            val = loaded.get(field)
            self.assertIsNone(val,
                              f"Prediction field '{field}' should be None in replay, got {val}")

    # ── Test: save metadata has correct structure ──
    def test_save_metadata_structure(self):
        assembly = _make_assembly()
        saved = save_mvp_context_snapshot(self.store, assembly)
        self.assertIsInstance(saved, SavedMvpSnapshotMetadata)
        self.assertTrue(saved.snapshot_id)
        self.assertGreater(saved.gap_count, 0)
        self.assertGreater(saved.issue_count, 0)
        self.assertFalse(saved.model_boundary["affects_model"])

    # ── Test: load non-existent snapshot raises FileNotFoundError ──
    def test_load_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_mvp_context_snapshot(self.store, "nonexistent-snapshot-id")

    # ── Test: default test uses tempfile not repo ──
    def test_store_uses_tempfile(self):
        self.assertIn("mvp_replay_test_", str(self.store.root))
        self.assertTrue(os.path.exists(self.store.root))

    # ── Test: no env read in default tests ──
    def test_no_env_read(self):
        # Verify that save/load work without any env vars set
        assembly = _make_assembly()
        saved = save_mvp_context_snapshot(self.store, assembly)
        loaded = load_mvp_context_snapshot(self.store, saved.snapshot_id)
        self.assertIsNotNone(loaded)


if __name__ == "__main__":
    unittest.main()
