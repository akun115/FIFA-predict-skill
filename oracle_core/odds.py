"""Pure local odds adapter — compute implied probabilities and model-vs-market delta.

No network access. No odds scraping. No betting advice.
Probabilities from ``predict_match`` are NEVER modified.

All normalized output uses ``team_a_win`` / ``draw`` / ``team_b_win`` keys.
Legacy ``home_win`` / ``away_win`` input is accepted and normalised on ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OddsEntry:
    """One odds snapshot for a single market (1X2 or over/under 2.5).

    Canonical 1X2 fields are ``team_a_win`` / ``draw`` / ``team_b_win``.
    Legacy ``home_win`` / ``away_win`` keys in the input dict are normalised
    by ``from_dict()``; they are never stored on the object.
    """

    match_id: str
    source: str  # "fixture", "user", etc.
    odds_format: str  # "decimal"
    market_type: str  # "1x2" or "over_under_2_5"
    # 1X2 canonical fields
    team_a_win: float | None = None
    draw: float | None = None
    team_b_win: float | None = None
    # Over/under fields
    over: float | None = None
    under: float | None = None
    threshold: float | None = None  # e.g. 2.5
    captured_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OddsEntry":
        # Normalise 1X2: prefer team_a_win/team_b_win, fall back to home_win/away_win
        taw = data.get("team_a_win")
        if taw is None:
            taw = data.get("home_win")
        tbw = data.get("team_b_win")
        if tbw is None:
            tbw = data.get("away_win")
        dr = data.get("draw")

        return cls(
            match_id=str(data.get("match_id", "")),
            source=str(data.get("source", "")),
            odds_format=str(data.get("odds_format", "decimal")),
            market_type=str(data.get("market_type", "")),
            team_a_win=float(taw) if taw is not None else None,
            draw=float(dr) if dr is not None else None,
            team_b_win=float(tbw) if tbw is not None else None,
            over=float(data["over"]) if "over" in data else None,
            under=float(data["under"]) if "under" in data else None,
            threshold=float(data["threshold"]) if "threshold" in data else None,
            captured_at=str(data.get("captured_at", "")),
        )


@dataclass(frozen=True)
class ImpliedProbabilities:
    """Outcome probabilities derived from decimal odds, with overround removed.

    Normalized 1X2 keys are always ``team_a_win`` / ``draw`` / ``team_b_win``.
    """

    market_type: str
    raw_implied: dict[str, float]
    overround: float
    normalized: dict[str, float]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_odds(*values: float) -> None:
    for v in values:
        if not isinstance(v, (int, float)) or v <= 1.0:
            raise ValueError(f"decimal odds must be > 1.0, got {v!r}")
        if v != v:  # NaN check
            raise ValueError("decimal odds must not be NaN")


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_implied_1x2(
    team_a_win: float, draw: float, team_b_win: float,
) -> ImpliedProbabilities:
    """Compute normalized implied probabilities from 1X2 decimal odds.

    Output keys are ``team_a_win`` / ``draw`` / ``team_b_win``.

    Overround (bookmaker margin) is removed proportionally via
    ``normalized = raw / (1 + overround)``.
    """
    _validate_odds(team_a_win, draw, team_b_win)
    raw = {
        "team_a_win": 1.0 / team_a_win,
        "draw": 1.0 / draw,
        "team_b_win": 1.0 / team_b_win,
    }
    overround = sum(raw.values()) - 1.0
    normalized = {k: v / (1.0 + overround) for k, v in raw.items()}
    return ImpliedProbabilities(
        market_type="1x2",
        raw_implied=raw,
        overround=overround,
        normalized=normalized,
    )


def compute_implied_over_under(
    over: float, under: float, threshold: float = 2.5,
) -> ImpliedProbabilities:
    """Compute normalized implied probabilities from over/under decimal odds."""
    _validate_odds(over, under)
    tkey = str(threshold).replace(".", "_")
    raw = {
        f"over_{tkey}": 1.0 / over,
        f"under_{tkey}": 1.0 / under,
    }
    overround = sum(raw.values()) - 1.0
    normalized = {k: v / (1.0 + overround) for k, v in raw.items()}
    return ImpliedProbabilities(
        market_type=f"over_under_{tkey}",
        raw_implied=raw,
        overround=overround,
        normalized=normalized,
    )


def compute_implied(entry: OddsEntry) -> ImpliedProbabilities | None:
    """Dispatch to the correct computation based on market_type.

    Returns ``None`` when the required odds fields are missing.
    """
    if entry.market_type == "1x2":
        if entry.team_a_win is None or entry.draw is None or entry.team_b_win is None:
            return None
        return compute_implied_1x2(entry.team_a_win, entry.draw, entry.team_b_win)

    if entry.market_type.startswith("over_under"):
        if entry.over is None or entry.under is None:
            return None
        threshold = entry.threshold if entry.threshold is not None else 2.5
        return compute_implied_over_under(entry.over, entry.under, threshold)

    return None


# ---------------------------------------------------------------------------
# Model-vs-market delta
# ---------------------------------------------------------------------------


def model_vs_market_delta(
    model_probs: dict[str, float],
    market_implied: dict[str, float],
) -> dict[str, float]:
    """Signed delta per outcome: model_prob - market_implied_prob.

    Positive delta → model is more optimistic about that outcome than the market.
    Negative delta → model is more pessimistic.
    Only keys present in *market_implied* are included.
    """
    return {
        k: model_probs.get(k, 0.0) - market_implied.get(k, 0.0)
        for k in market_implied
    }


# ---------------------------------------------------------------------------
# Odds indexing with duplicate resolution
# ---------------------------------------------------------------------------


def build_odds_index(
    entries: list[OddsEntry],
) -> tuple[dict[str, OddsEntry], dict[str, Any]]:
    """Index odds entries by match_id, resolving duplicates deterministically.

    Deduplication rules:
    1. Single entry per match_id → keep it.
    2. Multiple entries, some with ``captured_at`` → pick the **latest** timestamp.
    3. Multiple entries, none with valid ``captured_at`` → last entry wins.

    Returns:
        ``(index, audit)`` where *index* maps match_id → OddsEntry and
        *audit* is a dict describing how duplicates were resolved.
    """
    # Group by match_id
    by_id: dict[str, list[OddsEntry]] = {}
    for e in entries:
        by_id.setdefault(e.match_id, []).append(e)

    index: dict[str, OddsEntry] = {}
    duplicate_ids: list[str] = []
    resolved_by_ts = 0
    resolved_by_last = 0

    for mid, items in by_id.items():
        if len(items) == 1:
            index[mid] = items[0]
        else:
            duplicate_ids.append(mid)
            # Separate entries with vs without captured_at
            with_ts = [(e.captured_at, e) for e in items if e.captured_at]
            if with_ts:
                # Pick the entry with latest captured_at
                with_ts.sort(key=lambda x: x[0])
                index[mid] = with_ts[-1][1]
                resolved_by_ts += 1
            else:
                # No timestamps — last entry wins
                index[mid] = items[-1]
                resolved_by_last += 1

    audit: dict[str, Any] = {
        "total_entries": len(entries),
        "unique_match_ids": len(index),
        "duplicate_count": len(duplicate_ids),
        "duplicate_match_ids": duplicate_ids if duplicate_ids else None,
        "resolved_by_captured_at": resolved_by_ts,
        "resolved_by_last_entry": resolved_by_last,
    }
    return index, audit


def load_odds_from_jsonl(path: str) -> list[OddsEntry]:
    """Read OddsEntry objects from a JSONL fixture file."""
    import json
    from pathlib import Path

    entries: list[OddsEntry] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(OddsEntry.from_dict(json.loads(line)))
    return entries
