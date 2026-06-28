"""Validated, idempotent YAML knowledge storage."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import tempfile
from typing import Mapping

import yaml

from .scoring import score_prediction, summarize_calibration


class KnowledgeStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    @classmethod
    def initialize(
        cls, root: Path | str, *, teams: Mapping[str, Mapping] | None = None
    ) -> "KnowledgeStore":
        store = cls(root)
        (store.root / "L1-events").mkdir(parents=True, exist_ok=True)
        (store.root / "L2-states").mkdir(parents=True, exist_ok=True)
        (store.root / "L3-patterns").mkdir(parents=True, exist_ok=True)
        store._write(store.results_path, {"matches": []})
        store._write(store.teams_path, {"teams": deepcopy(dict(teams or {}))})
        store._write(
            store.calibration_path,
            {"prediction_history": [], "calibration": {"model_status": "provisional"}},
        )
        return store

    @property
    def results_path(self) -> Path:
        return self.root / "L1-events" / "match-results.yaml"

    @property
    def teams_path(self) -> Path:
        return self.root / "L2-states" / "teams.yaml"

    @property
    def calibration_path(self) -> Path:
        return self.root / "L3-patterns" / "model-calibration.yaml"

    def load_results(self) -> list[dict]:
        return self._read(self.results_path, {"matches": []}).get("matches", [])

    def load_teams(self) -> dict[str, dict]:
        return self._read(self.teams_path, {"teams": {}}).get("teams", {})

    def load_predictions(self) -> list[dict]:
        return self._read(
            self.calibration_path, {"prediction_history": []}
        ).get("prediction_history", [])

    def record_prediction(
        self,
        match_id: str,
        team_a: str,
        team_b: str,
        probabilities: Mapping[str, float],
        expected_goals: list[float] | tuple[float, float],
        input_snapshot: Mapping,
        *,
        replace: bool = False,
    ) -> dict:
        _require_text(match_id, "match_id")
        _require_text(team_a, "team_a")
        _require_text(team_b, "team_b")
        score_prediction(probabilities, "team_a_win")
        if len(expected_goals) != 2 or any(
            not math.isfinite(float(value)) or float(value) < 0
            for value in expected_goals
        ):
            raise ValueError("expected_goals must contain two finite non-negative values")

        data = self._read(
            self.calibration_path,
            {"prediction_history": [], "calibration": {"model_status": "provisional"}},
        )
        history = data.setdefault("prediction_history", [])
        existing = next((row for row in history if row.get("match_id") == match_id), None)
        new_values = {
            "probabilities": dict(probabilities),
            "expected_goals": [float(value) for value in expected_goals],
        }
        if existing:
            old_values = {
                "probabilities": existing.get("probabilities"),
                "expected_goals": existing.get("expected_goals"),
            }
            if old_values == new_values:
                return {"status": "already_recorded", "match_id": match_id}
            if not replace:
                raise ValueError("prediction already exists; pass replace=True to replace it")
            if "actual_result" in existing:
                raise ValueError("a settled prediction cannot be replaced")
            existing.setdefault("audit", []).append(
                {
                    "replaced_at": _now(),
                    "probabilities": old_values["probabilities"],
                    "expected_goals": old_values["expected_goals"],
                }
            )
            existing.update(new_values)
            existing["recorded_at"] = _now()
            existing["input_snapshot"] = deepcopy(dict(input_snapshot))
            status = "replaced"
        else:
            history.append(
                {
                    "match_id": match_id,
                    "team_a": team_a,
                    "team_b": team_b,
                    "recorded_at": _now(),
                    **new_values,
                    "input_snapshot": deepcopy(dict(input_snapshot)),
                    "audit": [],
                }
            )
            status = "recorded"
        self._write(self.calibration_path, data)
        return {"status": status, "match_id": match_id}

    def record_result(
        self,
        match_id: str,
        date: str,
        stage: str,
        team_a: str,
        team_b: str,
        score: list[int] | tuple[int, int],
        *,
        neutral_site: bool = True,
        home_team: str | None = None,
        stats: Mapping | None = None,
    ) -> dict:
        _validate_result(match_id, date, team_a, team_b, score, neutral_site, home_team)
        results_data = self._read(self.results_path, {"matches": []})
        matches = results_data.setdefault("matches", [])
        existing = next((row for row in matches if row.get("id") == match_id), None)
        identity = {
            "date": date,
            "team_a": team_a,
            "team_b": team_b,
            "score": list(score),
        }
        if existing:
            if all(existing.get(key) == value for key, value in identity.items()):
                return {"status": "already_recorded", "match_id": match_id}
            raise ValueError("match_id already exists with a different result")

        matches.append(
            {
                "id": match_id,
                "date": date,
                "stage": stage,
                "team_a": team_a,
                "team_b": team_b,
                "score": list(score),
                "neutral_site": neutral_site,
                "home_team": home_team,
                "stats": deepcopy(dict(stats or {})),
            }
        )
        teams_data = self._read(self.teams_path, {"teams": {}})
        self._update_team_states(
            teams_data.setdefault("teams", {}), date, stage, team_a, team_b,
            list(score), neutral_site, home_team, dict(stats or {})
        )
        calibration_data = self._read(
            self.calibration_path,
            {"prediction_history": [], "calibration": {"model_status": "provisional"}},
        )
        settled = self._settle_prediction(
            calibration_data.setdefault("prediction_history", []), match_id, list(score)
        )

        self._write(self.results_path, results_data)
        self._write(self.teams_path, teams_data)
        self._write(self.calibration_path, calibration_data)
        return {"status": "recorded", "match_id": match_id, "prediction_settled": settled}

    def calibration_report(self) -> dict:
        settled = [
            row for row in self.load_predictions()
            if "actual_result" in row and "probabilities" in row
        ]
        return summarize_calibration(settled)

    def _update_team_states(
        self, teams: dict, date: str, stage: str, team_a: str, team_b: str,
        score: list[int], neutral_site: bool, home_team: str | None, stats: dict
    ) -> None:
        before_a = float(teams.get(team_a, {}).get("elo", 1500))
        before_b = float(teams.get(team_b, {}).get("elo", 1500))
        venue_points = 0.0
        if not neutral_site:
            venue_points = 50.0 if home_team == team_a else -50.0
        expected_a = 1.0 / (1.0 + 10 ** (-(before_a - before_b + venue_points) / 400.0))
        actual_a = 1.0 if score[0] > score[1] else 0.5 if score[0] == score[1] else 0.0
        importance = {"group": 1.0, "R32": 1.3, "R16": 1.5, "QF": 1.7, "SF": 1.76, "F": 1.76}
        change_a = 32.0 * importance.get(stage, 1.0) * (actual_a - expected_a)

        for name, opponent, change, own, other in (
            (team_a, team_b, change_a, score[0], score[1]),
            (team_b, team_a, -change_a, score[1], score[0]),
        ):
            if name not in teams:
                continue
            team = teams[name]
            old_elo = before_a if name == team_a else before_b
            team["elo"] = old_elo + change
            team["elo_trend"] = float(team.get("elo_trend", 0.0)) + change
            team["last_match_date"] = date
            entry = {
                "date": date,
                "opponent": opponent,
                "result": f"{own}-{other}",
            }
            if isinstance(stats.get("xg"), list) and len(stats["xg"]) == 2:
                index = 0 if name == team_a else 1
                entry["xg_diff"] = float(stats["xg"][index]) - float(stats["xg"][1 - index])
            team["form_last_5"] = ([entry] + list(team.get("form_last_5", [])))[:5]

    @staticmethod
    def _settle_prediction(history: list[dict], match_id: str, score: list[int]) -> bool:
        record = next((row for row in history if row.get("match_id") == match_id), None)
        if record is None:
            return False
        actual = "team_a_win" if score[0] > score[1] else "draw" if score[0] == score[1] else "team_b_win"
        record["actual_score"] = score
        record["actual_result"] = actual
        record["settled_at"] = _now()
        record["scores"] = score_prediction(record["probabilities"], actual)
        return True

    @staticmethod
    def _read(path: Path, default: dict) -> dict:
        if not path.exists():
            return deepcopy(default)
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        if loaded is None:
            return deepcopy(default)
        if not isinstance(loaded, dict):
            raise ValueError(f"knowledge file must contain a mapping: {path}")
        return loaded

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
            ) as handle:
                yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
                temp_name = handle.name
            os.replace(temp_name, path)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)


def _validate_result(
    match_id: str, date: str, team_a: str, team_b: str,
    score: list[int] | tuple[int, int], neutral_site: bool, home_team: str | None
) -> None:
    for value, label in ((match_id, "match_id"), (date, "date"), (team_a, "team_a"), (team_b, "team_b")):
        _require_text(value, label)
    datetime.strptime(date, "%Y-%m-%d")
    if team_a == team_b:
        raise ValueError("teams must be different")
    if len(score) != 2 or any(not isinstance(value, int) or value < 0 for value in score):
        raise ValueError("score must contain two non-negative integers")
    if not neutral_site and home_team not in {team_a, team_b}:
        raise ValueError("home_team must identify one participant")


def _require_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
