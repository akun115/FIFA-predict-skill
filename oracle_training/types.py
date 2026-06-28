"""Immutable training-domain values."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class TournamentCategory(str, Enum):
    WORLD_CUP = "world_cup"
    WORLD_CUP_QUALIFIER = "world_cup_qualifier"
    CONTINENTAL_FINAL = "continental_final"
    CONTINENTAL_QUALIFIER = "continental_qualifier"
    NATIONS_LEAGUE = "nations_league"
    FRIENDLY = "friendly"
    OTHER = "other"


@dataclass(frozen=True)
class HistoricalMatch:
    date: date
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    tournament: str
    neutral: bool
    category: TournamentCategory
    source_row: int
    source_id: str

    def __post_init__(self) -> None:
        if not self.home_team.strip() or not self.away_team.strip():
            raise ValueError("team names must not be empty")
        if self.home_team == self.away_team:
            raise ValueError("teams must differ")
        if self.home_score < 0 or self.away_score < 0:
            raise ValueError("scores must be non-negative")
        if self.source_row < 1 or not self.source_id:
            raise ValueError("source identity is invalid")

    def to_dict(self) -> dict:
        value = asdict(self)
        value["date"] = self.date.isoformat()
        value["category"] = self.category.value
        return value


@dataclass(frozen=True)
class DataManifest:
    source_url: str
    source_sha256: str
    normalized_sha256: str
    as_of: str
    source_rows: int
    accepted_rows: int
    rejections: dict[str, int]
    min_date: str | None
    max_date: str | None
    team_count: int
    taxonomy_version: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FoldDefinition:
    test_year: int
    training_end: str
    training_count: int
    test_count: int
    partial: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ModelCandidate:
    version: str
    model: dict[str, Any]
    converged: bool
    objective: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EvaluationReport:
    models: dict[str, dict[str, Any]]
    folds: tuple[FoldDefinition, ...]
    gates: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "models": self.models,
            "folds": [fold.to_dict() for fold in self.folds],
            "gates": dict(self.gates),
        }
