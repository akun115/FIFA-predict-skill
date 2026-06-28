"""Deterministic statistical core for World Cup Oracle."""

from .model import ModelConfig, Prediction, TeamSnapshot, predict_match

__all__ = ["ModelConfig", "Prediction", "TeamSnapshot", "predict_match"]
