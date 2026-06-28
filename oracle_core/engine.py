"""Pure expected-goal and score-distribution calculations."""

from __future__ import annotations

import math

from .types import ModelConfig, Prediction, TeamSnapshot


def predict_match(
    team_a: TeamSnapshot,
    team_b: TeamSnapshot,
    *,
    neutral_site: bool = True,
    home_team: str | None = None,
    config: ModelConfig | None = None,
) -> Prediction:
    """Return a deterministic normalized score distribution."""
    if team_a.name == team_b.name:
        raise ValueError("teams must differ")
    cfg = config or ModelConfig()
    if not neutral_site and home_team not in {team_a.name, team_b.name}:
        raise ValueError("home_team must name team_a or team_b for a non-neutral match")

    elo_term = cfg.elo_weight * (team_a.elo - team_b.elo) / 400.0
    log_a = (
        math.log(cfg.base_goal_rate)
        + cfg.attack_weight * (team_a.attack - 70.0) / 10.0
        - cfg.defense_weight * (team_b.defense - 70.0) / 10.0
        + elo_term
        + cfg.form_weight * team_a.form
        + cfg.availability_weight * team_a.availability
    )
    log_b = (
        math.log(cfg.base_goal_rate)
        + cfg.attack_weight * (team_b.attack - 70.0) / 10.0
        - cfg.defense_weight * (team_a.defense - 70.0) / 10.0
        - elo_term
        + cfg.form_weight * team_b.form
        + cfg.availability_weight * team_b.availability
    )
    if not neutral_site:
        if home_team == team_a.name:
            log_a += cfg.home_log_advantage
        else:
            log_b += cfg.home_log_advantage

    lambda_a = _clamp(math.exp(log_a), cfg.min_expected_goals, cfg.max_expected_goals)
    lambda_b = _clamp(math.exp(log_b), cfg.min_expected_goals, cfg.max_expected_goals)
    score_probabilities = _score_matrix(lambda_a, lambda_b, cfg)
    result_probabilities = {
        "team_a_win": sum(p for (a, b), p in score_probabilities.items() if a > b),
        "draw": sum(p for (a, b), p in score_probabilities.items() if a == b),
        "team_b_win": sum(p for (a, b), p in score_probabilities.items() if a < b),
    }
    result_total = sum(result_probabilities.values())
    result_probabilities = {
        key: value / result_total for key, value in result_probabilities.items()
    }
    top_scores = tuple(
        sorted(score_probabilities.items(), key=lambda item: (-item[1], item[0]))[:5]
    )
    over_under = _compute_over_under(score_probabilities)
    return Prediction(
        team_a=team_a.name,
        team_b=team_b.name,
        expected_goals=(lambda_a, lambda_b),
        result_probabilities=result_probabilities,
        score_probabilities=score_probabilities,
        top_scores=top_scores,
        over_under=over_under,
        model_version=cfg.version,
        assumptions=(
            "Coefficients are transparent provisional priors, not fitted 2026 parameters.",
            "Ratings and availability inputs are assumed to be pre-match information.",
        ),
        limitations=(
            "Tactical and psychological evidence is explanatory until backtested.",
            "The baseline does not claim to outperform bookmaker markets.",
        ),
    )


def _score_matrix(
    lambda_a: float, lambda_b: float, config: ModelConfig
) -> dict[tuple[int, int], float]:
    max_goals = config.min_score_grid
    while max_goals < config.max_score_grid:
        captured = _poisson_cdf(max_goals, lambda_a) * _poisson_cdf(max_goals, lambda_b)
        if 1.0 - captured <= config.tail_tolerance:
            break
        max_goals += 1

    probabilities: dict[tuple[int, int], float] = {}
    for goals_a in range(max_goals + 1):
        p_a = _poisson_pmf(goals_a, lambda_a)
        for goals_b in range(max_goals + 1):
            raw = p_a * _poisson_pmf(goals_b, lambda_b)
            probabilities[(goals_a, goals_b)] = raw * _dc_factor(
                goals_a, goals_b, lambda_a, lambda_b, config.dixon_coles_rho
            )

    if any(value < 0 or not math.isfinite(value) for value in probabilities.values()):
        raise ValueError("Dixon-Coles parameters produced invalid probabilities")
    total = sum(probabilities.values())
    if total <= 0:
        raise ValueError("score probability mass must be positive")
    return {score: value / total for score, value in probabilities.items()}


def _dc_factor(
    goals_a: int, goals_b: int, lambda_a: float, lambda_b: float, rho: float
) -> float:
    """Classic Dixon-Coles tau using the paper's rho sign convention."""
    if goals_a == 0 and goals_b == 0:
        return 1.0 - lambda_a * lambda_b * rho
    if goals_a == 0 and goals_b == 1:
        return 1.0 + lambda_a * rho
    if goals_a == 1 and goals_b == 0:
        return 1.0 + lambda_b * rho
    if goals_a == 1 and goals_b == 1:
        return 1.0 - rho
    return 1.0


def _poisson_pmf(goals: int, rate: float) -> float:
    return math.exp(-rate) * rate**goals / math.factorial(goals)


def _poisson_cdf(goals: int, rate: float) -> float:
    return sum(_poisson_pmf(value, rate) for value in range(goals + 1))


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _compute_over_under(
    score_probabilities: dict[tuple[int, int], float],
) -> dict[str, float]:
    """Aggregate score matrix into over/under total-goal probabilities."""
    thresholds = (0.5, 1.5, 2.5, 3.5, 4.5)
    result: dict[str, float] = {}
    for threshold in thresholds:
        over = sum(
            p for (a, b), p in score_probabilities.items() if a + b > threshold
        )
        under_key = f"under_{str(threshold).replace('.', '_')}"
        over_key = f"over_{str(threshold).replace('.', '_')}"
        result[over_key] = over
        result[under_key] = 1.0 - over
    return result
