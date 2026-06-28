"""TheSportsDB live raw store capture — opt-in only.

NOT in default discovery.  Requires:
    WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS=1 python -m unittest discover tests_live -v

Writes to tempfile.TemporaryDirectory() — auto-cleaned, never committed.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.live_provider_harness import (
    require_live_provider_enabled,
    build_live_provider_config_from_env,
)
from oracle_core.free_provider_adapters import (
    TheSportsDbProviderAdapter,
    StdlibHttpTransport,
)
from oracle_core.data_service_store import DataServiceLocalStore
from oracle_core.free_provider_live_capture import (
    persist_provider_fetch_result,
)
from oracle_core.data_service_providers import ProviderCapability


class TheSportsDbLiveCaptureTest(unittest.TestCase):
    """Live fetch → raw store persistence (tempdir, auto-cleaned)."""

    @classmethod
    def setUpClass(cls):
        env = os.environ
        require_live_provider_enabled(env)
        config = build_live_provider_config_from_env(env, "thesportsdb")
        cls.provider = TheSportsDbProviderAdapter(
            config=config, transport=StdlibHttpTransport())
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.store = DataServiceLocalStore(root_path=Path(cls.tempdir.name))

    @classmethod
    def tearDownClass(cls):
        cls.tempdir.cleanup()

    # ── fetch_teams → store ──

    def test_01_fetch_teams_persist_succeeds(self):
        r = self.provider.fetch_teams()
        meta = persist_provider_fetch_result(
            self.store, r,
            capture_reason="Patch 28 live smoke",
            allow_real_payload=True,
        )
        self.assertEqual(meta.provider_name, "thesportsdb")
        self.assertEqual(meta.payload_kind, "opt_in_live")

    def test_02_teams_metadata_redacted(self):
        r = self.provider.fetch_teams()
        meta = persist_provider_fetch_result(
            self.store, r,
            capture_reason="Patch 28 live smoke",
            allow_real_payload=True,
        )
        self.assertEqual(meta.redaction_status, "redacted")
        self.assertIn("<public_test_key>", meta.source_reference)
        self.assertNotIn("123", meta.source_reference)

    def test_03_teams_roundtrip(self):
        r = self.provider.fetch_teams()
        meta = persist_provider_fetch_result(
            self.store, r,
            capture_reason="Patch 28 live smoke",
            allow_real_payload=True,
        )
        data = self.store.read_raw_fetch_result(
            "thesportsdb", "teams", r.raw_payload_hash)
        self.assertEqual(data["provider_name"], "thesportsdb")
        self.assertIn("teams", data["payload"])

    def test_04_teams_model_boundary(self):
        r = self.provider.fetch_teams()
        meta = persist_provider_fetch_result(
            self.store, r,
            capture_reason="Patch 28 live smoke",
            allow_real_payload=True,
        )
        self.assertFalse(meta.model_boundary["affects_model"])
        self.assertTrue(meta.model_boundary["report_only_or_context_only"])

    # ── fetch_matches → store ──

    def test_05_fetch_matches_persist_succeeds(self):
        r = self.provider.fetch_matches()
        meta = persist_provider_fetch_result(
            self.store, r,
            capture_reason="Patch 28 live smoke",
            allow_real_payload=True,
        )
        self.assertEqual(meta.provider_name, "thesportsdb")
        self.assertEqual(meta.payload_kind, "opt_in_live")

    def test_06_matches_metadata_redacted(self):
        r = self.provider.fetch_matches()
        meta = persist_provider_fetch_result(
            self.store, r,
            capture_reason="Patch 28 live smoke",
            allow_real_payload=True,
        )
        self.assertIn("<public_test_key>", meta.source_reference)
        self.assertNotIn("123", meta.source_reference)

    def test_07_matches_roundtrip(self):
        r = self.provider.fetch_matches()
        meta = persist_provider_fetch_result(
            self.store, r,
            capture_reason="Patch 28 live smoke",
            allow_real_payload=True,
        )
        data = self.store.read_raw_fetch_result(
            "thesportsdb", "matches", r.raw_payload_hash)
        self.assertEqual(data["provider_name"], "thesportsdb")
