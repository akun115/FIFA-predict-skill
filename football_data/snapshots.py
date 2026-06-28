"""Immutable durable data snapshots."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .quality import QualityReport


class SnapshotConflictError(ValueError):
    pass


_SECRET_PARTS = ("token", "secret", "password", "authorization", "api_key")


def _redact(value):
    if isinstance(value, dict):
        return {
            key: "[redacted]" if any(part in key.casefold() for part in _SECRET_PARTS)
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SnapshotStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL, quality_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )"""
            )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record(self, kind: str, payload: dict, quality: QualityReport) -> str:
        safe_payload = _redact(payload)
        content = {"kind": kind, "payload": safe_payload, "quality": quality.to_dict()}
        snapshot_id = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
        return self.record_with_id(snapshot_id, kind, safe_payload, quality)

    def record_with_id(
        self, snapshot_id: str, kind: str, payload: dict, quality: QualityReport
    ) -> str:
        safe_payload = _redact(payload)
        payload_json = _canonical(safe_payload)
        quality_json = _canonical(quality.to_dict())
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT kind, payload_json, quality_json FROM snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
            candidate = (kind, payload_json, quality_json)
            if existing is not None:
                if existing != candidate:
                    raise SnapshotConflictError(f"snapshot {snapshot_id} already exists")
                return snapshot_id
            connection.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
                (snapshot_id, kind, payload_json, quality_json, time.time()),
            )
        return snapshot_id

    def load(self, snapshot_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT kind, payload_json, quality_json, created_at FROM snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "snapshot_id": snapshot_id,
            "kind": row[0],
            "payload": json.loads(row[1]),
            "quality": json.loads(row[2]),
            "created_at": row[3],
        }
