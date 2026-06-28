"""Model-lab MCP server kept separate from runtime prediction."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

from oracle_training.cli import (
    default_models_root,
    default_training_root,
    run_backtest,
    run_promote,
    run_status,
    run_train,
)


mcp = FastMCP(
    "world-cup-oracle-model-lab",
    instructions="Historical training, walk-forward evaluation, status, and explicit promotion.",
)


@mcp.tool(name="model_status")
def model_status_tool(version: str = "", models_root: str = "") -> str:
    result = run_status(models_root=models_root or str(default_models_root()), version=version)
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


@mcp.tool(name="train_model")
def train_model_tool(
    snapshot: str = "latest",
    as_of: str = "",
    backtest_report: str = "latest",
    version: str = "national-dc-v1.0.0",
    models_root: str = "",
    training_root: str = "",
) -> str:
    result = run_train(
        snapshot=snapshot,
        as_of=as_of,
        backtest_report=backtest_report,
        version=version,
        models_root=models_root or str(default_models_root()),
        training_root=training_root or str(default_training_root()),
    )
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


@mcp.tool(name="backtest_model")
def backtest_model_tool(
    snapshot: str = "latest",
    as_of: str = "",
    first_test_year: int = 2010,
    models_root: str = "",
    training_root: str = "",
) -> str:
    result = run_backtest(
        snapshot=snapshot,
        as_of=as_of,
        first_test_year=first_test_year,
        models_root=models_root or str(default_models_root()),
        training_root=training_root or str(default_training_root()),
    )
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


@mcp.tool(name="promote_model")
def promote_model_tool(
    version: str,
    confirm: bool = False,
    models_root: str = "",
) -> str:
    result = run_promote(
        models_root=models_root or str(default_models_root()),
        version=version,
        confirm=confirm,
    )
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


if __name__ == "__main__":
    mcp.run(transport="stdio")
