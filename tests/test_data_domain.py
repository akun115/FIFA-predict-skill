import io
import json
import os
import socket
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError


class DomainTests(unittest.TestCase):
    def test_match_requires_timezone_aware_kickoff(self):
        from football_data.domain import MatchRecord, Provenance

        provenance = Provenance(
            "openfootball", "match-1", datetime.now(timezone.utc)
        )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            MatchRecord(
                "match-1",
                "PL",
                datetime(2026, 1, 1),
                "Team A",
                "Team B",
                provenance,
            )

    def test_settings_public_summary_never_contains_token(self):
        from football_data.config import DataHubSettings

        with patch.dict(
            os.environ, {"FOOTBALL_DATA_ORG_TOKEN": "secret-value"}, clear=True
        ):
            settings = DataHubSettings.from_env()
        self.assertTrue(settings.football_data_org_enabled)
        self.assertNotIn("secret-value", repr(settings.public_summary()))
        self.assertNotIn("secret-value", repr(settings))
        self.assertEqual(settings.max_cache_bytes, 500 * 1024 * 1024)

    def test_data_states_have_stable_wire_values(self):
        from football_data.domain import DataState

        self.assertEqual(DataState.FRESH.value, "fresh")
        self.assertEqual(DataState.BLOCKED.value, "blocked")


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


class HttpTests(unittest.TestCase):
    def test_http_client_decodes_json(self):
        from football_data.http import UrllibJsonClient

        client = UrllibJsonClient(opener=lambda request, timeout: _Response(b'{"ok":true}'))
        self.assertEqual(client.get_json("https://example.test/data"), {"ok": True})

    def test_http_errors_do_not_expose_headers(self):
        from football_data.http import HttpRequestError, UrllibJsonClient

        def fail(request, timeout):
            raise HTTPError(request.full_url, 429, "limited", {}, io.BytesIO())

        client = UrllibJsonClient(opener=fail)
        with self.assertRaises(HttpRequestError) as caught:
            client.get_json(
                "https://example.test/data", headers={"X-Auth-Token": "secret-value"}
            )
        self.assertEqual(caught.exception.category, "http")
        self.assertEqual(caught.exception.status, 429)
        self.assertNotIn("secret-value", str(caught.exception))

    def test_http_client_classifies_invalid_json_and_timeout(self):
        from football_data.http import HttpRequestError, UrllibJsonClient

        invalid = UrllibJsonClient(opener=lambda request, timeout: _Response(b"not-json"))
        with self.assertRaisesRegex(HttpRequestError, "invalid_json"):
            invalid.get_json("https://example.test/data")

        def timeout(request, timeout):
            raise socket.timeout()

        timed_out = UrllibJsonClient(opener=timeout)
        with self.assertRaisesRegex(HttpRequestError, "timeout"):
            timed_out.get_json("https://example.test/data")


if __name__ == "__main__":
    unittest.main()
