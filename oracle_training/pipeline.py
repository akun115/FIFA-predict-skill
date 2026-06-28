"""Chronological model-training and evaluation pipeline."""

from __future__ import annotations

from datetime import date
import gzip
import hashlib
import json
import os
from pathlib import Path

from oracle_core.fitted import FittedNationalModel

from .dixon_coles import FitConfig, fit_dixon_coles
from .elo import build_pre_match_elo
from .metrics import mean_scores, score_1x2
from .registry import ModelRegistry
from .types import HistoricalMatch, TournamentCategory
from .walk_forward import annual_folds


_MODEL_NAMES = ("mean", "elo", "dixon_coles", "dixon_coles_elo")


def load_snapshot(path: str | Path) -> tuple[tuple[HistoricalMatch, ...], dict]:
    snapshot = Path(path)
    manifest = json.loads(
        (snapshot / "data-manifest.json").read_text(encoding="utf-8")
    )
    rows = json.loads(
        gzip.decompress((snapshot / "matches.json.gz").read_bytes()).decode("utf-8")
    )
    normalized = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if hashlib.sha256(normalized).hexdigest() != manifest.get("normalized_sha256"):
        raise ValueError("snapshot normalized hash mismatch")
    matches = tuple(
        HistoricalMatch(
            date.fromisoformat(row["date"]),
            row["home_team"],
            row["away_team"],
            int(row["home_score"]),
            int(row["away_score"]),
            row["tournament"],
            bool(row["neutral"]),
            TournamentCategory(row["category"]),
            int(row["source_row"]),
            row["source_id"],
        )
        for row in rows
    )
    return matches, manifest


def resolve_snapshot(
    selector: str,
    *,
    training_root: str | Path,
    as_of: date,
) -> Path:
    root = Path(training_root)
    if selector != "latest":
        candidate = Path(selector)
        if not candidate.is_absolute():
            candidate = root / "snapshots" / selector
        _, manifest = load_snapshot(candidate)
        if date.fromisoformat(manifest["as_of"]) > as_of:
            raise ValueError("snapshot cutoff is later than requested cutoff")
        return candidate
    eligible: list[tuple[date, Path]] = []
    for candidate in (root / "snapshots").glob("snapshot-*"):
        try:
            _, manifest = load_snapshot(candidate)
            cutoff = date.fromisoformat(manifest["as_of"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if cutoff <= as_of:
            eligible.append((cutoff, candidate))
    if not eligible:
        raise FileNotFoundError("no eligible snapshot at or before requested cutoff")
    return max(eligible, key=lambda item: (item[0], item[1].name))[1]


def _outcome(match: HistoricalMatch) -> str:
    if match.home_score > match.away_score:
        return "team_a_win"
    if match.home_score < match.away_score:
        return "team_b_win"
    return "draw"


def _mean_probabilities(matches: tuple[HistoricalMatch, ...]) -> dict[str, float]:
    counts = {"team_a_win": 1, "draw": 1, "team_b_win": 1}
    for match in matches:
        counts[_outcome(match)] += 1
    total = sum(counts.values())
    return {name: count / total for name, count in counts.items()}


def backtest_matches(
    matches: tuple[HistoricalMatch, ...],
    *,
    as_of: date,
    first_test_year: int,
) -> dict:
    """Evaluate all required model families on identical annual test folds."""
    folds = annual_folds(matches, first_test_year=first_test_year, as_of=as_of)
    scores: dict[str, list[dict[str, float]]] = {
        name: [] for name in _MODEL_NAMES
    }
    by_year_scores: dict[str, dict[str, list[dict[str, float]]]] = {}
    by_category_scores: dict[str, dict[str, list[dict[str, float]]]] = {}
    fold_rows: list[dict] = []
    for fold in folds:
        mean_probabilities = _mean_probabilities(fold.training)
        elo_rows = build_pre_match_elo(fold.training + fold.test)
        test_elo = elo_rows[len(fold.training) :]
        cutoff = max(match.date for match in fold.training)
        candidate = fit_dixon_coles(
            fold.training,
            cutoff=cutoff,
            version=f"backtest-{fold.test_year}",
        )
        elo_candidate = fit_dixon_coles(
            fold.training,
            cutoff=cutoff,
            version=f"backtest-elo-{fold.test_year}",
            config=FitConfig(include_elo=True),
        )
        fitted = FittedNationalModel.from_dict(candidate.model)
        fitted_elo = FittedNationalModel.from_dict(elo_candidate.model)
        for match, elo_row in zip(fold.test, test_elo):
            outcome = _outcome(match)
            row_scores = {
                "mean": score_1x2(mean_probabilities, outcome),
                "elo": score_1x2(elo_row.probabilities, outcome),
            }
            dc = fitted.predict(
                match.home_team,
                match.away_team,
                neutral_site=match.neutral,
                category=match.category.value,
            )
            row_scores["dixon_coles"] = score_1x2(
                dc.result_probabilities, outcome
            )
            dc_elo = fitted_elo.predict(
                match.home_team,
                match.away_team,
                neutral_site=match.neutral,
                category=match.category.value,
                elo_difference=(elo_row.home_elo - elo_row.away_elo) / 400.0,
            )
            row_scores["dixon_coles_elo"] = score_1x2(
                dc_elo.result_probabilities, outcome
            )
            year_scores = by_year_scores.setdefault(
                str(fold.test_year), {name: [] for name in _MODEL_NAMES}
            )
            category_scores = by_category_scores.setdefault(
                match.category.value, {name: [] for name in _MODEL_NAMES}
            )
            for name, row_score in row_scores.items():
                scores[name].append(row_score)
                year_scores[name].append(row_score)
                category_scores[name].append(row_score)
        fold_rows.append(
            {
                "test_year": fold.test_year,
                "training_end": cutoff.isoformat(),
                "training_count": len(fold.training),
                "test_count": len(fold.test),
                "partial": fold.partial,
            }
        )
    model_rows = {
        name: {**mean_scores(rows), "sample_count": len(rows)}
        for name, rows in scores.items()
    }

    def summarize(groups):
        return {
            group: {
                name: {**mean_scores(rows), "sample_count": len(rows)}
                for name, rows in model_scores.items()
            }
            for group, model_scores in groups.items()
        }

    by_year = summarize(by_year_scores)
    by_category = summarize(by_category_scores)
    candidate_model = min(
        ("dixon_coles", "dixon_coles_elo"),
        key=lambda name: model_rows[name]["log_loss"],
    )
    candidate_scores = model_rows[candidate_model]
    gates = {
        "integrity": bool(folds),
        "log_loss": candidate_scores["log_loss"] < model_rows["mean"]["log_loss"]
        and candidate_scores["log_loss"] < model_rows["elo"]["log_loss"],
        "brier": candidate_scores["brier"] < model_rows["mean"]["brier"]
        and candidate_scores["brier"] < model_rows["elo"]["brier"],
        "rps": candidate_scores["rps"] < model_rows["mean"]["rps"]
        and candidate_scores["rps"] < model_rows["elo"]["rps"],
    }
    return {
        "as_of": as_of.isoformat(),
        "first_test_year": first_test_year,
        "fold_count": len(folds),
        "folds": fold_rows,
        "models": model_rows,
        "by_year": by_year,
        "by_category": by_category,
        "candidate_model": candidate_model,
        "gates": gates,
    }


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def backtest_from_snapshot(
    *,
    snapshot: str,
    as_of: str,
    first_test_year: int,
    training_root: str,
    **_: object,
) -> dict:
    cutoff = date.fromisoformat(as_of)
    snapshot_path = resolve_snapshot(
        snapshot, training_root=training_root, as_of=cutoff
    )
    matches, manifest = load_snapshot(snapshot_path)
    report = backtest_matches(
        matches,
        as_of=cutoff,
        first_test_year=first_test_year,
    )
    report["snapshot"] = str(snapshot_path.resolve())
    report["snapshot_sha256"] = manifest["normalized_sha256"]
    root = Path(training_root)
    report_path = (
        root
        / "backtests"
        / (
            f"report-{cutoff.isoformat()}-from-{first_test_year}-"
            f"{manifest['normalized_sha256'][:12]}.json"
        )
    )
    _write_json_atomic(report_path, report)
    _write_json_atomic(
        root / "latest-backtest.json",
        {
            "path": str(report_path.resolve()),
            "as_of": cutoff.isoformat(),
            "first_test_year": first_test_year,
            "snapshot_sha256": manifest["normalized_sha256"],
        },
    )
    return {**report, "report_path": str(report_path)}


def _pointer_report(training_root: Path) -> Path | None:
    pointer_path = training_root / "latest-backtest.json"
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        candidate = Path(pointer["path"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if candidate.is_file():
        return candidate
    fallback = training_root / "backtests" / candidate.name
    return fallback if fallback.is_file() else None


def _resolve_report(
    selector: str,
    *,
    training_root: Path,
    cutoff: date,
    snapshot_sha256: str,
) -> tuple[Path, dict]:
    if selector == "latest":
        pointed = _pointer_report(training_root)
        candidates = (pointed,) if pointed is not None else tuple(
            (training_root / "backtests").glob("report-*.json")
        )
    else:
        path = Path(selector)
        if not path.is_absolute():
            path = training_root / "backtests" / selector
        candidates = (path,)
    eligible: list[tuple[date, Path, dict]] = []
    for candidate in candidates:
        try:
            report = json.loads(candidate.read_text(encoding="utf-8"))
            report_cutoff = date.fromisoformat(report["as_of"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if (
            report_cutoff <= cutoff
            and report.get("snapshot_sha256") == snapshot_sha256
        ):
            eligible.append((report_cutoff, candidate, report))
    if not eligible:
        raise FileNotFoundError("no eligible backtest report for selected snapshot")
    _, path, report = max(
        eligible, key=lambda item: (item[0], item[1].name)
    )
    return path, report


def train_from_snapshot(
    *,
    snapshot: str,
    as_of: str,
    backtest_report: str,
    version: str,
    training_root: str,
    models_root: str,
    **_: object,
) -> dict:
    cutoff = date.fromisoformat(as_of)
    snapshot_path = resolve_snapshot(
        snapshot, training_root=training_root, as_of=cutoff
    )
    matches, manifest = load_snapshot(snapshot_path)
    report_path, report = _resolve_report(
        backtest_report,
        training_root=Path(training_root),
        cutoff=cutoff,
        snapshot_sha256=manifest["normalized_sha256"],
    )
    selected_model = report.get("candidate_model")
    if selected_model not in {"dixon_coles", "dixon_coles_elo"}:
        raise ValueError("backtest report has no valid candidate_model")
    use_elo = selected_model == "dixon_coles_elo"
    candidate = fit_dixon_coles(
        tuple(match for match in matches if match.date <= cutoff),
        cutoff=cutoff,
        version=version,
        config=FitConfig(include_elo=use_elo),
    )
    artifact = ModelRegistry(models_root).save_candidate(
        candidate.model, manifest, report
    )
    return {
        "status": "candidate",
        "version": version,
        "artifact": str(artifact),
        "snapshot": str(snapshot_path),
        "backtest_report": str(report_path),
        "model_family": "dixon_coles_elo" if use_elo else "dixon_coles",
        "converged": candidate.converged,
        "objective": candidate.objective,
    }
