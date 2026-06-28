#!/usr/bin/env python
"""Read-only replay evaluation: compare prediction logs to actual results.

Usage:
    python scripts/evaluate_predictions.py
    python scripts/evaluate_predictions.py --log-dir /tmp/logs --knowledge knowledge/
    python scripts/evaluate_predictions.py --help

Output: JSON summary to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from oracle_core.evaluation import evaluate_from_knowledge


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate prediction logs against actual match results.",
    )
    parser.add_argument(
        "--log-dir",
        default=str(_PROJECT_ROOT / "logs" / "predictions"),
        help="Directory containing predictions-*.jsonl files.",
    )
    parser.add_argument(
        "--knowledge",
        default=str(_PROJECT_ROOT / "knowledge"),
        help="Path to the knowledge/ directory (schedule, groups, aliases).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON output.",
    )
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    if not log_dir.is_dir():
        print(f"ERROR: log directory not found: {log_dir}", file=sys.stderr)
        sys.exit(1)

    knowledge_root = Path(args.knowledge)
    if not knowledge_root.is_dir():
        print(f"ERROR: knowledge directory not found: {knowledge_root}", file=sys.stderr)
        sys.exit(1)

    result = evaluate_from_knowledge(log_dir, knowledge_root)

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=indent,
                     default=str))


if __name__ == "__main__":
    main()
