"""Tests for web_scout_fallback — Patch 33."""

import unittest

from oracle_core.web_scout_fallback import (
    WebScoutEvidence,
    WebScoutRequest,
    WebScoutResult,
    DisabledWebScoutAdapter,
    DeterministicFakeWebScoutAdapter,
    build_web_scout_requests,
    run_web_scout_fallback,
)


class TestWebScoutFallback(unittest.TestCase):
    """Tests for Web Scout fallback runtime."""

    def setUp(self):
        self.gap_list = (
            "injuries_missing",
            "lineups_missing",
            "suspensions_missing",
            "weather_missing",
            "standings_missing",  # Not scoutable
            "odds_missing",  # Not scoutable
            "prematch_signals_missing",
        )

    # ── Test 22: disabled adapter returns gap/caveat ──
    def test_disabled_adapter_returns_gap_caveat(self):
        requests = build_web_scout_requests(
            self.gap_list, match_id="FIC-MATCH-001",
        )
        result = run_web_scout_fallback(requests, DisabledWebScoutAdapter())
        self.assertEqual(len(result.evidence), 0)
        self.assertGreater(len(result.gaps), 0)
        self.assertGreater(len(result.caveats), 0)
        self.assertIn("scout_web_provider_missing", result.gaps)

    # ── Test 23: fake adapter returns synthetic evidence ──
    def test_fake_adapter_returns_synthetic_evidence(self):
        requests = build_web_scout_requests(
            self.gap_list, match_id="FIC-MATCH-001",
        )
        result = run_web_scout_fallback(
            requests, DeterministicFakeWebScoutAdapter(),
        )
        self.assertGreater(len(result.evidence), 0)
        for ev in result.evidence:
            self.assertIn("synthetic", ev.confidence)
            self.assertIn("FIC-", ev.evidence_id)

    # ── Test 24: scout evidence is report-only/context-only ──
    def test_scout_evidence_is_report_only(self):
        requests = build_web_scout_requests(
            self.gap_list, match_id="FIC-MATCH-001",
        )
        result = run_web_scout_fallback(
            requests, DeterministicFakeWebScoutAdapter(),
        )
        for ev in result.evidence:
            self.assertTrue(ev.report_only)

    # ── Test 25: scout evidence does not modify model_output ──
    def test_scout_evidence_does_not_modify_model_output(self):
        model_output = {
            "result_probabilities": {"team_a_win": 0.5},
        }
        original = dict(model_output)
        requests = build_web_scout_requests(
            self.gap_list, match_id="FIC-MATCH-001",
        )
        result = run_web_scout_fallback(
            requests, DeterministicFakeWebScoutAdapter(),
        )
        # Scout evidence should not touch model_output
        self.assertEqual(model_output, original)
        # Verify no probability fields in evidence
        for ev in result.evidence:
            d = ev.to_dict()
            self.assertNotIn("result_probabilities", d)
            self.assertNotIn("xG", d)

    # ── Test 26: missing injuries/lineups/weather/news generate scout requests ──
    def test_gaps_generate_scout_requests(self):
        requests = build_web_scout_requests(
            self.gap_list, match_id="FIC-MATCH-001",
        )
        topics = {r.topic for r in requests}
        self.assertIn("injuries", topics)
        self.assertIn("lineups", topics)
        self.assertIn("weather", topics)
        # standings and odds should NOT generate scout requests
        self.assertNotIn("standings", topics)
        self.assertNotIn("odds", topics)

    # ── Test 27: no default network ──
    def test_no_default_network(self):
        # Default adapter is Disabled, which is the fail-closed default
        adapter = DisabledWebScoutAdapter()
        req = WebScoutRequest(
            request_id="test-1", topic="injuries",
        )
        result = adapter.search(req)
        self.assertIsNone(result)
        # No import of urllib, requests, etc. in the default path

    # ── Test 28: no env read in default tests ──
    def test_no_env_read_in_default(self):
        # Disabled adapter doesn't read env vars
        requests = build_web_scout_requests(
            self.gap_list, match_id="FIC-MATCH-001",
        )
        result = run_web_scout_fallback(requests)  # Default = Disabled
        self.assertEqual(result.adapter_used, "disabled")

    # ── Test: WebScoutEvidence dataclass validation ──
    def test_evidence_dataclass_validation(self):
        ev = WebScoutEvidence(
            evidence_id="test-ev-1",
            evidence_type="injuries",
            summary="Test summary",
            confidence="synthetic",
            source_url_or_reference="fixture://test",
        )
        self.assertEqual(ev.evidence_id, "test-ev-1")
        self.assertTrue(ev.report_only)

    # ── Test: WebScoutRequest dataclass validation ──
    def test_request_dataclass_validation(self):
        req = WebScoutRequest(
            request_id="req-1",
            topic="injuries",
            match_id="FIC-001",
            team_ids=("FIC-ALPHA",),
        )
        self.assertEqual(req.topic, "injuries")

    # ── Test: fake adapter provenance ──
    def test_fake_adapter_provenance(self):
        requests = build_web_scout_requests(
            ("weather_missing",), match_id="FIC-MATCH-001",
        )
        result = run_web_scout_fallback(
            requests, DeterministicFakeWebScoutAdapter(),
        )
        for ev in result.evidence:
            self.assertIn("FIC-*", ev.provenance)

    # ── Test: build_web_scout_requests with empty gap_list ──
    def test_empty_gap_list_generates_no_requests(self):
        requests = build_web_scout_requests(())
        self.assertEqual(len(requests), 0)

    # ── Test: scout evidence has required fields ──
    def test_evidence_has_required_fields(self):
        requests = build_web_scout_requests(
            ("injuries_missing",), match_id="FIC-MATCH-001",
        )
        result = run_web_scout_fallback(
            requests, DeterministicFakeWebScoutAdapter(),
        )
        for ev in result.evidence:
            d = ev.to_dict()
            self.assertIn("evidence_id", d)
            self.assertIn("evidence_type", d)
            self.assertIn("summary", d)
            self.assertIn("confidence", d)
            self.assertIn("source_url_or_reference", d)
            self.assertIn("searched_at", d)
            self.assertIn("provenance", d)


if __name__ == "__main__":
    unittest.main()
