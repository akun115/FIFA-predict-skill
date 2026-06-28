#!/usr/bin/env python
"""Generate pre_match replay predictions for every completed schedule match.

Usage:
    python scripts/generate_replay_predictions.py
    python scripts/generate_replay_predictions.py --output-dir logs/replay/custom
    python scripts/generate_replay_predictions.py --help

Every prediction calls get_tournament_state(state_mode="pre_match") to
reconstruct the table as it was before kickoff.  Log entries are written to a
separate replay directory — production prediction logs are NEVER modified.

Output: JSON summary to stdout; prediction log entries in JSONL in the output dir.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure the project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from oracle_core.engine import predict_match as predict_score
from oracle_core.tournament import (
    get_tournament_state,
    load_aliases,
    load_groups,
    load_rules,
    load_schedule,
)
from oracle_core.types import (
    GroupDefinition,
    Prediction,
    ScheduledMatch,
    TeamSnapshot,
    TournamentRules,
    TournamentState,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NEUTRAL_CONTEXT_NOTE = (
    "Tournament context detected but not quantitatively modeled;"
    " rotation, motivation, qualification pressure,"
    " and tactical conservatism may affect realized score."
)

_SCHEDULE_INTEGRITY_NOTE = (
    "Schedule integrity warning for group {group}: {issues}."
    " Tournament context may not reflect a valid single-round-robin schedule."
    " Standings and incentives derived from this schedule should be treated"
    " as provisional."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_compact() -> str:
    """Timestamp slug suitable for directory names."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _build_team_snapshot(name: str, teams: dict[str, dict]) -> TeamSnapshot:
    """Build a TeamSnapshot from knowledge-store data (or defaults)."""
    record = teams.get(name, {})
    return TeamSnapshot(
        name=name,
        elo=float(record.get("elo", 1500.0)),
        attack=float(record.get("attack", record.get("attack_rating", 70.0))),
        defense=float(record.get("defense", record.get("defense_rating", 70.0))),
        form=float(record.get("form", 0.0)),
        availability=float(record.get("availability", 0.0)),
    )


def _input_hash(
    team_a: str,
    team_b: str,
    neutral_site: bool,
    category: str,
) -> str:
    canonical = json.dumps(
        [team_a, team_b, neutral_site, category, "", {}, {}],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _score_hash(prediction: Prediction) -> str:
    canonical = json.dumps(
        {
            f"{a}-{b}": round(p, 12)
            for (a, b), p in sorted(prediction.score_probabilities.items())
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Tournament context → compact payload
# ---------------------------------------------------------------------------


def _build_tournament_context_payload(state: TournamentState) -> dict[str, Any]:
    """Extract the tournament_context sub-dict from a TournamentState."""
    tc: dict[str, Any] = {
        "state_mode": state.state_mode,
        "state_timestamp_utc": state.state_timestamp_utc,
        "match_id": state.match_id,
        "team_a_incentive": {
            "primary_incentive": state.team_a_incentive.primary_incentive.value,
            "incentive_flags": list(state.team_a_incentive.incentive_flags),
            "intensity": state.team_a_incentive.intensity,
            "description": state.team_a_incentive.description,
        },
        "team_b_incentive": {
            "primary_incentive": state.team_b_incentive.primary_incentive.value,
            "incentive_flags": list(state.team_b_incentive.incentive_flags),
            "intensity": state.team_b_incentive.intensity,
            "description": state.team_b_incentive.description,
        },
        "excluded_matches": list(state.excluded_matches),
        "simultaneous_group_matches": list(state.simultaneous_group_matches),
    }
    if state.data_quality is not None:
        tc["data_quality"] = state.data_quality
    return tc


# ---------------------------------------------------------------------------
# Enrich prediction with tournament context (replicates server.py logic)
# ---------------------------------------------------------------------------


def _enrich_prediction(
    prediction: Prediction,
    tc_payload: dict[str, Any],
    data_quality: dict | None,
) -> Prediction:
    """Return a new Prediction with tournament_context and limitations updated.

    Probabilities are NEVER modified.
    """
    current_limits = list(prediction.limitations)
    if _NEUTRAL_CONTEXT_NOTE not in current_limits:
        current_limits.append(_NEUTRAL_CONTEXT_NOTE)

    # If tournament context has a schedule integrity warning, surface it
    if isinstance(data_quality, dict) and data_quality.get("status") == "warning":
        issues_text = "; ".join(data_quality.get("issues", []))
        group = tc_payload.get("match_context", {}).get(
            "group_or_round", "?"
        )
        dq_note = _SCHEDULE_INTEGRITY_NOTE.format(
            group=group, issues=issues_text,
        )
        if dq_note not in current_limits:
            current_limits.append(dq_note)

    return replace(
        prediction,
        tournament_context=tc_payload,
        limitations=tuple(current_limits),
    )


# ---------------------------------------------------------------------------
# Build replay log entry
# ---------------------------------------------------------------------------


def _build_replay_log_entry(
    prediction: Prediction,
    match: ScheduledMatch,
    tc_payload: dict[str, Any],
    data_quality: dict | None,
) -> dict[str, Any]:
    """Build a JSON-serializable log entry with all replay metadata."""
    now = _now_utc()
    safe_ts = now.replace(":", "").replace("-", "").replace("T", "-")[:20]
    return {
        "prediction_id": f"replay-{match.match_id}-{safe_ts}",
        "predicted_at": now,
        "match_id": match.match_id,
        "match_id_source": "provided",
        "team_a": match.team_a,
        "team_b": match.team_b,
        "replay_mode": True,
        "state_mode": "pre_match",
        "model_mode": "provisional",
        "engine_path": "oracle_core.engine.predict_score",
        "model_name": prediction.model_version,
        "model_version": prediction.model_version,
        "model_artifact_hash": "replay-provisional",
        "input_context_hash": _input_hash(
            match.team_a, match.team_b, match.neutral_site, "world_cup"
        ),
        "category": "world_cup",
        "neutral_site": match.neutral_site,
        "expected_goals": list(prediction.expected_goals),
        "result_probabilities": dict(prediction.result_probabilities),
        "over_under": dict(prediction.over_under),
        "top_scores": [
            {"score": list(score), "probability": probability}
            for score, probability in prediction.top_scores
        ],
        "score_matrix_hash": _score_hash(prediction),
        "tournament_context_available": True,
        "tournament_context": tc_payload,
        "data_quality": data_quality,
        "limitations": list(prediction.limitations),
        "source_snapshot_refs": {
            "model_version": prediction.model_version,
            "generation_mode": "replay",
        },
    }


# ---------------------------------------------------------------------------
# Write replay log
# ---------------------------------------------------------------------------


def _write_replay_log(output_dir: Path, entry: dict[str, Any]) -> None:
    """Append one JSONL line to the replay log file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    date_part = entry["predicted_at"][:10]
    filename = output_dir / f"predictions-{date_part}.jsonl"
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    with open(filename, "a", encoding="utf-8") as fh:
        fh.write(line)


# ---------------------------------------------------------------------------
# Core generation function (testable with fixture data)
# ---------------------------------------------------------------------------


def generate_replay_predictions(
    schedule: tuple[ScheduledMatch, ...],
    groups: dict[str, GroupDefinition],
    rules: TournamentRules,
    teams: dict[str, dict],
    output_dir: Path,
) -> dict[str, Any]:
    """Generate pre_match replay predictions for every completed schedule match.

    Args:
        schedule: All scheduled matches.
        groups: Group definitions keyed by group name.
        rules: Tournament advancement rules.
        teams: Per-team knowledge-store data (elo, attack, defense, …).
        output_dir: Where to write replay JSONL log files.

    Returns:
        Summary dict with ``generated``, ``skipped``, ``total_completed``.
    """
    completed = [m for m in schedule if m.is_completed]
    generated = 0
    skipped: list[dict[str, str]] = []

    for match in completed:
        try:
            # 1. Get pre_match tournament state
            state = get_tournament_state(
                match.match_id, schedule, groups, rules,
                state_mode="pre_match",
            )

            # 2. Build tournament context payload
            tc_payload = _build_tournament_context_payload(state)

            # 3. Build team snapshots
            snap_a = _build_team_snapshot(match.team_a, teams)
            snap_b = _build_team_snapshot(match.team_b, teams)

            # 4. Generate prediction (provisional engine)
            prediction = predict_score(
                snap_a, snap_b,
                neutral_site=match.neutral_site,
            )

            # 5. Enrich with tournament context
            data_quality = state.data_quality
            prediction = _enrich_prediction(prediction, tc_payload, data_quality)

            # 6. Build log entry
            entry = _build_replay_log_entry(
                prediction, match, tc_payload, data_quality,
            )

            # 7. Write to replay output directory
            _write_replay_log(output_dir, entry)
            generated += 1

        except Exception as exc:
            skipped.append({
                "match_id": match.match_id,
                "team_a": match.team_a,
                "team_b": match.team_b,
                "reason": f"{type(exc).__name__}: {exc}",
            })

    return {
        "total_completed_matches": len(completed),
        "generated": generated,
        "skipped_predictions": skipped if skipped else None,
        "output_dir": str(output_dir),
    }


# ---------------------------------------------------------------------------
# Convenience: load from knowledge root
# ---------------------------------------------------------------------------


def generate_from_knowledge(
    knowledge_root: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Load schedule / groups / rules / teams from a knowledge root, then generate."""
    root = Path(knowledge_root)
    aliases = load_aliases(root / "L2-states" / "team-aliases.yaml")
    groups = load_groups(root / "L2-states" / "groups.yaml", aliases)
    schedule = load_schedule(root / "L1-events" / "schedule.yaml", aliases)
    rules = load_rules(root / "L2-states" / "tournament-rules-2026.yaml")

    # Load team data from teams.yaml (KnowledgeStore-style read)
    import yaml
    teams_path = root / "L2-states" / "teams.yaml"
    teams: dict[str, dict] = {}
    if teams_path.is_file():
        raw = yaml.safe_load(teams_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            teams = raw.get("teams", {})

    return generate_replay_predictions(
        schedule, groups, rules, teams, Path(output_dir),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate pre_match replay predictions for completed matches.",
    )
    parser.add_argument(
        "--knowledge",
        default=str(_PROJECT_ROOT / "knowledge"),
        help="Path to the knowledge/ directory (schedule, groups, teams).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_PROJECT_ROOT / "logs" / "replay" / _now_compact()),
        help="Directory for replay prediction log files.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON summary.",
    )
    args = parser.parse_args()

    knowledge_root = Path(args.knowledge)
    if not knowledge_root.is_dir():
        print(f"ERROR: knowledge directory not found: {knowledge_root}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    if output_dir.exists():
        print(
            f"ERROR: output directory already exists: {output_dir}\n"
            f"  (Refusing to overwrite. Choose a different --output-dir.)",
            file=sys.stderr,
        )
        sys.exit(1)

    result = generate_from_knowledge(knowledge_root, output_dir)

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=indent,
                     default=str))


if __name__ == "__main__":
    main()
