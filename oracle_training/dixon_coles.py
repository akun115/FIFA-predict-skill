"""Weighted Dixon-Coles fitting for national-team scores."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

from .elo import build_pre_match_elo
from .types import HistoricalMatch, ModelCandidate, TournamentCategory


@dataclass(frozen=True)
class FitConfig:
    decay_per_year: float = 0.15
    friendly_weight: float = 0.5
    l2: float = 0.1
    include_elo: bool = False

    def __post_init__(self) -> None:
        if self.decay_per_year < 0 or not 0 < self.friendly_weight <= 1 or self.l2 < 0:
            raise ValueError("invalid fit configuration")


def match_weight(
    match: HistoricalMatch,
    cutoff: date,
    *,
    decay_per_year: float,
    friendly_weight: float,
) -> float:
    age_days = max(0, (cutoff - match.date).days)
    weight = math.exp(-decay_per_year * age_days / 365.25)
    if match.category is TournamentCategory.FRIENDLY:
        weight *= friendly_weight
    return weight


def _tau(home: int, away: int, lambda_home: float, lambda_away: float, rho: float) -> float:
    if home == 0 and away == 0:
        return 1.0 - lambda_home * lambda_away * rho
    if home == 0 and away == 1:
        return 1.0 + lambda_home * rho
    if home == 1 and away == 0:
        return 1.0 + lambda_away * rho
    if home == 1 and away == 1:
        return 1.0 - rho
    return 1.0


def fit_dixon_coles(
    matches: tuple[HistoricalMatch, ...],
    *,
    cutoff: date,
    version: str,
    config: FitConfig | None = None,
) -> ModelCandidate:
    cfg = config or FitConfig()
    if not matches:
        raise ValueError("at least one training match is required")
    if any(match.date > cutoff for match in matches):
        raise ValueError("training match occurs after cutoff")
    if any(matches[index].date > matches[index + 1].date for index in range(len(matches) - 1)):
        raise ValueError("training matches must be chronological")

    teams = sorted({team for match in matches for team in (match.home_team, match.away_team)})
    if len(teams) < 2:
        raise ValueError("at least two teams are required")
    team_index = {team: index for index, team in enumerate(teams)}
    categories = sorted(
        {match.category.value for match in matches if match.category.value != "other"}
    )
    category_index = {name: index for index, name in enumerate(categories)}
    n_teams = len(teams)
    n_free = n_teams - 1
    attack_start = 3
    defense_start = attack_start + n_free
    category_start = defense_start + n_free
    elo_index = category_start + len(categories) if cfg.include_elo else None
    size = category_start + len(categories) + int(cfg.include_elo)

    home_team = np.array([team_index[m.home_team] for m in matches], dtype=np.intp)
    away_team = np.array([team_index[m.away_team] for m in matches], dtype=np.intp)
    home_score = np.array([m.home_score for m in matches], dtype=float)
    away_score = np.array([m.away_score for m in matches], dtype=float)
    home_site = np.array([not m.neutral for m in matches], dtype=float)
    category = np.array(
        [category_index.get(m.category.value, -1) for m in matches], dtype=np.intp
    )
    weights = np.array([
        match_weight(
            m,
            cutoff,
            decay_per_year=cfg.decay_per_year,
            friendly_weight=cfg.friendly_weight,
        )
        for m in matches
    ])
    if cfg.include_elo:
        elo_rows = build_pre_match_elo(
            matches, friendly_multiplier=cfg.friendly_weight
        )
        elo_features = np.array([
            (row.home_elo - row.away_elo) / 400.0 for row in elo_rows
        ])
        final_elo_ratings: dict[str, float] = {}
        for row in elo_rows:
            match = row.match
            expected_home = row.probabilities["team_a_win"] / 0.75
            actual_home = (
                1.0 if match.home_score > match.away_score
                else 0.0 if match.home_score < match.away_score
                else 0.5
            )
            multiplier = (
                cfg.friendly_weight
                if match.category is TournamentCategory.FRIENDLY
                else 1.0
            )
            change = 20.0 * multiplier * (actual_home - expected_home)
            final_elo_ratings[match.home_team] = row.home_elo + change
            final_elo_ratings[match.away_team] = row.away_elo - change
    else:
        elo_features = np.zeros(len(matches))
        final_elo_ratings = {}

    average_goals = float(np.sum(home_score + away_score) / (2 * len(matches)))
    initial = np.zeros(size, dtype=float)
    initial[0] = math.log(max(0.2, average_goals))
    bounds = [(-2.5, 2.0), (-1.0, 1.0), (-0.25, 0.25)]
    bounds += [(-3.0, 3.0)] * (2 * n_free)
    bounds += [(-1.0, 1.0)] * len(categories)
    if cfg.include_elo:
        bounds.append((-1.5, 1.5))

    def unpack(vector):
        attack = np.empty(n_teams)
        defense = np.empty(n_teams)
        attack[:-1] = vector[attack_start:defense_start]
        defense[:-1] = vector[defense_start:category_start]
        attack[-1] = -float(np.sum(attack[:-1]))
        defense[-1] = -float(np.sum(defense[:-1]))
        effects = np.zeros(len(categories))
        if categories:
            effects[:] = vector[category_start:category_start + len(categories)]
        elo_coefficient = float(vector[elo_index]) if elo_index is not None else 0.0
        return attack, defense, effects, elo_coefficient

    def objective_and_gradient(vector):
        intercept = float(vector[0])
        home_effect = float(vector[1])
        rho = float(vector[2])
        attack, defense, effects, elo_coefficient = unpack(vector)
        category_effect = np.zeros(len(matches))
        known_category = category >= 0
        category_effect[known_category] = effects[category[known_category]]
        log_home = (
            intercept + attack[home_team] - defense[away_team]
            + category_effect + home_effect * home_site
            + elo_coefficient * elo_features
        )
        log_away = (
            intercept + attack[away_team] - defense[home_team]
            + category_effect - elo_coefficient * elo_features
        )
        lambda_home = np.exp(log_home)
        lambda_away = np.exp(log_away)
        tau = np.ones(len(matches))
        tau_log_home = np.zeros(len(matches))
        tau_log_away = np.zeros(len(matches))
        tau_rho = np.zeros(len(matches))
        zero_zero = (home_score == 0) & (away_score == 0)
        zero_one = (home_score == 0) & (away_score == 1)
        one_zero = (home_score == 1) & (away_score == 0)
        one_one = (home_score == 1) & (away_score == 1)
        product = lambda_home * lambda_away
        tau[zero_zero] = 1.0 - product[zero_zero] * rho
        tau_log_home[zero_zero] = -product[zero_zero] * rho
        tau_log_away[zero_zero] = -product[zero_zero] * rho
        tau_rho[zero_zero] = -product[zero_zero]
        tau[zero_one] = 1.0 + lambda_home[zero_one] * rho
        tau_log_home[zero_one] = lambda_home[zero_one] * rho
        tau_rho[zero_one] = lambda_home[zero_one]
        tau[one_zero] = 1.0 + lambda_away[one_zero] * rho
        tau_log_away[one_zero] = lambda_away[one_zero] * rho
        tau_rho[one_zero] = lambda_away[one_zero]
        tau[one_one] = 1.0 - rho
        tau_rho[one_one] = -1.0
        if np.any(tau <= 0) or not np.all(np.isfinite(tau)):
            return 1e100, np.zeros_like(vector)

        log_probability = (
            -lambda_home + home_score * log_home - gammaln(home_score + 1)
            -lambda_away + away_score * log_away - gammaln(away_score + 1)
            + np.log(tau)
        )
        value = -float(np.dot(weights, log_probability))
        value += cfg.l2 * float(
            np.dot(attack, attack) + np.dot(defense, defense)
            + np.dot(effects, effects) + elo_coefficient * elo_coefficient
        )

        grad_log_home = -weights * (
            home_score - lambda_home + tau_log_home / tau
        )
        grad_log_away = -weights * (
            away_score - lambda_away + tau_log_away / tau
        )
        gradient = np.zeros_like(vector)
        gradient[0] = np.sum(grad_log_home + grad_log_away)
        gradient[1] = np.dot(grad_log_home, home_site)
        gradient[2] = -np.dot(weights, tau_rho / tau)

        attack_gradient = np.zeros(n_teams)
        defense_gradient = np.zeros(n_teams)
        np.add.at(attack_gradient, home_team, grad_log_home)
        np.add.at(attack_gradient, away_team, grad_log_away)
        np.add.at(defense_gradient, away_team, -grad_log_home)
        np.add.at(defense_gradient, home_team, -grad_log_away)
        attack_gradient += 2.0 * cfg.l2 * attack
        defense_gradient += 2.0 * cfg.l2 * defense
        gradient[attack_start:defense_start] = (
            attack_gradient[:-1] - attack_gradient[-1]
        )
        gradient[defense_start:category_start] = (
            defense_gradient[:-1] - defense_gradient[-1]
        )
        if categories:
            category_gradient = np.zeros(len(categories))
            np.add.at(
                category_gradient,
                category[known_category],
                (grad_log_home + grad_log_away)[known_category],
            )
            category_gradient += 2.0 * cfg.l2 * effects
            gradient[category_start:category_start + len(categories)] = category_gradient
        if elo_index is not None:
            gradient[elo_index] = (
                np.dot(grad_log_home - grad_log_away, elo_features)
                + 2.0 * cfg.l2 * elo_coefficient
            )
        scale = 1.0 / max(float(np.sum(weights)), 1.0)
        return value * scale, gradient * scale

    result = minimize(
        objective_and_gradient,
        initial,
        method="L-BFGS-B",
        jac=True,
        bounds=bounds,
    )
    if not result.success or not np.isfinite(result.fun) or not np.all(np.isfinite(result.x)):
        raise RuntimeError(f"Dixon-Coles optimization failed: {result.message}")
    attack_values, defense_values, effect_values, elo_coefficient = unpack(result.x)
    attack = {team: float(attack_values[index]) for team, index in team_index.items()}
    defense = {team: float(defense_values[index]) for team, index in team_index.items()}
    effects = {"other": 0.0}
    effects.update({
        name: float(effect_values[index]) for name, index in category_index.items()
    })
    model = {
        "schema_version": 1,
        "version": version,
        "training_cutoff": cutoff.isoformat(),
        "intercept": float(result.x[0]),
        "home_advantage": float(result.x[1]),
        "rho": float(result.x[2]),
        "elo_coefficient": elo_coefficient,
        "elo_ratings": final_elo_ratings,
        "elo_scale": 400.0,
        "attack": attack,
        "defense": defense,
        "category_effects": effects,
        "min_expected_goals": 0.1,
        "max_expected_goals": 5.0,
        "fit_config": {
            "decay_per_year": cfg.decay_per_year,
            "friendly_weight": cfg.friendly_weight,
            "l2": cfg.l2,
            "include_elo": cfg.include_elo,
        },
        "training_matches": len(matches),
        "optimizer": {
            "method": "L-BFGS-B",
            "jacobian": "analytic",
            "evaluations": int(result.nfev),
            "iterations": int(result.nit),
        },
    }
    return ModelCandidate(version, model, True, float(result.fun))




