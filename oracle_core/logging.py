"""Structured JSONL prediction audit log."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class PredictionLogEntry:
    prediction_id: str
    predicted_at: str
    match_id: str
    match_id_source: str
    team_a: str
    team_b: str
    model_name: str
    model_version: str
    model_artifact_hash: str
    input_context_hash: str
    category: str
    neutral_site: bool
    expected_goals: tuple[float, float]
    result_probabilities: dict[str, float]
    over_under: dict[str, float]
    top_scores: tuple[tuple[tuple[int, int], float], ...]
    score_matrix_hash: str
    tournament_context_available: bool
    limitations: tuple[str, ...]
    source_snapshot_refs: dict[str, str]
    advancement_probabilities: dict | None = None

    def to_jsonl(self) -> str:
        payload = asdict(self)
        payload["expected_goals"] = list(self.expected_goals)
        payload["top_scores"] = [
            {"score": list(score), "probability": probability}
            for score, probability in self.top_scores
        ]
        payload["limitations"] = list(self.limitations)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _input_hash(
    team_a: str,
    team_b: str,
    neutral_site: bool,
    category: str,
    home_team: str,
    overrides_a: dict,
    overrides_b: dict,
) -> str:
    canonical = json.dumps(
        [team_a, team_b, neutral_site, category, home_team or "",
         dict(sorted(overrides_a.items())), dict(sorted(overrides_b.items()))],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _score_hash(score_probabilities: dict) -> str:
    canonical = json.dumps(
        {f"{a}-{b}": round(p, 12) for (a, b), p in sorted(score_probabilities.items())},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PredictionLogger:
    def __init__(self, log_dir: str | Path) -> None:
        self.log_dir = Path(log_dir)

    def write(self, entry: PredictionLogEntry) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        date_part = entry.predicted_at[:10]
        filename = self.log_dir / f"predictions-{date_part}.jsonl"
        try:
            line = entry.to_jsonl() + "\n"
            _atomic_append(filename, line)
        except OSError:
            import sys
            print(
                f"[world-cup-oracle] WARNING: failed to write prediction log to {filename}",
                file=sys.stderr,
            )


def _atomic_append(path: Path, content: str) -> None:
    """Append content to path atomically. We use os.open with O_APPEND
    so no temp file is needed — the write is atomic for lines under PIPE_BUF
    on POSIX; on Windows, this is a best-effort append."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
