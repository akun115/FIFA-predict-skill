"""Proper scoring metrics for 1X2 forecasts."""

from __future__ import annotations

import math


_ORDER = ("team_b_win", "draw", "team_a_win")


def score_1x2(probabilities: dict[str, float], outcome: str) -> dict[str, float]:
    if outcome not in _ORDER or set(probabilities) != set(_ORDER):
        raise ValueError("invalid 1X2 outcome or probability keys")
    values = [float(probabilities[key]) for key in _ORDER]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("probabilities must be finite and non-negative")
    total = sum(values)
    if total <= 0:
        raise ValueError("probability mass must be positive")
    values = [value / total for value in values]
    actual = [1.0 if key == outcome else 0.0 for key in _ORDER]
    brier = sum((predicted - observed) ** 2 for predicted, observed in zip(values, actual))
    log_loss = -math.log(max(1e-15, values[_ORDER.index(outcome)]))
    predicted_cumulative = (values[0], values[0] + values[1])
    actual_cumulative = (actual[0], actual[0] + actual[1])
    rps = sum(
        (predicted - observed) ** 2
        for predicted, observed in zip(predicted_cumulative, actual_cumulative)
    ) / 2.0
    return {"log_loss": log_loss, "brier": brier, "rps": rps}


def mean_scores(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        raise ValueError("at least one score row is required")
    return {
        key: sum(row[key] for row in rows) / len(rows)
        for key in ("log_loss", "brier", "rps")
    }
