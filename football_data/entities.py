"""Canonical football entity registry."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
import unicodedata
import uuid


class EntityAmbiguityError(ValueError):
    pass


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()


class EntityRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, canonical_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL, created_at REAL NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS entity_aliases (
                    entity_id TEXT NOT NULL, provider TEXT NOT NULL,
                    provider_id TEXT NOT NULL, normalized_alias TEXT NOT NULL,
                    FOREIGN KEY(entity_id) REFERENCES entities(id),
                    UNIQUE(provider, provider_id, entity_id, normalized_alias)
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

    def create(self, kind: str, canonical_name: str) -> str:
        if not kind.strip() or not canonical_name.strip():
            raise ValueError("kind and canonical_name must not be empty")
        entity_id = uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO entities VALUES (?, ?, ?, ?, ?)",
                (entity_id, kind, canonical_name.strip(), _normalize(canonical_name), time.time()),
            )
        return entity_id

    def add_alias(
        self, entity_id: str, provider: str, provider_id: str, alias: str
    ) -> None:
        if not alias.strip():
            raise ValueError("alias must not be empty")
        with self._connection() as connection:
            if connection.execute(
                "SELECT 1 FROM entities WHERE id = ?", (entity_id,)
            ).fetchone() is None:
                raise KeyError(entity_id)
            connection.execute(
                "INSERT OR IGNORE INTO entity_aliases VALUES (?, ?, ?, ?)",
                (entity_id, provider, provider_id, _normalize(alias)),
            )

    def resolve(
        self,
        kind: str,
        *,
        name: str = "",
        provider: str = "",
        provider_id: str = "",
    ) -> str | None:
        with self._connection() as connection:
            if provider and provider_id:
                rows = connection.execute(
                    """SELECT DISTINCT e.id FROM entities e
                       JOIN entity_aliases a ON a.entity_id=e.id
                       WHERE e.kind=? AND a.provider=? AND a.provider_id=?""",
                    (kind, provider, provider_id),
                ).fetchall()
            elif name:
                normalized = _normalize(name)
                rows = connection.execute(
                    """SELECT id FROM entities WHERE kind=? AND normalized_name=?
                       UNION SELECT e.id FROM entities e JOIN entity_aliases a
                       ON a.entity_id=e.id WHERE e.kind=? AND a.normalized_alias=?""",
                    (kind, normalized, kind, normalized),
                ).fetchall()
            else:
                raise ValueError("name or provider/provider_id is required")
        ids = sorted({row[0] for row in rows})
        if len(ids) > 1:
            raise EntityAmbiguityError(f"ambiguous {kind} entity")
        return ids[0] if ids else None

    def count(self) -> int:
        with self._connection() as connection:
            return connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
