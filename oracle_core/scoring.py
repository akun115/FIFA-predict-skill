"""Proper scoring rules and non-mutating calibration reports."""

from __future__ import annotations

import math
from typing import Iterable, Mapping


OUTCOMES = ("team_b_win", "draw", "team_a_win")


def score_prediction(
    probabilities: Mapping[str, float], actual_result: str
) -> dict[str, float]:
    values = _validated(probabilities)
    if actual_result not in OUTCOMES:
        raise ValueError(f"unknown actual result: {actual_result}")

    observed = [1.0 if outcome == actual_result else 0.0 for outcome in OUTCOMES]
    forecast = [values[outcome] for outcome in OUTCOMES]
    brier = sum((probability - truth) ** 2 for probability, truth in zip(forecast, observed))

    cumulative_forecast = 0.0
    cumulative_observed = 0.0
    rps_sum = 0.0
    for index in range(len(OUTCOMES) - 1):
        cumulative_forecast += forecast[index]
        cumulative_observed += observed[index]
        rps_sum += (cumulative_forecast - cumulative_observed) ** 2
    rps = rps_sum / (len(OUTCOMES) - 1)

    actual_probability = max(values[actual_result], 1e-15)
    return {
        "brier": brier,
        "rps": rps,
        "log_loss": -math.log(actual_probability),
    }


def summarize_calibration(rows: Iterable[Mapping]) -> dict:
    settled = list(rows)
    scored = [
        score_prediction(row["probabilities"], row["actual_result"])
        for row in settled
    ]
    sample_size = len(scored)
    mean_scores = {
        name: (sum(item[name] for item in scored) / sample_size if sample_size else None)
        for name in ("brier", "rps", "log_loss")
    }

    correct = 0
    bins = [dict(predicted=0.0, observed=0.0, count=0) for _ in range(10)]
    for row in settled:
        probabilities = _validated(row["probabilities"])
        actual = row["actual_result"]
        predicted = max(OUTCOMES, key=lambda outcome: probabilities[outcome])
        correct += int(predicted == actual)
        for outcome in OUTCOMES:
            probability = probabilities[outcome]
            index = min(9, int(probability * 10))
            bins[index]["predicted"] += probability
            bins[index]["observed"] += float(outcome == actual)
            bins[index]["count"] += 1

    calibration_bins = []
    for index, bucket in enumerate(bins):
        count = bucket["count"]
        if count:
            calibration_bins.append(
                {
                    "range": [index / 10, (index + 1) / 10],
                    "mean_predicted": bucket["predicted"] / count,
                    "observed_frequency": bucket["observed"] / count,
                    "count": count,
                }
            )

    return {
        "status": "report_only" if sample_size >= 30 else "insufficient_data",
        "sample_size": sample_size,
        "minimum_for_stable_report": 30,
        "mean_scores": mean_scores,
        "result_accuracy": (correct / sample_size if sample_size else None),
        "calibration_bins": calibration_bins,
        "note": "This report never changes model coefficients automatically.",
    }


def _validated(probabilities: Mapping[str, float]) -> dict[str, float]:
    if set(probabilities) != set(OUTCOMES):
        raise ValueError(f"probabilities must contain exactly: {', '.join(OUTCOMES)}")
    values = {outcome: float(probabilities[outcome]) for outcome in OUTCOMES}
    if any(not math.isfinite(value) or value < 0 for value in values.values()):
        raise ValueError("probabilities must be finite and non-negative")
    if not math.isclose(sum(values.values()), 1.0, abs_tol=1e-9):
        raise ValueError("probabilities must sum to one")
    return values
