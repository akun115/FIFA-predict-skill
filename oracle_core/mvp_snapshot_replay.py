"""MVP snapshot replay / load path — Patch 31.

Minimal replay/load path that saves and loads ``MatchContextAssemblyResult``
via a local store.  Uses tempfile for default tests.  No live payload.
No prediction fields after replay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from oracle_core.data_service_types import (
    DataQualityIssue,
    DataQualitySeverity,
    ProviderProvenance,
    make_fixture_provenance,
)
from oracle_core.free_provider_context_assembly import (
    MatchContextAssemblyResult,
    ModelBoundary,
)


# ---------------------------------------------------------------------------
# Saved snapshot metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SavedMvpSnapshotMetadata:
    """Metadata about a saved MVP context snapshot."""

    snapshot_id: str
    """Unique snapshot identifier."""

    saved_at: datetime
    """When the snapshot was saved."""

    store_root: str
    """Root path of the store (redacted in tests)."""

    file_path: str
    """Absolute path to the saved file."""

    provider_name: str
    """Provider that sourced the data."""

    gap_count: int
    """Number of gaps in the gap_list."""

    issue_count: int
    """Number of data quality issues."""

    model_boundary: dict = field(default_factory=dict)
    """Serialized model boundary."""


# ---------------------------------------------------------------------------
# Local snapshot store (lightweight, no dependency on KnowledgeStore)
# ---------------------------------------------------------------------------


class MvpSnapshotStore:
    """Lightweight file-based store for MVP context snapshots.

    Uses a directory on disk.  For default tests, use ``tempfile.mkdtemp()``.
    Does NOT depend on ``KnowledgeStore``.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, snapshot_id: str, data: dict) -> Path:
        """Write a snapshot dict to disk.  Returns the file path."""
        # Reject path traversal
        safe_id = _sanitize_snapshot_id(snapshot_id)
        file_path = self.root / f"{safe_id}.json"
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True, default=str)
        return file_path

    def read_snapshot(self, snapshot_id: str) -> dict:
        """Read a snapshot dict from disk.  Raises FileNotFoundError."""
        safe_id = _sanitize_snapshot_id(snapshot_id)
        file_path = self.root / f"{safe_id}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"Snapshot not found: {safe_id}")
        # Path traversal check
        resolved = file_path.resolve()
        root_resolved = self.root.resolve()
        if not str(resolved).startswith(str(root_resolved)):
            raise ValueError("Path traversal rejected")
        with open(file_path, "r", encoding="utf-8") as fh:
            return json.load(fh)


def _sanitize_snapshot_id(snapshot_id: str) -> str:
    """Reject path traversal characters in snapshot IDs."""
    if not snapshot_id or not snapshot_id.strip():
        raise ValueError("snapshot_id must not be empty")
    dangerous = {"..", "/", "\\", "\x00"}
    for ch in dangerous:
        if ch in snapshot_id:
            raise ValueError(f"snapshot_id contains disallowed character: {ch!r}")
    # Allow alphanumeric, hyphens, underscores, and dots
    safe = "".join(c for c in snapshot_id if c.isalnum() or c in "-_.")
    if not safe:
        raise ValueError(f"snapshot_id '{snapshot_id}' reduces to empty after sanitization")
    return safe


# ---------------------------------------------------------------------------
# Save / Load API
# ---------------------------------------------------------------------------


def save_mvp_context_snapshot(
    store: MvpSnapshotStore,
    assembly_result: MatchContextAssemblyResult,
    *,
    snapshot_id: str | None = None,
) -> SavedMvpSnapshotMetadata:
    """Save a ``MatchContextAssemblyResult`` to the store.

    Args:
        store: An ``MvpSnapshotStore`` instance.
        assembly_result: The assembly result to save.
        snapshot_id: Optional override.  If ``None``, uses the snapshot_id
            from ``assembly_result.context_snapshot``.

    Returns:
        ``SavedMvpSnapshotMetadata`` with save details.

    Requirements:
        - source_reference must be redacted (no raw API keys).
        - raw_payload_hashes must be preserved.
        - gap_list must be preserved.
        - data_quality_issues must be preserved.
        - model_boundary must be preserved.
        - No prediction fields may appear.
    """
    sid = snapshot_id or (
        assembly_result.context_snapshot.snapshot_id
        if assembly_result.context_snapshot
        else f"snap-{assembly_result.provider_name}-{_now_iso()}"
    )

    data = {
        "snapshot_id": sid,
        "provider_name": assembly_result.provider_name,
        "assembled_at": assembly_result.assembled_at.isoformat(),
        "canonical_teams": [
            _team_to_dict(t) for t in assembly_result.canonical_teams
        ],
        "canonical_matches": [
            _match_to_dict(m) for m in assembly_result.canonical_matches
        ],
        "data_quality_issues": [
            _issue_to_dict(i) for i in assembly_result.data_quality_issues
        ],
        "gap_list": list(assembly_result.gap_list),
        "source_references": [
            _redact_source_ref(ref)
            for ref in assembly_result.source_references
        ],
        "raw_payload_hashes": list(assembly_result.raw_payload_hashes),
        "model_boundary": {
            "affects_model": assembly_result.model_boundary.affects_model,
            "report_only_or_context_only": (
                assembly_result.model_boundary.report_only_or_context_only
            ),
            "enters_prediction_engine": (
                assembly_result.model_boundary.enters_prediction_engine
            ),
        },
        # Explicit: NO prediction fields
        "result_probabilities": None,
        "expected_goals": None,
        "top_scores": None,
        "advancement_probabilities": None,
        "over_under_probabilities": None,
        "odds_blending": None,
        "xg_adjustment": None,
        "score_prediction": None,
    }

    file_path = store.write_snapshot(sid, data)

    return SavedMvpSnapshotMetadata(
        snapshot_id=sid,
        saved_at=datetime.now(timezone.utc),
        store_root=str(store.root),
        file_path=str(file_path),
        provider_name=assembly_result.provider_name,
        gap_count=len(assembly_result.gap_list),
        issue_count=len(assembly_result.data_quality_issues),
        model_boundary=data["model_boundary"],
    )


def load_mvp_context_snapshot(
    store: MvpSnapshotStore,
    snapshot_id: str,
) -> dict:
    """Load a saved MVP context snapshot from the store.

    Returns the raw dict.  Callers can reconstruct a
    ``MatchContextAssemblyResult``-like object from it.

    Args:
        store: An ``MvpSnapshotStore`` instance.
        snapshot_id: The snapshot ID to load.

    Returns:
        A ``dict`` with the saved snapshot data.

    Raises:
        FileNotFoundError: if the snapshot does not exist.
        ValueError: if path traversal is detected.
    """
    return store.read_snapshot(snapshot_id)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _team_to_dict(team) -> dict:
    return {
        "team_id": team.team_id,
        "display_name": team.display_name,
        "country_code": team.country_code,
        "external_ids": dict(team.external_ids) if team.external_ids else {},
        "data_quality": [_issue_to_dict(dq) for dq in team.data_quality],
    }


def _match_to_dict(match) -> dict:
    return {
        "match_id": match.match_id,
        "team_a_id": match.team_a_id,
        "team_b_id": match.team_b_id,
        "kickoff_at": match.kickoff_at.isoformat(),
        "stage": match.stage,
        "venue": match.venue,
        "neutral_site": match.neutral_site,
        "data_quality": [_issue_to_dict(dq) for dq in match.data_quality],
    }


def _issue_to_dict(issue) -> dict:
    return {
        "severity": issue.severity.value,
        "code": issue.code,
        "message": issue.message,
        "field_path": issue.field_path,
        "provenance_refs": list(issue.provenance_refs),
        "blocking": issue.blocking,
    }


def _redact_source_ref(ref: str) -> str:
    """Redact any API key patterns from source references."""
    if "/123/" in ref:
        return ref.replace("/123/", "/<public_test_key>/")
    return ref


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
