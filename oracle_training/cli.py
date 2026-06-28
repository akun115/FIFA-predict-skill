"""Command-line orchestration for national-team model maintenance."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from .ingest import ingest_csv, write_snapshot
from .registry import ModelRegistry, PromotionRejected


DEFAULT_SOURCE = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"


def default_models_root() -> Path:
    return Path(
        os.environ.get(
            "WORLD_CUP_ORACLE_MODELS",
            Path.home() / ".world-cup-oracle" / "models",
        )
    )


def default_training_root() -> Path:
    return Path(
        os.environ.get(
            "WORLD_CUP_ORACLE_TRAINING_DATA",
            Path.home() / ".world-cup-oracle" / "training",
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="world-cup-oracle-model-lab")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest")
    ingest.add_argument("--training-root", default=str(default_training_root()))
    ingest.add_argument("--as-of", required=True)
    ingest.add_argument("--source", default=DEFAULT_SOURCE)

    backtest = commands.add_parser("backtest")
    backtest.add_argument("--training-root", default=str(default_training_root()))
    backtest.add_argument("--as-of", required=True)
    backtest.add_argument("--snapshot", default="latest")
    backtest.add_argument("--first-test-year", type=int, default=2010)

    train = commands.add_parser("train")
    train.add_argument("--models-root", default=str(default_models_root()))
    train.add_argument("--training-root", default=str(default_training_root()))
    train.add_argument("--as-of", required=True)
    train.add_argument("--version", required=True)
    train.add_argument("--snapshot", default="latest")
    train.add_argument("--backtest-report", default="latest")

    status = commands.add_parser("status")
    status.add_argument("--models-root", default=str(default_models_root()))
    status.add_argument("--version", default="")

    promote = commands.add_parser("promote")
    promote.add_argument("--models-root", default=str(default_models_root()))
    promote.add_argument("--version", required=True)
    promote.add_argument("--confirm", action="store_true")
    return parser


def run_ingest(*, source: str, as_of: str, training_root: str) -> dict:
    request = Request(source, headers={"User-Agent": "world-cup-oracle-model-lab/1.0"})
    with urlopen(request, timeout=60) as response:
        raw = response.read()
    cutoff = date.fromisoformat(as_of)
    result = ingest_csv(raw, as_of=cutoff, source_url=source)
    root = Path(training_root)
    snapshot = write_snapshot(result, root / "snapshots")
    index = root / "latest-snapshot.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    temporary = index.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "path": str(snapshot.resolve()),
                "as_of": as_of,
                "normalized_sha256": result.manifest.normalized_sha256,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, index)
    return {"snapshot": str(snapshot), "manifest": result.manifest.to_dict()}


def run_status(*, models_root: str, version: str = "") -> dict:
    return ModelRegistry(models_root).status(version)


def run_promote(*, models_root: str, version: str, confirm: bool) -> dict:
    try:
        pointer = ModelRegistry(models_root).promote(version, confirm=confirm)
        return {"status": "promoted", "version": version, "pointer": str(pointer)}
    except PromotionRejected as error:
        return {"status": "refused", "version": version, "error": str(error)}


def run_backtest(**kwargs) -> dict:
    from .pipeline import backtest_from_snapshot

    return backtest_from_snapshot(**kwargs)


def run_train(**kwargs) -> dict:
    from .pipeline import train_from_snapshot

    return train_from_snapshot(**kwargs)


def main(argv: list[str] | None = None) -> int:
    values = vars(build_parser().parse_args(argv))
    command = values.pop("command")
    if command == "ingest":
        result = run_ingest(**values)
    elif command == "status":
        result = run_status(**values)
    elif command == "promote":
        result = run_promote(**values)
    elif command == "backtest":
        result = run_backtest(**values)
    else:
        result = run_train(**values)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
