"""Deterministic data-quality assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from .domain import DataState


@dataclass(frozen=True)
class QualityReport:
    state: DataState
    missing: tuple[str, ...]
    stale: tuple[str, ...]
    conflicts: tuple[str, ...]
    provider_errors: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    as_of: datetime

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "missing": list(self.missing),
            "stale": list(self.stale),
            "conflicts": list(self.conflicts),
            "provider_errors": list(self.provider_errors),
            "blocked_reasons": list(self.blocked_reasons),
            "as_of": self.as_of.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


def assess_quality(
    *,
    required: set[str],
    available: set[str],
    as_of: datetime,
    stale: set[str] | None = None,
    conflicts: tuple[str, ...] = (),
    provider_errors: tuple[str, ...] = (),
    blocked: tuple[str, ...] = (),
    observed_at: Mapping[str, datetime] | None = None,
    used_cache: bool = False,
) -> QualityReport:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    accepted = set(available)
    reasons = list(blocked)
    for field, timestamp in (observed_at or {}).items():
        if timestamp > as_of and field in required:
            accepted.discard(field)
            reasons.append(f"{field} observed after cutoff")
    missing = tuple(sorted(required - accepted))
    stale_fields = tuple(sorted(stale or set()))
    if reasons:
        state = DataState.BLOCKED
    elif missing or conflicts:
        state = DataState.PARTIAL
    elif stale_fields:
        state = DataState.STALE
    elif used_cache:
        state = DataState.CACHED
    else:
        state = DataState.FRESH
    return QualityReport(
        state, missing, stale_fields, tuple(conflicts), tuple(provider_errors),
        tuple(sorted(set(reasons))), as_of,
    )
