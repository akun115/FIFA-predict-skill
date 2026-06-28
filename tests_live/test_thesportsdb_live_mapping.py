"""TheSportsDB live canonical mapping smoke — opt-in only.

NOT in default discovery.  Requires:
    WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS=1 python -m unittest discover tests_live -v

Does NOT save live payloads.  Only asserts structural properties
(types, model boundary, no prediction fields, no API keys).
"""

from __future__ import annotations

import os
import re
import unittest

from tests.live_provider_harness import (
    require_live_provider_enabled,
    build_live_provider_config_from_env,
)
from oracle_core.free_provider_adapters import (
    TheSportsDbProviderAdapter,
    StdlibHttpTransport,
)
from oracle_core.free_provider_mappers import (
    MappingResult,
    map_thesportsdb_teams,
    map_thesportsdb_matches,
)
from oracle_core.data_service_types import CanonicalTeam, CanonicalMatch


class TheSportsDbLiveMappingTest(unittest.TestCase):
    """Live fetch → canonical mapping structural assertions only."""

    @classmethod
    def setUpClass(cls):
        env = os.environ
        require_live_provider_enabled(env)
        config = build_live_provider_config_from_env(env, "thesportsdb")
        cls.provider = TheSportsDbProviderAdapter(
            config=config, transport=StdlibHttpTransport())

    # ── fetch_teams → map ──

    def test_01_map_teams_returns_mapping_result(self):
        r = self.provider.fetch_teams()
        m = map_thesportsdb_teams(r)
        self.assertIsInstance(m, MappingResult)

    def test_02_map_teams_provider_name(self):
        r = self.provider.fetch_teams()
        m = map_thesportsdb_teams(r)
        self.assertEqual(m.provider_name, "thesportsdb")

    def test_03_map_teams_model_boundary(self):
        r = self.provider.fetch_teams()
        m = map_thesportsdb_teams(r)
        self.assertFalse(m.model_boundary.affects_model)
        self.assertFalse(m.model_boundary.enters_prediction_engine)
        self.assertTrue(m.model_boundary.report_only_or_context_only)

    def test_04_map_teams_canonical_items_is_list(self):
        r = self.provider.fetch_teams()
        m = map_thesportsdb_teams(r)
        self.assertIsInstance(m.canonical_items, tuple)
        for item in m.canonical_items:
            self.assertIsInstance(item, CanonicalTeam)

    def test_05_map_teams_data_quality_issues(self):
        r = self.provider.fetch_teams()
        m = map_thesportsdb_teams(r)
        self.assertIsInstance(m.data_quality_issues, tuple)
        # Must include common issues
        codes = {i.code for i in m.data_quality_issues}
        self.assertIn("PROVIDER_NEEDS_MORE_INFO", codes)
        self.assertIn("MODEL_BOUNDARY_REPORT_ONLY", codes)

    def test_06_map_teams_no_prediction_fields(self):
        r = self.provider.fetch_teams()
        m = map_thesportsdb_teams(r)
        for item in m.canonical_items:
            d = item.to_dict()
            for banned in ("result_probabilities", "expected_goals",
                           "advancement_probabilities", "predicted_score"):
                self.assertNotIn(banned, d)

    def test_07_map_teams_no_api_key_in_source(self):
        r = self.provider.fetch_teams()
        m = map_thesportsdb_teams(r)
        self.assertNotIn("123", m.source_reference)
        # Must be redacted
        self.assertIn("<public_test_key>", m.source_reference)

    def test_08_map_teams_no_narrative_prediction(self):
        r = self.provider.fetch_teams()
        m = map_thesportsdb_teams(r)
        for item in m.canonical_items:
            d = item.to_dict()
            text = str(d)
            for pat in ("I predict", "will win", "likely score"):
                self.assertNotIn(pat, text)

    # ── fetch_matches → map ──

    def test_09_map_matches_returns_mapping_result(self):
        r = self.provider.fetch_matches()
        m = map_thesportsdb_matches(r)
        self.assertIsInstance(m, MappingResult)

    def test_10_map_matches_provider_name(self):
        r = self.provider.fetch_matches()
        m = map_thesportsdb_matches(r)
        self.assertEqual(m.provider_name, "thesportsdb")

    def test_11_map_matches_model_boundary(self):
        r = self.provider.fetch_matches()
        m = map_thesportsdb_matches(r)
        self.assertFalse(m.model_boundary.affects_model)
        self.assertFalse(m.model_boundary.enters_prediction_engine)

    def test_12_map_matches_canonical_items_is_list(self):
        r = self.provider.fetch_matches()
        m = map_thesportsdb_matches(r)
        self.assertIsInstance(m.canonical_items, tuple)
        for item in m.canonical_items:
            self.assertIsInstance(item, CanonicalMatch)

    def test_13_map_matches_data_quality_issues(self):
        r = self.provider.fetch_matches()
        m = map_thesportsdb_matches(r)
        self.assertIsInstance(m.data_quality_issues, tuple)
        codes = {i.code for i in m.data_quality_issues}
        self.assertIn("LIMITED_MATCH_COVERAGE", codes)

    def test_14_map_matches_no_prediction_fields(self):
        r = self.provider.fetch_matches()
        m = map_thesportsdb_matches(r)
        for item in m.canonical_items:
            d = item.to_dict()
            for banned in ("result_probabilities", "expected_goals",
                           "advancement_probabilities", "predicted_score"):
                self.assertNotIn(banned, d)

    def test_15_map_matches_no_api_key_in_source(self):
        r = self.provider.fetch_matches()
        m = map_thesportsdb_matches(r)
        self.assertNotIn("123", m.source_reference)
        self.assertIn("<public_test_key>", m.source_reference)


if __name__ == "__main__":
    unittest.main()
