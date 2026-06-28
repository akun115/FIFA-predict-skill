"""Normalized immutable football data contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class DataState(str, Enum):
    FRESH = "fresh"
    CACHED = "cached"
    STALE = "stale"
    PARTIAL = "partial"
    BLOCKED = "blocked"


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Provenance:
    provider: str
    provider_object_id: str
    retrieved_at: datetime
    observed_at: datetime | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.provider_object_id.strip():
            raise ValueError("provider and provider_object_id must not be empty")
        _require_aware(self.retrieved_at, "retrieved_at")
        if self.observed_at is not None:
            _require_aware(self.observed_at, "observed_at")

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "provider_object_id": self.provider_object_id,
            "retrieved_at": _iso(self.retrieved_at),
            "observed_at": _iso(self.observed_at),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MatchRecord:
    match_id: str
    competition_id: str
    kickoff: datetime
    home_team: str
    away_team: str
    provenance: Provenance
    status: str = "scheduled"
    home_score: int | None = None
    away_score: int | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.match_id, "match_id"),
            (self.competition_id, "competition_id"),
            (self.home_team, "home_team"),
            (self.away_team, "away_team"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        _require_aware(self.kickoff, "kickoff")
        if self.home_team == self.away_team:
            raise ValueError("home_team and away_team must differ")
        if (self.home_score is None) != (self.away_score is None):
            raise ValueError("scores must both be set or both be absent")
        if self.home_score is not None and (self.home_score < 0 or self.away_score < 0):
            raise ValueError("scores must be non-negative")

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "competition_id": self.competition_id,
            "kickoff": _iso(self.kickoff),
            "home_team": self.home_team,
            "away_team": self.away_team,
            "status": self.status,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "provenance": self.provenance.to_dict(),
        }
