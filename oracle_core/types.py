"""Deterministic football score probabilities.

Default coefficients are provisional priors and are not claimed as calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Mapping


# ---------- team incentive labels ----------


class TeamIncentive(str, Enum):
    MUST_WIN_FOR_TOP2 = "must_win_for_top2"
    MUST_WIN_TO_STAY_ALIVE = "must_win_to_stay_alive"
    DRAW_SUFFICIENT_FOR_TOP2 = "draw_sufficient_for_top2"
    DRAW_REQUIRES_HELP = "draw_requires_help"
    THIRD_PLACE_DEPENDENT = "third_place_dependent"
    TOP_SPOT_AT_STAKE = "top_spot_at_stake"
    ALREADY_QUALIFIED_ROTATION_RISK = "already_qualified_rotation_risk"
    ELIMINATED_LOW_PRESSURE = "eliminated_low_pressure"
    NO_CLEAR_INCENTIVE = "no_clear_incentive"


@dataclass(frozen=True)
class IncentiveResult:
    primary_incentive: TeamIncentive
    incentive_flags: tuple[str, ...]
    intensity: float | None
    description: str


# ---------- tournament state types ----------


@dataclass(frozen=True)
class GroupDefinition:
    group_name: str
    teams: tuple[str, ...]


@dataclass(frozen=True)
class ScheduledMatch:
    match_id: str
    group_or_round: str
    matchday: int
    team_a: str
    team_b: str
    kickoff_utc: str
    venue: str
    neutral_site: bool
    score: tuple[int, int] | None = None
    stats: dict | None = None

    @property
    def is_completed(self) -> bool:
        return self.score is not None

    @property
    def total_goals(self) -> int | None:
        if self.score is None:
            return None
        return self.score[0] + self.score[1]


@dataclass(frozen=True)
class TournamentRules:
    tournament_name: str
    group_stage_format: str
    total_groups: int
    teams_per_group: int
    matchdays_per_group: int
    top_n_per_group: int
    best_third_place_count: int
    total_advancing: int
    group_tiebreakers: tuple[str, ...]
    best_third_place_criteria: tuple[str, ...]


@dataclass(frozen=True)
class GroupStandingsRow:
    position: int
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int


@dataclass(frozen=True)
class GroupTable:
    group_name: str
    rows: tuple[GroupStandingsRow, ...]


@dataclass(frozen=True)
class TournamentState:
    match_id: str
    generated_at: str
    stale_after: str
    state_mode: str
    state_timestamp_utc: str
    excluded_matches: tuple[str, ...]
    data_sources: dict[str, object]
    match_context: dict[str, object]
    group_standings_before_match: GroupTable | None
    simultaneous_group_matches: tuple[dict[str, str], ...]
    qualification_scenarios: dict[str, object]
    team_a_incentive: IncentiveResult
    team_b_incentive: IncentiveResult
    knockout_edge_if_known: dict | None
    data_quality: dict | None = None


@dataclass(frozen=True)
class ModelConfig:
    version: str = "provisional-v1"
    base_goal_rate: float = 1.35
    attack_weight: float = 0.16
    defense_weight: float = 0.14
    elo_weight: float = 0.20
    form_weight: float = 0.10
    availability_weight: float = 0.10
    home_log_advantage: float = 0.12
    dixon_coles_rho: float = -0.08
    min_expected_goals: float = 0.15
    max_expected_goals: float = 5.0
    tail_tolerance: float = 1e-8
    min_score_grid: int = 6
    max_score_grid: int = 30

    def __post_init__(self) -> None:
        numeric = (
            self.base_goal_rate, self.attack_weight, self.defense_weight,
            self.elo_weight, self.form_weight, self.availability_weight,
            self.home_log_advantage, self.dixon_coles_rho,
            self.min_expected_goals, self.max_expected_goals,
            self.tail_tolerance,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("model configuration values must be finite")
        if self.base_goal_rate <= 0:
            raise ValueError("base_goal_rate must be positive")
        if not 0 < self.min_expected_goals < self.max_expected_goals:
            raise ValueError("expected-goal bounds are invalid")
        if not 0 < self.tail_tolerance < 1:
            raise ValueError("tail_tolerance must be between zero and one")
        if self.min_score_grid < 1 or self.max_score_grid < self.min_score_grid:
            raise ValueError("score-grid bounds are invalid")


@dataclass(frozen=True)
class TeamSnapshot:
    name: str
    elo: float
    attack: float
    defense: float
    form: float = 0.0
    availability: float = 0.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("team name must not be empty")
        values = (self.elo, self.attack, self.defense, self.form, self.availability)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("team values must be finite")
        if not 0 <= self.attack <= 100 or not 0 <= self.defense <= 100:
            raise ValueError("attack and defense ratings must be between 0 and 100")
        if not -1 <= self.form <= 1 or not -1 <= self.availability <= 1:
            raise ValueError("form and availability must be between -1 and 1")


@dataclass(frozen=True)
class Prediction:
    team_a: str
    team_b: str
    expected_goals: tuple[float, float]
    result_probabilities: Mapping[str, float]
    score_probabilities: Mapping[tuple[int, int], float]
    top_scores: tuple[tuple[tuple[int, int], float], ...]
    model_version: str
    model_status: str = "provisional"
    over_under: Mapping[str, float] = field(default_factory=dict)
    tournament_context: Mapping[str, Any] | None = None
    advancement_probabilities: dict | None = None
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self, *, include_score_matrix: bool = False) -> dict:
        payload = {
            "team_a": self.team_a,
            "team_b": self.team_b,
            "expected_goals": list(self.expected_goals),
            "result_probabilities": dict(self.result_probabilities),
            "top_scores": [
                {"score": list(score), "probability": probability}
                for score, probability in self.top_scores
            ],
            "over_under": dict(self.over_under),
            "tournament_context": (
                dict(self.tournament_context)
                if self.tournament_context is not None
                else None
            ),
            "advancement_probabilities": (
                dict(self.advancement_probabilities)
                if self.advancement_probabilities is not None
                else None
            ),
            "model_version": self.model_version,
            "model_status": self.model_status,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
        }
        if include_score_matrix:
            payload["score_probabilities"] = {
                f"{home}-{away}": probability
                for (home, away), probability in self.score_probabilities.items()
            }
        return payload
