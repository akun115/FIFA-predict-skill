"""Bounded compressed SQLite response cache."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import time


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _key(provider: str, operation: str, params: dict) -> str:
    raw = "\n".join((provider, operation, _canonical(params))).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CacheHit:
    value: object
    state: str
    created_at: float
    expires_at: float


class SQLiteResponseCache:
    def __init__(self, path: str | Path, *, max_bytes: int) -> None:
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    payload_size INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    last_accessed_at REAL NOT NULL
                )
                """
            )

    def put(
        self,
        provider: str,
        operation: str,
        params: dict,
        value: object,
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")
        timestamp = time.time() if now is None else float(now)
        params_json = _canonical(params)
        payload = gzip.compress(_canonical(value).encode("utf-8"))
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO cache_entries (
                    cache_key, provider, operation, params_json, payload,
                    payload_size, created_at, expires_at, last_accessed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload=excluded.payload,
                    payload_size=excluded.payload_size,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    last_accessed_at=excluded.last_accessed_at
                """,
                (
                    _key(provider, operation, params), provider, operation, params_json,
                    payload, len(payload), timestamp, timestamp + ttl_seconds, timestamp,
                ),
            )
        self.enforce_limit(self.max_bytes)

    def get(
        self,
        provider: str,
        operation: str,
        params: dict,
        *,
        now: float | None = None,
        allow_stale: bool = False,
    ) -> CacheHit | None:
        timestamp = time.time() if now is None else float(now)
        cache_key = _key(provider, operation, params)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload, created_at, expires_at FROM cache_entries WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            payload, created_at, expires_at = row
            if timestamp > expires_at and not allow_stale:
                return None
            try:
                value = json.loads(gzip.decompress(payload).decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                connection.execute(
                    "DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,)
                )
                return None
            connection.execute(
                "UPDATE cache_entries SET last_accessed_at = ? WHERE cache_key = ?",
                (timestamp, cache_key),
            )
        state = "stale" if timestamp > expires_at else "fresh"
        return CacheHit(value=value, state=state, created_at=created_at, expires_at=expires_at)

    def enforce_limit(self, max_bytes: int | None = None) -> int:
        limit = self.max_bytes if max_bytes is None else max_bytes
        removed = 0
        with self._connection() as connection:
            while True:
                total = connection.execute(
                    "SELECT COALESCE(SUM(payload_size), 0) FROM cache_entries"
                ).fetchone()[0]
                if total <= limit:
                    break
                row = connection.execute(
                    "SELECT cache_key FROM cache_entries ORDER BY last_accessed_at, cache_key LIMIT 1"
                ).fetchone()
                if row is None:
                    break
                connection.execute(
                    "DELETE FROM cache_entries WHERE cache_key = ?", (row[0],)
                )
                removed += 1
        return removed

    def purge(self, provider: str = "") -> int:
        with self._connection() as connection:
            if provider:
                cursor = connection.execute(
                    "DELETE FROM cache_entries WHERE provider = ?", (provider,)
                )
            else:
                cursor = connection.execute("DELETE FROM cache_entries")
            return cursor.rowcount

    def status(self) -> dict:
        with self._connection() as connection:
            count, size = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(payload_size), 0) FROM cache_entries"
            ).fetchone()
        return {"entry_count": count, "payload_bytes": size, "max_bytes": self.max_bytes}
