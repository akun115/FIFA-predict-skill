"""Persistent storage and retention policy — Patch 38.

Provides a ``LocalFilesystemBackend`` with path-traversal protection,
redacted snapshot save/load, retention-policy application (dry-run
safe by default), and a hard block on raw payload saving.

Write location defaults to a system tempdir — never the repo tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import json
import os
import tempfile
from typing import Any, Protocol


# ------------------------------------------------------------------
# Storage backend protocol
# ------------------------------------------------------------------


class StorageBackend(Protocol):
    """Protocol for a persistent storage backend."""

    def save(self, key: str, data: dict[str, Any]) -> None:
        """Save *data* under *key*."""

    def load(self, key: str) -> dict[str, Any] | None:
        """Load data for *key*, or ``None`` if missing."""

    def list_keys(self) -> list[str]:
        """Return all stored keys."""

    def delete(self, key: str) -> bool:
        """Delete *key*.  Return ``True`` if it existed."""


# ------------------------------------------------------------------
# Local filesystem implementation
# ------------------------------------------------------------------


def _is_safe_key(key: str) -> bool:
    """Reject keys containing path-traversal sequences."""
    for unsafe in ("..", "/", "\\", "\x00"):
        if unsafe in key:
            return False
    return bool(key and key.strip())


@dataclass
class LocalFilesystemBackend:
    """``StorageBackend`` that saves JSON files under *root_path*.

    Path-traversal protection: keys containing ``..``, ``/``, ``\\``,
    or null bytes are rejected with ``ValueError``.
    """

    root_path: str

    def __post_init__(self) -> None:
        os.makedirs(self.root_path, exist_ok=True)

    def _path_for(self, key: str) -> str:
        if not _is_safe_key(key):
            raise ValueError(
                f"Unsafe storage key: {key!r} (path traversal denied)"
            )
        return os.path.join(self.root_path, f"{key}.json")

    def save(self, key: str, data: dict[str, Any]) -> None:
        path = self._path_for(key)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    def load(self, key: str) -> dict[str, Any] | None:
        path = self._path_for(key)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def list_keys(self) -> list[str]:
        keys: list[str] = []
        for name in os.listdir(self.root_path):
            if name.endswith(".json"):
                keys.append(name[:-5])
        return sorted(keys)

    def delete(self, key: str) -> bool:
        path = self._path_for(key)
        if not os.path.isfile(path):
            return False
        os.remove(path)
        return True


# ------------------------------------------------------------------
# Retention policy
# ------------------------------------------------------------------


@dataclass(frozen=True)
class RetentionPolicy:
    """Policy governing how long snapshots are retained."""

    max_age_days: int
    """Snapshots older than this are eligible for deletion."""

    max_count: int
    """Maximum number of snapshots to retain (oldest removed first)."""

    policy_name: str
    """Human-readable policy label."""


@dataclass(frozen=True)
class CleanupResult:
    """Outcome of a retention-policy run."""

    files_examined: int
    files_deleted: int
    files_retained: int
    dry_run: bool
    gaps: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()


# ------------------------------------------------------------------
# Factory / helpers
# ------------------------------------------------------------------


def create_local_backend(
    root_path: str | None = None,
) -> LocalFilesystemBackend:
    """Create a ``LocalFilesystemBackend``.

    If ``root_path`` is ``None``, a temporary directory is created
    (outside the repo tree).
    """
    if root_path is None:
        root_path = tempfile.mkdtemp(prefix="wco_storage_")
    return LocalFilesystemBackend(root_path=root_path)


def save_redacted_snapshot(
    backend: StorageBackend,
    snapshot_id: str,
    data: dict[str, Any],
) -> None:
    """Save *data* as a JSON snapshot, redacting ``source_references``.

    The ``source_references`` key (if present) is replaced with a
    redacted copy — credential-like values are masked.
    """
    payload = dict(data)

    raw = payload.get("source_references")
    if raw is not None:
        if isinstance(raw, (list, tuple)):
            payload["source_references"] = [
                _redact_ref(r) for r in raw
            ]
        elif isinstance(raw, str):
            payload["source_references"] = _redact_ref(raw)

    backend.save(snapshot_id, payload)


def load_redacted_snapshot(
    backend: StorageBackend,
    snapshot_id: str,
) -> dict[str, Any] | None:
    """Load a previously saved redacted snapshot."""
    return backend.load(snapshot_id)


def apply_retention_policy(
    backend: StorageBackend,
    policy: RetentionPolicy,
    *,
    dry_run: bool = True,
) -> CleanupResult:
    """Examine stored files and delete those exceeding retention limits.

    Parameters
    ----------
    backend:
        Storage backend to scan.
    policy:
        Retention rules to apply.
    dry_run:
        When ``True`` (the default), files are reported but **not**
        deleted.

    Returns
    -------
    CleanupResult
        Summary of examined, deleted, and retained files.
    """
    keys = backend.list_keys()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=policy.max_age_days)

    # Load timestamps — best-effort from file metadata or content.
    entries: list[tuple[str, datetime]] = []
    caveats: list[str] = []
    for key in keys:
        data = backend.load(key)
        if data is None:
            caveats.append(f"could not load '{key}' — skipped")
            continue
        generated_at = data.get("generated_at") or data.get("timestamp")
        if generated_at is None:
            # Fall back to filesystem mtime.
            try:
                st = os.stat(
                    os.path.join(
                        getattr(backend, "root_path", ""), f"{key}.json"
                    )
                )
                ts = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            except Exception:
                caveats.append(f"no timestamp for '{key}' — retained")
                continue
        else:
            try:
                ts = datetime.fromisoformat(generated_at)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                caveats.append(f"invalid timestamp '{generated_at}' for '{key}' — retained")
                continue
        entries.append((key, ts))

    # Sort by timestamp (oldest first).
    entries.sort(key=lambda e: e[1])

    to_delete: set[str] = set()
    # Delete by age.
    for key, ts in entries:
        if ts < cutoff:
            to_delete.add(key)

    # Enforce max_count — keep the newest *max_count* entries.
    if len(entries) > policy.max_count:
        retain_count = policy.max_count
        for key, _ in entries[: len(entries) - retain_count]:
            to_delete.add(key)

    examined = len(keys)
    deleted = 0
    retained = examined

    for key in to_delete:
        if not dry_run:
            try:
                backend.delete(key)
                deleted += 1
                retained -= 1
            except Exception as exc:
                caveats.append(f"failed to delete '{key}': {exc}")
        else:
            deleted += 1
            retained -= 1

    return CleanupResult(
        files_examined=examined,
        files_deleted=deleted,
        files_retained=retained,
        dry_run=dry_run,
        gaps=(),
        caveats=tuple(caveats),
    )


def raw_payload_save_disabled() -> CleanupResult:
    """Return a ``CleanupResult`` indicating raw payload save is blocked.

    Raw payload saving is **disabled in this version** — this function
    always reports the block without performing any I/O.
    """
    return CleanupResult(
        files_examined=0,
        files_deleted=0,
        files_retained=0,
        dry_run=True,
        caveats=("raw_payload_save disabled in this version",),
    )


def list_stored_snapshots(backend: StorageBackend) -> list[str]:
    """Return a list of stored snapshot IDs."""
    return backend.list_keys()


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

_CREDENTIAL_PATTERN = __import__("re").compile(
    r"(?i)(api[_-]?key|apikey|key|token|secret|password|auth)"
    r"[=:]\s*"
    r"['\"]?"
    r"([a-zA-Z0-9_\-.]{8,})"
)


def _redact_ref(ref: str) -> str:
    """Mask credential-like values in a source-reference string."""
    return _CREDENTIAL_PATTERN.sub(r"\1=<redacted>", ref)
