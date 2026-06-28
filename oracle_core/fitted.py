"""Pure-Python runtime for fitted national-team models."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from .engine import _compute_over_under, _score_matrix
from .types import ModelConfig, Prediction


def _finite(value: object, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _finite_map(value: object, label: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return {str(key): _finite(item, f"{label}.{key}") for key, item in value.items()}


@dataclass(frozen=True)
class FittedNationalModel:
    version: str
    training_cutoff: str
    intercept: float
    home_advantage: float
    rho: float
    elo_coefficient: float
    elo_ratings: dict[str, float]
    elo_scale: float
    attack: dict[str, float]
    defense: dict[str, float]
    category_effects: dict[str, float]
    min_expected_goals: float
    max_expected_goals: float

    @classmethod
    def from_dict(cls, value: dict) -> "FittedNationalModel":
        if value.get("schema_version") != 1:
            raise ValueError("unsupported fitted-model schema_version")
        version = str(value.get("version", "")).strip()
        cutoff = str(value.get("training_cutoff", "")).strip()
        if not version or not cutoff:
            raise ValueError("version and training_cutoff are required")
        model = cls(
            version=version,
            training_cutoff=cutoff,
            intercept=_finite(value["intercept"], "intercept"),
            home_advantage=_finite(value["home_advantage"], "home_advantage"),
            rho=_finite(value["rho"], "rho"),
            elo_coefficient=_finite(
                value.get("elo_coefficient", 0.0), "elo_coefficient"
            ),
            elo_ratings=_finite_map(value.get("elo_ratings", {}), "elo_ratings"),
            elo_scale=_finite(value.get("elo_scale", 400.0), "elo_scale"),
            attack=_finite_map(value["attack"], "attack"),
            defense=_finite_map(value["defense"], "defense"),
            category_effects=_finite_map(
                value["category_effects"], "category_effects"
            ),
            min_expected_goals=_finite(
                value.get("min_expected_goals", 0.1), "min_expected_goals"
            ),
            max_expected_goals=_finite(
                value.get("max_expected_goals", 5.0), "max_expected_goals"
            ),
        )
        if model.elo_scale <= 0:
            raise ValueError("elo_scale must be positive")
        if not 0 < model.min_expected_goals < model.max_expected_goals:
            raise ValueError("expected-goal bounds are invalid")
        if set(model.attack) != set(model.defense):
            raise ValueError("attack and defense team maps must match")
        if not -0.5 <= model.rho <= 0.5:
            raise ValueError("rho is outside safe bounds")
        return model

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "version": self.version,
            "training_cutoff": self.training_cutoff,
            "intercept": self.intercept,
            "home_advantage": self.home_advantage,
            "rho": self.rho,
            "elo_coefficient": self.elo_coefficient,
            "elo_ratings": dict(self.elo_ratings),
            "elo_scale": self.elo_scale,
            "attack": dict(self.attack),
            "defense": dict(self.defense),
            "category_effects": dict(self.category_effects),
            "min_expected_goals": self.min_expected_goals,
            "max_expected_goals": self.max_expected_goals,
        }

    def predict(
        self,
        team_a: str,
        team_b: str,
        *,
        neutral_site: bool,
        category: str,
        elo_difference: float | None = None,
        home_team: str | None = None,
    ) -> Prediction:
        """Return a deterministic score distribution from fitted attack/defense/Elo parameters.

        This fitted model uses only intercept, attack, defense, Elo, category_effects,
        and home_advantage. It does NOT use form or availability inputs. The provisional
        engine (oracle_core/engine.py) supports those dimensions; the fitted path does not.

        If you need injury, rotation, or motivation reflected quantitatively, either:
        - use the provisional engine with overrides, or
        - inspect the qualitative limitations on the returned Prediction object.
        """
        if team_a == team_b:
            raise ValueError("teams must differ")
        unseen = [team for team in (team_a, team_b) if team not in self.attack]
        if elo_difference is None:
            elo_difference = (
                self.elo_ratings.get(team_a, 1500.0)
                - self.elo_ratings.get(team_b, 1500.0)
            ) / self.elo_scale
        attack_a = self.attack.get(team_a, 0.0)
        attack_b = self.attack.get(team_b, 0.0)
        defense_a = self.defense.get(team_a, 0.0)
        defense_b = self.defense.get(team_b, 0.0)
        category_effect = self.category_effects.get(
            category, self.category_effects.get("other", 0.0)
        )
        log_a = (
            self.intercept
            + attack_a
            - defense_b
            + category_effect
            + self.elo_coefficient * float(elo_difference)
        )
        log_b = (
            self.intercept
            + attack_b
            - defense_a
            + category_effect
            - self.elo_coefficient * float(elo_difference)
        )
        if not neutral_site:
            named_home = home_team or team_a
            if named_home == team_a:
                log_a += self.home_advantage
            elif named_home == team_b:
                log_b += self.home_advantage
            else:
                raise ValueError("home_team must be one of the predicted teams")
        lambda_a = min(
            self.max_expected_goals,
            max(self.min_expected_goals, math.exp(log_a)),
        )
        lambda_b = min(
            self.max_expected_goals,
            max(self.min_expected_goals, math.exp(log_b)),
        )
        config = ModelConfig(
            version=self.version,
            dixon_coles_rho=self.rho,
            min_expected_goals=self.min_expected_goals,
            max_expected_goals=self.max_expected_goals,
        )
        scores = _score_matrix(lambda_a, lambda_b, config)
        results = {
            "team_a_win": sum(p for (a, b), p in scores.items() if a > b),
            "draw": sum(p for (a, b), p in scores.items() if a == b),
            "team_b_win": sum(p for (a, b), p in scores.items() if a < b),
        }
        total = sum(results.values())
        results = {key: item / total for key, item in results.items()}
        top_scores = tuple(
            sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:5]
        )
        over_under = _compute_over_under(scores)
        _FORM_AVAIL_NOTE = (
            "Fitted model does not use form/availability inputs;"
            " injury, rotation, and motivation effects"
            " are not reflected in expected goals."
        )
        status = "unseen_team_prior" if unseen else "fitted"
        if unseen:
            limitations = (
                f"Unseen teams use global priors: {', '.join(unseen)}",
                _FORM_AVAIL_NOTE,
            )
        else:
            limitations = (_FORM_AVAIL_NOTE,)
        return Prediction(
            team_a=team_a,
            team_b=team_b,
            expected_goals=(lambda_a, lambda_b),
            result_probabilities=results,
            score_probabilities=scores,
            top_scores=top_scores,
            over_under=over_under,
            model_version=self.version,
            model_status=status,
            assumptions=(f"Tournament category: {category}",),
            limitations=limitations,
        )


def load_model(path: str | Path) -> FittedNationalModel:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("model artifact must be a JSON object")
    return FittedNationalModel.from_dict(value)


def load_current_model(root: str | Path) -> FittedNationalModel:
    models_root = Path(root)
    pointer_path = models_root / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    version = str(pointer.get("version", ""))
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", version) is None:
        raise ValueError("invalid current model version")
    artifact = models_root / version
    checksums = json.loads(
        (artifact / "checksum.sha256").read_text(encoding="utf-8")
    )
    model_path = artifact / "model.json"
    actual = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if checksums.get("model.json") != actual:
        raise ValueError("current model checksum mismatch")
    if pointer.get("model_sha256") != actual:
        raise ValueError("current pointer checksum mismatch")
    return load_model(model_path)
