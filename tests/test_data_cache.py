from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path


class CacheTests(unittest.TestCase):
    def setUp(self):
        from football_data.cache import SQLiteResponseCache

        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "hub.sqlite3"
        self.cache = SQLiteResponseCache(self.path, max_bytes=1024 * 1024)

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_and_stale_reads(self):
        self.cache.put(
            "provider", "matches", {"season": "2025"}, {"value": "a"},
            ttl_seconds=60, now=1000,
        )
        fresh = self.cache.get(
            "provider", "matches", {"season": "2025"}, now=1010
        )
        self.assertEqual((fresh.state, fresh.value), ("fresh", {"value": "a"}))
        self.assertIsNone(
            self.cache.get("provider", "matches", {"season": "2025"}, now=2000)
        )
        stale = self.cache.get(
            "provider", "matches", {"season": "2025"}, now=2000,
            allow_stale=True,
        )
        self.assertEqual(stale.state, "stale")

    def test_parameter_order_produces_same_key(self):
        self.cache.put(
            "p", "op", {"a": 1, "b": 2}, {"ok": True}, ttl_seconds=60, now=1
        )
        hit = self.cache.get("p", "op", {"b": 2, "a": 1}, now=2)
        self.assertEqual(hit.value, {"ok": True})
        self.assertEqual(self.cache.status()["entry_count"], 1)

    def test_put_enforces_limit_automatically(self):
        from football_data.cache import SQLiteResponseCache

        tiny = SQLiteResponseCache(self.path, max_bytes=1)
        tiny.put("p", "op", {}, {"payload": "large"}, ttl_seconds=60, now=1)
        status = tiny.status()
        self.assertLessEqual(status["payload_bytes"], 1)
        self.assertEqual(status["entry_count"], 0)

    def test_corrupt_entry_is_removed(self):
        self.cache.put("p", "op", {}, {"ok": True}, ttl_seconds=60, now=1)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute("UPDATE cache_entries SET payload = ?", (b"broken",))
        self.assertIsNone(self.cache.get("p", "op", {}, now=2))
        self.assertEqual(self.cache.status()["entry_count"], 0)

    def test_purge_is_limited_to_provider(self):
        self.cache.put("a", "op", {}, {"a": 1}, ttl_seconds=60, now=1)
        self.cache.put("b", "op", {}, {"b": 1}, ttl_seconds=60, now=1)
        self.assertEqual(self.cache.purge("a"), 1)
        self.assertIsNone(self.cache.get("a", "op", {}, now=2))
        self.assertIsNotNone(self.cache.get("b", "op", {}, now=2))


if __name__ == "__main__":
    unittest.main()
