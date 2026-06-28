"""Leakage-free pre-match Elo baseline."""

from __future__ import annotations

from dataclasses import dataclass

from .types import HistoricalMatch, TournamentCategory


@dataclass(frozen=True)
class PreMatchElo:
    match: HistoricalMatch
    home_elo: float
    away_elo: float
    probabilities: dict[str, float]


def _expected(home: float, away: float, advantage: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(home + advantage - away) / 400.0))


def _probabilities(expected_home: float, draw_probability: float) -> dict[str, float]:
    if not 0 <= draw_probability < 1:
        raise ValueError("draw_probability must be in [0, 1)")
    decisive = 1.0 - draw_probability
    return {
        "team_a_win": decisive * expected_home,
        "draw": draw_probability,
        "team_b_win": decisive * (1.0 - expected_home),
    }


def build_pre_match_elo(
    matches: tuple[HistoricalMatch, ...] | list[HistoricalMatch],
    *,
    initial_rating: float = 1500.0,
    k_factor: float = 20.0,
    home_advantage: float = 80.0,
    draw_probability: float = 0.25,
    friendly_multiplier: float = 0.5,
) -> tuple[PreMatchElo, ...]:
    if any(matches[index].date > matches[index + 1].date for index in range(len(matches) - 1)):
        raise ValueError("matches must be chronological")
    ratings: dict[str, float] = {}
    rows: list[PreMatchElo] = []
    for match in matches:
        home = ratings.get(match.home_team, initial_rating)
        away = ratings.get(match.away_team, initial_rating)
        advantage = 0.0 if match.neutral else home_advantage
        expected_home = _expected(home, away, advantage)
        rows.append(
            PreMatchElo(
                match, home, away, _probabilities(expected_home, draw_probability)
            )
        )
        actual_home = (
            1.0 if match.home_score > match.away_score
            else 0.0 if match.home_score < match.away_score
            else 0.5
        )
        multiplier = (
            friendly_multiplier
            if match.category is TournamentCategory.FRIENDLY
            else 1.0
        )
        change = k_factor * multiplier * (actual_home - expected_home)
        ratings[match.home_team] = home + change
        ratings[match.away_team] = away - change
    return tuple(rows)
