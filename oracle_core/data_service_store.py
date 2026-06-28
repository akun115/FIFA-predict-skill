"""Local store and snapshot writer/reader — Data Service v1.

Patch 16 — deterministic JSON persistence for raw provider fetch results
and MatchContextSnapshot.  No live providers.  No network.  No prediction
integration.  All tests use temporary directories.

Patch 16.1 — path segment validation, root containment, timestamp hardening.

Serialization rules (Patch 16 + 16.1):
  - datetime → explicit UTC ISO-8601 string (no default=str fallback).
  - dict keys sorted for deterministic output (sort_keys=True).
  - Snapshot writes are immutable — duplicate write raises error.
  - No prediction output keys (result_probabilities, expected_goals, etc.)
    are ever stored in snapshot or raw fetch result files.
  - All path segments validated against traversal/injection.
  - All written paths enforced under root_path.
  - Timestamp sorting uses parsed aware datetime, not string comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class DataServiceStoreError(RuntimeError):
    """Base error for local store operations."""


class SnapshotAlreadyExistsError(DataServiceStoreError):
    """A snapshot with the same match_id + snapshot_id already exists."""


class SnapshotNotFoundError(DataServiceStoreError):
    """The requested snapshot was not found in the store."""


class RawFetchResultNotFoundError(DataServiceStoreError):
    """The requested raw fetch result was not found in the store."""


class InvalidStorePayloadError(DataServiceStoreError):
    """Payload contains a value that cannot be safely serialized to JSON,
    or a path segment / timestamp is invalid."""


# ---------------------------------------------------------------------------
# Path segment validation (Patch 16.1)
# ---------------------------------------------------------------------------

# Allowed: A-Z a-z 0-9 _ - .  (but standalone . and .. are rejected separately)
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _validate_path_segment(value: str, field_name: str) -> str:
    """Validate a dynamic path segment for safety.

    Rejects:
      - Empty strings
      - Standalone ``.`` or ``..`` (directory traversal)
      - ``/`` or ``\\`` (path separators)
      - Characters outside ``[A-Za-z0-9_.-]`` (control chars, spaces, NUL, etc.)

    Returns *value* unchanged on success (for chaining).
    """
    if not value or not value.strip():
        raise InvalidStorePayloadError(
            f"{field_name} must not be empty: {value!r}"
        )
    if value in (".", ".."):
        raise InvalidStorePayloadError(
            f"{field_name} must not be '{value}' (path traversal rejected)"
        )
    if not _PATH_SEGMENT_RE.match(value):
        raise InvalidStorePayloadError(
            f"{field_name} contains invalid characters: {value!r}"
        )
    return value


def _validate_raw_payload_hash(value: str, field_name: str = "raw_payload_hash") -> str:
    """Validate that *value* is a 64-character lowercase hex string."""
    if len(value) != 64:
        raise InvalidStorePayloadError(
            f"{field_name} must be 64 characters, got {len(value)}: {value!r}"
        )
    if not re.match(r"^[0-9a-f]{64}$", value):
        raise InvalidStorePayloadError(
            f"{field_name} must be 64-char hex, got: {value!r}"
        )
    return value


def _validate_capability_segment(value: str) -> str:
    """Validate that *value* is a known ``ProviderCapability`` value.

    This prevents arbitrary strings from being used as directory names
    in the raw fetch result store.
    """
    from oracle_core.data_service_providers import ProviderCapability
    try:
        ProviderCapability(value)
    except ValueError:
        raise InvalidStorePayloadError(
            f"capability must be a valid ProviderCapability value, got: {value!r}"
        ) from None
    return value


# ---------------------------------------------------------------------------
# Root containment validation (Patch 16.1)
# ---------------------------------------------------------------------------


def _ensure_under_root(path: Path, root: Path) -> Path:
    """Resolve *path* and verify it is under *root*.

    Raises ``InvalidStorePayloadError`` if the resolved path escapes *root*.
    Returns the resolved ``Path``.
    """
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise InvalidStorePayloadError(
            f"Path escapes root: {path} resolves to {resolved}, "
            f"which is not under {root_resolved}"
        ) from None
    return resolved


# ---------------------------------------------------------------------------
# Serialization helpers — explicit, no silent fallback
# ---------------------------------------------------------------------------


def _datetime_to_iso(dt: Any) -> str:
    """Convert a datetime to ISO-8601 string.  Raises on non-datetime."""
    if not isinstance(dt, datetime):
        raise InvalidStorePayloadError(
            f"Expected datetime, got {type(dt).__name__}: {dt!r}"
        )
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise InvalidStorePayloadError(f"datetime must be timezone-aware: {dt!r}")
    return dt.isoformat()


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string to a timezone-aware datetime.

    Raises ``InvalidStorePayloadError`` if *value* cannot be parsed.
    """
    if not isinstance(value, str):
        raise InvalidStorePayloadError(
            f"Expected ISO timestamp string, got {type(value).__name__}: {value!r}"
        )
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise InvalidStorePayloadError(
            f"Cannot parse ISO timestamp: {value!r}: {exc}"
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _json_safe(value: Any, path: str = "$") -> Any:
    """Recursively check that *value* is JSON-safe.

    Allowed: None, bool, int, float, str, list, tuple, dict (str keys).
    Raises ``InvalidStorePayloadError`` for anything else (including
    ``datetime``, ``set``, ``bytes``, custom objects).

    Callers must convert ``datetime`` to ISO-8601 strings *before* calling
    this function or calling ``json.dumps``.
    """
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        result: list[Any] = []
        for i, item in enumerate(value):
            result.append(_json_safe(item, f"{path}[{i}]"))
        return result
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, val in value.items():
            if not isinstance(key, str):
                raise InvalidStorePayloadError(
                    f"Non-string key {key!r} at {path}"
                )
            result[key] = _json_safe(val, f"{path}.{key}")
        return result
    raise InvalidStorePayloadError(
        f"Non-JSON-safe type {type(value).__name__} at {path}: {value!r}"
    )


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Write *data* as deterministic JSON (sorted keys, indent=2).

    *data* must already be JSON-safe (datetimes converted to ISO strings,
    no custom objects).  Raises ``InvalidStorePayloadError`` if any value
    is not JSON-safe.
    """
    safe = _json_safe(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(safe, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(raw + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    """Read and parse a JSON file.  Returns a plain dict."""
    if not path.exists():
        raise FileNotFoundError(f"Store file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise InvalidStorePayloadError(
            f"Expected JSON object at {path}, got {type(data).__name__}"
        )
    return data


# ---------------------------------------------------------------------------
# DataServiceLocalStore
# ---------------------------------------------------------------------------


@dataclass
class DataServiceLocalStore:
    """Isolated local store for Data Service v1.

    Persists raw provider fetch results and immutable MatchContextSnapshot
    objects as deterministic JSON files under *root_path*.

    All I/O is constrained to *root_path* — this store never touches
    production ``data/``, prediction logs, or any other directory.
    Tests use ``tempfile.TemporaryDirectory``.

    Patch 16.1 — all path segments are validated; root containment enforced;
    timestamp sorting uses parsed aware datetime.
    """

    root_path: Path
    """Root directory for all store data.  Created on first write."""

    # ------------------------------------------------------------------
    # Raw provider fetch results
    # ------------------------------------------------------------------

    # ── Path helpers ──

    def _raw_dir(
        self,
        provider_name: str,
        capability: str,
    ) -> Path:
        _validate_path_segment(provider_name, "provider_name")
        _validate_capability_segment(capability)
        p = self.root_path / "raw" / provider_name / capability
        _ensure_under_root(p, self.root_path)
        return p

    def _raw_path(
        self,
        provider_name: str,
        capability: str,
        raw_payload_hash: str,
    ) -> Path:
        _validate_raw_payload_hash(raw_payload_hash)
        p = self._raw_dir(provider_name, capability) / f"{raw_payload_hash}.json"
        _ensure_under_root(p, self.root_path)
        return p

    # ── Write ──

    def write_raw_fetch_result(self, result: Any) -> Path:
        """Persist a raw provider fetch result as a JSON file.

        *result* must have ``to_dict()`` (e.g. ``ProviderFetchResult``).
        The dict must already be JSON-safe — datetimes must be ISO strings,
        not ``datetime`` objects.

        Returns the Path where the file was written.
        """
        if not hasattr(result, "to_dict"):
            raise InvalidStorePayloadError(
                "result must have to_dict() method"
            )
        data = result.to_dict()
        # Ensure datetimes are strings
        data = _canonicalize_store_dict(data)
        _json_safe(data)

        provider_name = data["provider_name"]
        capability = data["capability"]
        raw_hash = data["raw_payload_hash"]

        path = self._raw_path(provider_name, capability, raw_hash)
        _write_json(path, data)
        return path

    # ── Read ──

    def read_raw_fetch_result(
        self,
        provider_name: str,
        capability: str,
        raw_payload_hash: str,
    ) -> dict[str, Any]:
        """Read a raw fetch result from the store.  Returns a canonical dict.

        The returned dict has the same shape as ``ProviderFetchResult.to_dict()``.
        ISO datetime strings are NOT parsed back into ``datetime`` objects.
        """
        path = self._raw_path(provider_name, capability, raw_payload_hash)
        try:
            return _read_json(path)
        except FileNotFoundError:
            raise RawFetchResultNotFoundError(
                f"Raw fetch result not found: provider={provider_name}, "
                f"capability={capability}, hash={raw_payload_hash}"
            ) from None

    # ── List ──

    def list_raw_fetch_results(
        self,
        *,
        provider_name: str | None = None,
        capability: str | None = None,
    ) -> list[dict[str, str]]:
        """List stored raw fetch results, optionally filtered.

        Returns a list of metadata dicts with keys:
        ``provider_name``, ``capability``, ``raw_payload_hash``, ``path``.
        """
        results: list[dict[str, str]] = []
        raw_root = self.root_path / "raw"
        if not raw_root.exists():
            return results

        for pn_dir in sorted(raw_root.iterdir()):
            if not pn_dir.is_dir():
                continue
            pn = pn_dir.name
            if provider_name is not None and pn != provider_name:
                continue
            for cap_dir in sorted(pn_dir.iterdir()):
                if not cap_dir.is_dir():
                    continue
                cap = cap_dir.name
                if capability is not None and cap != capability:
                    continue
                for json_file in sorted(cap_dir.glob("*.json")):
                    rhash = json_file.stem
                    results.append({
                        "provider_name": pn,
                        "capability": cap,
                        "raw_payload_hash": rhash,
                        "path": str(json_file.relative_to(self.root_path)),
                    })
        return results

    # ------------------------------------------------------------------
    # MatchContextSnapshot writer / reader
    # ------------------------------------------------------------------

    # ── Path helpers ──

    def _snapshots_dir(self, match_id: str) -> Path:
        _validate_path_segment(match_id, "match_id")
        p = self.root_path / "snapshots" / "match_context" / match_id
        _ensure_under_root(p, self.root_path)
        return p

    def _snapshot_path(self, match_id: str, snapshot_id: str) -> Path:
        _validate_path_segment(snapshot_id, "snapshot_id")
        p = self._snapshots_dir(match_id) / f"{snapshot_id}.json"
        _ensure_under_root(p, self.root_path)
        return p

    def _snapshot_index_path(self, match_id: str) -> Path:
        p = self._snapshots_dir(match_id) / "index.json"
        _ensure_under_root(p, self.root_path)
        return p

    # ── Write ──

    def write_match_context_snapshot(self, snapshot: Any) -> Path:
        """Persist a ``MatchContextSnapshot`` as an immutable JSON file.

        *snapshot* must have ``to_dict()``.  If a file with the same
        ``match_id`` + ``snapshot_id`` already exists, raises
        ``SnapshotAlreadyExistsError``.

        Also updates the snapshot index for this match_id.

        Returns the Path where the file was written.
        """
        if not hasattr(snapshot, "to_dict"):
            raise InvalidStorePayloadError(
                "snapshot must have to_dict() method"
            )
        data = snapshot.to_dict()
        data = _canonicalize_store_dict(data)
        _json_safe(data)

        match_id = data["match"]["match_id"]
        snapshot_id = data["snapshot_id"]

        path = self._snapshot_path(match_id, snapshot_id)
        if path.exists():
            raise SnapshotAlreadyExistsError(
                f"Snapshot already exists: match_id={match_id}, "
                f"snapshot_id={snapshot_id}"
            )

        _write_json(path, data)
        self._update_snapshot_index(match_id)
        return path

    # ── Read ──

    def read_match_context_snapshot(
        self,
        match_id: str,
        snapshot_id: str,
    ) -> dict[str, Any]:
        """Read a MatchContextSnapshot from the store.  Returns a canonical dict.

        ISO datetime strings are NOT parsed back into ``datetime`` objects.
        """
        path = self._snapshot_path(match_id, snapshot_id)
        try:
            return _read_json(path)
        except FileNotFoundError:
            raise SnapshotNotFoundError(
                f"Snapshot not found: match_id={match_id}, snapshot_id={snapshot_id}"
            ) from None

    # ── List ──

    def list_match_context_snapshots(
        self,
        match_id: str,
    ) -> list[dict[str, Any]]:
        """List all snapshots for a match, ordered by snapshot_created_at.

        Returns a list of metadata dicts with keys from the index.
        Returns empty list if no snapshots exist for this match_id.

        Patch 16.1: sorting uses parsed aware datetime, not string comparison.
        """
        index_path = self._snapshot_index_path(match_id)
        if not index_path.exists():
            return []
        data = _read_json(index_path)
        snapshots = list(data.get("snapshots", []))
        # Ensure sorted by parsed aware datetime (Patch 16.1)
        snapshots.sort(key=_index_entry_sort_key)
        return snapshots

    # ── Latest ──

    def latest_match_context_snapshot(
        self,
        match_id: str,
    ) -> dict[str, Any] | None:
        """Return the latest snapshot dict for *match_id*, or None.

        "Latest" is determined by ``snapshot_created_at``, parsed as an
        aware datetime so that different timezone offsets are compared
        correctly by real instant, not string value.
        """
        snapshots = self.list_match_context_snapshots(match_id)
        if not snapshots:
            return None
        # list is already sorted by _index_entry_sort_key
        latest_meta = snapshots[-1]
        return self.read_match_context_snapshot(
            match_id, latest_meta["snapshot_id"]
        )

    # ── Index maintenance ──

    def _update_snapshot_index(self, match_id: str) -> None:
        """Rebuild the snapshot index for *match_id*, sorted by created_at.

        Patch 16.1: timestamps are parsed as aware datetimes for sorting;
        invalid timestamps raise ``InvalidStorePayloadError`` instead of
        being silently skipped.
        """
        snap_dir = self._snapshots_dir(match_id)
        snap_dir.mkdir(parents=True, exist_ok=True)

        entries: list[dict[str, Any]] = []
        for json_file in sorted(snap_dir.glob("*.json")):
            if json_file.name == "index.json":
                continue
            snap_data = _read_json(json_file)
            created_at_str = snap_data.get("snapshot_created_at")
            if not created_at_str:
                raise InvalidStorePayloadError(
                    f"Snapshot {json_file.name} is missing snapshot_created_at"
                )
            # Validate timestamp is parseable (raises on invalid)
            _parse_iso(created_at_str)

            entries.append({
                "snapshot_id": snap_data["snapshot_id"],
                "snapshot_version": snap_data.get("snapshot_version", "1.0.0"),
                "snapshot_created_at": created_at_str,
                "match_id": snap_data["match"]["match_id"],
            })

        entries.sort(key=_index_entry_sort_key)

        index_data = {"match_id": match_id, "snapshots": entries}
        index_path = self._snapshot_index_path(match_id)
        _write_json(index_path, index_data)


# ---------------------------------------------------------------------------
# Index sorting helper (Patch 16.1)
# ---------------------------------------------------------------------------


def _index_entry_sort_key(entry: dict[str, Any]) -> datetime:
    """Parse ``snapshot_created_at`` as an aware datetime for sorting.

    Uses ``_parse_iso`` so that different timezone offsets are compared
    by real UTC instant, not by string lexical order.
    """
    return _parse_iso(entry["snapshot_created_at"])


# ---------------------------------------------------------------------------
# Canonicalization helper
# ---------------------------------------------------------------------------


def _canonicalize_store_dict(data: Any) -> Any:
    """Recursively walk *data*, converting ``datetime`` objects to ISO strings.

    All other types are passed through unchanged.  Call ``_json_safe`` after
    this to verify no non-JSON types remain.
    """
    if data is None:
        return None
    if isinstance(data, datetime):
        return _datetime_to_iso(data)
    if isinstance(data, (bool, int, float, str)):
        return data
    if isinstance(data, (list, tuple)):
        return [_canonicalize_store_dict(item) for item in data]
    if isinstance(data, dict):
        return {str(key): _canonicalize_store_dict(val) for key, val in data.items()}
    # For types with to_dict()
    if hasattr(data, "to_dict"):
        return _canonicalize_store_dict(data.to_dict())
    raise InvalidStorePayloadError(
        f"Cannot canonicalize type {type(data).__name__}: {data!r}"
    )
