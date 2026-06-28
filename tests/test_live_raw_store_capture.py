"""Patch 28 — Raw store capture default offline tests.

All offline.  No network.  No real data.  No skipped tests.
"""

from __future__ import annotations

import ast
import pathlib
import tempfile
import unittest
from pathlib import Path

from oracle_core.data_service_providers import (
    DeterministicFakeProvider,
    ProviderCapability,
    ProviderFetchResult,
)
from oracle_core.data_service_store import (
    DataServiceLocalStore,
    InvalidStorePayloadError,
)
from oracle_core.free_provider_live_capture import (
    StoredRawFetchMetadata,
    persist_provider_fetch_result,
    _check_no_forbidden_keys,
    _check_no_narrative,
    _check_source_redacted,
)

from tests.provider_contract_helpers import (
    assert_provider_does_not_import_prediction_runtime,
)

REPO = pathlib.Path(__file__).parent.parent


# ==========================================================================
# Import boundary
# ==========================================================================


class CaptureImportBoundaryTests(unittest.TestCase):
    def test_01_capture_module_clean(self):
        mod_path = REPO / "oracle_core" / "free_provider_live_capture.py"
        assert_provider_does_not_import_prediction_runtime(mod_path)

    def test_02_prediction_modules_no_capture_import(self):
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
                        self.assertNotIn("free_provider_live_capture", alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertNotIn("free_provider_live_capture", node.module)


# ==========================================================================
# Synthetic payload persistence
# ==========================================================================


class SyntheticPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))
        self.provider = DeterministicFakeProvider()

    def tearDown(self):
        self.temp.cleanup()

    def test_01_synthetic_can_be_persisted(self):
        r = self.provider.fetch_teams()
        meta = persist_provider_fetch_result(self.store, r)
        self.assertEqual(meta.provider_name, "fake_provider_v1")
        self.assertEqual(meta.capability, "teams")
        self.assertEqual(meta.payload_kind, "synthetic")

    def test_02_metadata_has_provenance_fields(self):
        r = self.provider.fetch_teams()
        meta = persist_provider_fetch_result(self.store, r)
        self.assertTrue(meta.provider_name)
        self.assertTrue(meta.adapter_version)
        self.assertTrue(meta.raw_payload_hash)
        self.assertTrue(meta.stored_at)

    def test_03_metadata_model_boundary(self):
        r = self.provider.fetch_teams()
        meta = persist_provider_fetch_result(self.store, r)
        self.assertFalse(meta.model_boundary["affects_model"])
        self.assertTrue(meta.model_boundary["report_only_or_context_only"])

    def test_04_payload_roundtrips(self):
        r = self.provider.fetch_teams()
        meta = persist_provider_fetch_result(self.store, r)
        data = self.store.read_raw_fetch_result(
            "fake_provider_v1", "teams", r.raw_payload_hash)
        self.assertEqual(data["provider_name"], "fake_provider_v1")

    def test_05_writes_stay_under_root(self):
        r = self.provider.fetch_teams()
        meta = persist_provider_fetch_result(self.store, r)
        stored = Path(meta.file_path)
        root = Path(self.temp.name).resolve()
        self.assertTrue(str(stored.resolve()).startswith(str(root)))


# ==========================================================================
# Rejection of unsafe content
# ==========================================================================


class UnsafeContentRejectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))
        self.provider = DeterministicFakeProvider()

    def tearDown(self):
        self.temp.cleanup()

    def _make_result(self, payload, source="fixture://test"):
        r = self.provider.fetch_teams()
        return ProviderFetchResult(
            provider_name="test", adapter_version="1.0.0",
            capability=ProviderCapability.TEAMS,
            fetched_at=r.fetched_at,
            source_reference=source,
            raw_payload_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload=payload,
        )

    def test_01_payload_with_expected_goals_rejected(self):
        r = self._make_result({"expected_goals": [1.5, 0.8]})
        with self.assertRaises(InvalidStorePayloadError):
            persist_provider_fetch_result(self.store, r)

    def test_02_payload_with_result_probabilities_rejected(self):
        r = self._make_result({"result_probabilities": {"home": 0.5}})
        with self.assertRaises(InvalidStorePayloadError):
            persist_provider_fetch_result(self.store, r)

    def test_03_narrative_prediction_rejected(self):
        r = self._make_result({"text": "I predict this team will win"})
        with self.assertRaises(InvalidStorePayloadError):
            persist_provider_fetch_result(self.store, r)

    def test_04_unredacted_key_in_source_rejected(self):
        r = self._make_result({}, source="https://x.com/api/v1/json/123/search.php")
        with self.assertRaises(InvalidStorePayloadError):
            persist_provider_fetch_result(self.store, r)

    def test_05_api_key_pattern_rejected(self):
        r = self._make_result({"key": "a" * 32})
        with self.assertRaises(InvalidStorePayloadError):
            persist_provider_fetch_result(self.store, r)


# ==========================================================================
# allow_real_payload gate
# ==========================================================================


class AllowRealPayloadGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DataServiceLocalStore(root_path=Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_01_live_like_result_blocked_by_default(self):
        """Non-fixture:// source is rejected without allow_real_payload=True."""
        from oracle_core.data_service_providers import DeterministicFakeProvider
        p = DeterministicFakeProvider()
        r = ProviderFetchResult(
            provider_name="test", adapter_version="1.0.0",
            capability=ProviderCapability.TEAMS,
            fetched_at=p.fetch_teams().fetched_at,
            source_reference="https://www.thesportsdb.com/api/v1/json/<public_test_key>/searchteams.php",
            raw_payload_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload={},
        )
        with self.assertRaises(InvalidStorePayloadError):
            persist_provider_fetch_result(self.store, r)

    def test_02_live_like_result_allowed_with_flag(self):
        from oracle_core.data_service_providers import DeterministicFakeProvider
        p = DeterministicFakeProvider()
        r = ProviderFetchResult(
            provider_name="test", adapter_version="1.0.0",
            capability=ProviderCapability.TEAMS,
            fetched_at=p.fetch_teams().fetched_at,
            source_reference="https://www.thesportsdb.com/api/v1/json/<public_test_key>/searchteams.php",
            raw_payload_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload={"teams": []},
        )
        meta = persist_provider_fetch_result(
            self.store, r, allow_real_payload=True)
        self.assertEqual(meta.payload_kind, "opt_in_live")
        self.assertEqual(meta.redaction_status, "redacted")


# ==========================================================================
# Tests_live file existence and isolation
# ==========================================================================


class LiveCaptureFileTests(unittest.TestCase):
    def test_01_live_capture_file_exists(self):
        p = REPO / "tests_live" / "test_thesportsdb_live_capture.py"
        self.assertTrue(p.exists(),
                        "tests_live/test_thesportsdb_live_capture.py must exist")

    def test_02_not_in_default_tests(self):
        p = REPO / "tests" / "test_thesportsdb_live_capture.py"
        self.assertFalse(p.exists())

    def test_03_no_skip_in_live_capture(self):
        p = REPO / "tests_live" / "test_thesportsdb_live_capture.py"
        text = p.read_text(encoding="utf-8")
        self.assertNotIn("skipTest", text)
        self.assertNotIn("@unittest.skip", text)

    def test_04_requires_opt_in(self):
        p = REPO / "tests_live" / "test_thesportsdb_live_capture.py"
        text = p.read_text(encoding="utf-8")
        self.assertIn("require_live_provider_enabled", text)


if __name__ == "__main__":
    unittest.main()
