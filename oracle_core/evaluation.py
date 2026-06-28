"""Read-only replay evaluation: compare prediction logs to actual results.

Produces accuracy/scoring metrics with breakdowns by data_quality status,
by_stage (group/knockout), and by_round (R32/R16/QF/SF/THIRD_PLACE/FINAL).
Advancement metrics are computed for knockout-stage prediction logs.
Never modifies any data file. Never changes probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any

from oracle_core.tournament import (
    check_round_robin_integrity,
    load_aliases,
    load_groups,
    load_schedule,
)
from oracle_core.types import GroupDefinition, ScheduledMatch

# Lazy import to keep odds module optional for evaluation
try:
    from oracle_core.odds import (
        ImpliedProbabilities,
        OddsEntry,
        compute_implied,
        model_vs_market_delta,
    )
    _ODDS_AVAILABLE = True
except ImportError:
    _ODDS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Outcome helpers
# ---------------------------------------------------------------------------

_1X2_KEYS = ("team_a_win", "draw", "team_b_win")


def _actual_1x2(score: tuple[int, int]) -> str:
    sa, sb = score
    if sa > sb:
        return "team_a_win"
    if sa == sb:
        return "draw"
    return "team_b_win"


def _outcome_indicator(actual: str) -> tuple[float, float, float]:
    """Return (o_team_a_win, o_draw, o_team_b_win) for the actual outcome."""
    return (
        1.0 if actual == "team_a_win" else 0.0,
        1.0 if actual == "draw" else 0.0,
        1.0 if actual == "team_b_win" else 0.0,
    )


# ---------------------------------------------------------------------------
# Metric helpers (computations that go beyond the oracle_training.metrics module)
# ---------------------------------------------------------------------------


def _safe_log(p: float, eps: float = 1e-15) -> float:
    return math.log(max(eps, min(1.0 - eps, p)))


def _compute_brier(probs: dict[str, float], actual: str) -> float:
    o = {k: 1.0 if k == actual else 0.0 for k in _1X2_KEYS}
    return sum((probs[k] - o[k]) ** 2 for k in _1X2_KEYS) / 3.0


def _compute_log_loss(probs: dict[str, float], actual: str) -> float:
    return -_safe_log(probs.get(actual, 0.0))


def _compute_rps(probs: dict[str, float], actual: str) -> float:
    """Ranked Probability Score for ordered outcomes.

    Outcomes ordered from team_b_win (worst for team_a) to team_a_win (best):
        team_b_win → draw → team_a_win
    """
    order = ("team_b_win", "draw", "team_a_win")
    pred_cum = [probs[order[0]], probs[order[0]] + probs[order[1]]]
    obs = {k: 1.0 if k == actual else 0.0 for k in order}
    obs_cum = [obs[order[0]], obs[order[0]] + obs[order[1]]]
    return sum((p - o) ** 2 for p, o in zip(pred_cum, obs_cum)) / 2.0


def _score_hit(actual: tuple[int, int], top_scores: list[dict], top_n: int) -> bool:
    """Check if actual score appears in the first top_n score predictions."""
    for entry in top_scores[:top_n]:
        sc = entry.get("score")
        if sc and tuple(sc) == actual:
            return True
    return False


def _over_under_hit(over_under: dict[str, float], total_goals: int, threshold: float) -> bool | None:
    """Check if over/under prediction matches actual. Returns None if key missing."""
    key = f"over_{str(threshold).replace('.', '_')}"
    if key not in over_under:
        return None
    pred_over = over_under[key]
    actual_over = 1.0 if total_goals > threshold else 0.0
    # "Correct" if the higher-probability direction matches actual
    return (pred_over >= 0.5 and actual_over == 1.0) or (pred_over < 0.5 and actual_over == 0.0)


def _expected_goal_mae(expected: tuple[float, float], score: tuple[int, int]) -> float:
    return (abs(expected[0] - score[0]) + abs(expected[1] - score[1])) / 2.0


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class MetricBundle:
    """Aggregated metrics for a group of predictions."""
    count: int = 0
    brier_sum: float = 0.0
    log_loss_sum: float = 0.0
    rps_sum: float = 0.0
    directional_correct: int = 0
    exact_hits: int = 0
    top3_hits: int = 0
    top5_hits: int = 0
    over_2_5_correct: int = 0
    over_2_5_total: int = 0
    under_2_5_correct: int = 0
    under_2_5_total: int = 0
    eg_mae_sum: float = 0.0

    def add_settled(
        self,
        probs: dict[str, float],
        actual_outcome: str,
        expected_goals: tuple[float, float],
        actual_score: tuple[int, int],
        top_scores: list[dict],
        over_under: dict[str, float],
    ) -> None:
        self.count += 1
        self.brier_sum += _compute_brier(probs, actual_outcome)
        self.log_loss_sum += _compute_log_loss(probs, actual_outcome)
        self.rps_sum += _compute_rps(probs, actual_outcome)

        # Directional: predicted highest-prob outcome matches actual
        predicted_outcome = max(probs, key=probs.get)  # type: ignore[arg-type]
        if predicted_outcome == actual_outcome:
            self.directional_correct += 1

        # Score hits
        if _score_hit(actual_score, top_scores, 1):
            self.exact_hits += 1
        if _score_hit(actual_score, top_scores, 3):
            self.top3_hits += 1
        if _score_hit(actual_score, top_scores, 5):
            self.top5_hits += 1

        # Over/under 2.5
        total = actual_score[0] + actual_score[1]
        ou_25 = _over_under_hit(over_under, total, 2.5)
        if ou_25 is not None:
            self.over_2_5_total += 1
            if ou_25:
                self.over_2_5_correct += 1
        # Under 2.5 is the complement — same test, inverse
        # over_2_5 correct → under_2_5 also correct (they're complementary)
        # Actually: if total > 2.5 and pred over_2_5 >= 0.5, then under_2_5
        # prediction is < 0.5 (correctly predicting "not under"). So both are correct.
        # But wait, we only track them as separate if both keys exist.
        under_key = "under_2_5"
        if under_key in over_under:
            self.under_2_5_total += 1
            pred_under = over_under[under_key]
            actual_under = 1.0 if total < 2.5 else 0.0
            if (pred_under >= 0.5 and actual_under == 1.0) or (pred_under < 0.5 and actual_under == 0.0):
                self.under_2_5_correct += 1

        # Expected goal MAE
        self.eg_mae_sum += _expected_goal_mae(expected_goals, actual_score)

    def to_dict(self) -> dict[str, float | None]:
        if self.count == 0:
            return {
                "count": 0, "1x2_accuracy": None, "brier": None,
                "log_loss": None, "rps": None, "exact_score_hit_rate": None,
                "top3_score_hit_rate": None, "top5_score_hit_rate": None,
                "over_2_5_accuracy": None, "under_2_5_accuracy": None,
                "expected_goal_mae": None,
            }
        return {
            "count": self.count,
            "1x2_accuracy": self.directional_correct / self.count,
            "brier": self.brier_sum / self.count,
            "log_loss": self.log_loss_sum / self.count,
            "rps": self.rps_sum / self.count,
            "exact_score_hit_rate": self.exact_hits / self.count,
            "top3_score_hit_rate": self.top3_hits / self.count,
            "top5_score_hit_rate": self.top5_hits / self.count,
            "over_2_5_accuracy": (
                self.over_2_5_correct / self.over_2_5_total
                if self.over_2_5_total > 0 else None
            ),
            "under_2_5_accuracy": (
                self.under_2_5_correct / self.under_2_5_total
                if self.under_2_5_total > 0 else None
            ),
            "expected_goal_mae": self.eg_mae_sum / self.count,
        }


# ---------------------------------------------------------------------------
# Advancement metric bundle — knockout only
# ---------------------------------------------------------------------------

_KNOWN_KNOCKOUT_ROUNDS = frozenset({"R32", "R16", "QF", "SF", "THIRD_PLACE", "FINAL"})


@dataclass
class AdvancementMetricBundle:
    """Aggregated advancement metrics for knockout predictions."""

    count: int = 0
    missing_count: int = 0
    correct: int = 0
    brier_sum: float = 0.0
    log_loss_sum: float = 0.0

    def add_settled(
        self,
        adv_probs: dict[str, float],
        actual_winner: str,
    ) -> None:
        """*actual_winner* must be ``"team_a"`` or ``"team_b"``."""
        self.count += 1
        team_a_adv = float(adv_probs["team_a_advances"])
        team_b_adv = float(adv_probs["team_b_advances"])

        # Directional accuracy: higher advancement probability wins
        predicted_winner = "team_a" if team_a_adv >= team_b_adv else "team_b"
        if predicted_winner == actual_winner:
            self.correct += 1

        # Brier score (binary: advances / does not advance)
        o_a = 1.0 if actual_winner == "team_a" else 0.0
        o_b = 1.0 if actual_winner == "team_b" else 0.0
        self.brier_sum += ((team_a_adv - o_a) ** 2 + (team_b_adv - o_b) ** 2) / 2.0

        # Log loss
        prob_of_actual = team_a_adv if actual_winner == "team_a" else team_b_adv
        self.log_loss_sum += -_safe_log(prob_of_actual)

    def record_missing(self) -> None:
        """Count an entry that has advancement_probs but no resolved winner."""
        self.missing_count += 1

    def to_dict(self) -> dict[str, float | None]:
        if self.count == 0:
            return {
                "advancement_count": 0,
                "advancement_missing_count": self.missing_count,
                "advancement_accuracy": None,
                "advancement_brier": None,
                "advancement_log_loss": None,
            }
        return {
            "advancement_count": self.count,
            "advancement_missing_count": self.missing_count,
            "advancement_accuracy": self.correct / self.count,
            "advancement_brier": self.brier_sum / self.count,
            "advancement_log_loss": self.log_loss_sum / self.count,
        }


# ---------------------------------------------------------------------------
# Knockout helpers
# ---------------------------------------------------------------------------


def _is_knockout_entry(entry: dict) -> bool:
    """Return True if the prediction log entry is for a knockout match."""
    return entry.get("advancement_probabilities") is not None


def _resolve_advancement_winner(
    matched: "ScheduledMatch",
    entry: dict,
    knockout_winners: dict[str, str] | None,
) -> str | None:
    """Determine which team actually advanced in a knockout match.

    Returns ``"team_a"``, ``"team_b"``, or ``None`` (unresolved).

    Resolution priority:
    1. *knockout_winners* dict (maps match_id → winner team name)
    2. Entry-level ``winner`` field
    3. Regulation score (non-draw only — draw cannot infer advancement)
    """
    match_id = matched.match_id

    # Priority 1: knockout_winners dict
    if knockout_winners and match_id in knockout_winners:
        winner_name = knockout_winners[match_id]
        if winner_name == matched.team_a:
            return "team_a"
        if winner_name == matched.team_b:
            return "team_b"

    # Priority 2: entry-level winner field
    entry_winner = entry.get("winner")
    if entry_winner:
        if entry_winner == entry.get("team_a"):
            return "team_a"
        if entry_winner == entry.get("team_b"):
            return "team_b"

    # Priority 3: regulation score (non-draw only)
    score = matched.score
    if score is not None:
        if score[0] > score[1]:
            return "team_a"
        if score[1] > score[0]:
            return "team_b"

    return None


def _classify_stage(
    matched: "ScheduledMatch",
    groups: dict[str, "GroupDefinition"],
) -> str:
    """Return ``"group"``, ``"knockout"``, or ``"other"``."""
    g_or_r = matched.group_or_round
    if g_or_r in groups:
        return "group"
    if g_or_r in _KNOWN_KNOCKOUT_ROUNDS:
        return "knockout"
    return "other"


def _classify_round(matched: "ScheduledMatch") -> str:
    """Return the round name for by_round breakdown.

    Returns the *group_or_round* value directly if it is a known knockout
    round, otherwise ``"other"``.
    """
    g_or_r = matched.group_or_round
    if g_or_r in _KNOWN_KNOCKOUT_ROUNDS:
        return g_or_r
    return "other"


# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------


def _build_match_index(
    schedule: tuple[ScheduledMatch, ...],
) -> dict[tuple[str, str], ScheduledMatch]:
    """Build a lookup from (team_a_norm, team_b_norm) → ScheduledMatch.

    Both directions are indexed so a prediction for (A, B) or (B, A) can match.
    """
    index: dict[tuple[str, str], ScheduledMatch] = {}
    for m in schedule:
        a = m.team_a.strip()
        b = m.team_b.strip()
        index[(a.lower(), b.lower())] = m
        index[(b.lower(), a.lower())] = m
    return index


def _build_match_id_index(
    schedule: tuple[ScheduledMatch, ...],
) -> dict[str, ScheduledMatch]:
    """Build a lookup from match_id → ScheduledMatch."""
    return {m.match_id: m for m in schedule}


def _match_data_quality(
    match: ScheduledMatch,
    groups: dict[str, GroupDefinition],
    schedule: tuple[ScheduledMatch, ...],
) -> str:
    """Determine the data_quality status for a matched schedule match.

    Knockout rounds return ``"ok"`` (round-robin integrity does not apply).
    Group matches use ``check_round_robin_integrity``.
    """
    gname = match.group_or_round
    if gname in _KNOWN_KNOCKOUT_ROUNDS:
        return "ok"
    if gname not in groups:
        return "no_group"
    dq = check_round_robin_integrity(schedule, gname, groups[gname].teams)
    return dq["status"]  # "ok" or "warning"


def evaluate(
    log_dir: str | Path,
    schedule: tuple[ScheduledMatch, ...],
    groups: dict[str, GroupDefinition] | None = None,
    odds_index: dict[str, "OddsEntry"] | None = None,
    knockout_winners: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Read prediction logs, match to schedule, compute metrics.

    Args:
        log_dir: Directory containing predictions-*.jsonl files.
        schedule: Tuple of all scheduled matches (the source of truth).
        groups: Optional group definitions for data_quality breakdown.
        odds_index: Optional dict mapping match_id → OddsEntry for
            market-vs-model comparison. When provided, market-implied
            metrics (Brier, log-loss, RPS, directional accuracy) are
            computed alongside model metrics.
        knockout_winners: Optional dict mapping match_id → winner team name
            for resolving advancement outcomes in drawn knockout matches.

    Returns:
        A JSON-serializable dict with summary metrics, per-status breakdowns,
        by_stage / by_round breakdowns, and advancement_metrics.
    """
    log_path = Path(log_dir)
    if not log_path.is_dir():
        raise FileNotFoundError(f"log directory not found: {log_dir}")

    if groups is None:
        groups = {}

    match_index = _build_match_index(schedule)
    match_id_index = _build_match_id_index(schedule)

    # Accumulators
    total = 0
    settled = 0
    unsettled = 0
    malformed = 0
    matched_by_id = 0
    matched_by_team = 0
    warnings: list[str] = []

    # Per-status bundles: "all", "ok", "warning", "no_group", "no_match"
    bundles: dict[str, MetricBundle] = {
        key: MetricBundle() for key in ("all", "ok", "warning", "no_group", "no_match")
    }
    # Per-model_mode bundles: "all", "provisional", "fitted", "unknown"
    model_mode_bundles: dict[str, MetricBundle] = {
        key: MetricBundle() for key in ("all", "provisional", "fitted", "unknown")
    }
    # Per-stage bundles: "all", "group", "knockout"
    stage_bundles: dict[str, MetricBundle] = {
        key: MetricBundle() for key in ("all", "group", "knockout")
    }
    # Per-round bundles: dynamic — created on demand for knockout rounds
    round_bundles: dict[str, MetricBundle] = {}

    # Advancement metrics
    adv_all = AdvancementMetricBundle()
    adv_by_stage: dict[str, AdvancementMetricBundle] = {
        "knockout": AdvancementMetricBundle(),
    }
    adv_by_round: dict[str, AdvancementMetricBundle] = {}

    # Market metrics: accumulate when odds data is available for a settled match
    market_bundle: MetricBundle | None = (
        MetricBundle() if odds_index is not None else None
    )

    # Read all log entries
    jsonl_files = sorted(log_path.glob("predictions-*.jsonl"))
    for jf in jsonl_files:
        for lineno, line in enumerate(jf.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                warnings.append(
                    f"skipped malformed JSON at {jf.name}:{lineno}"
                )
                continue

            total += 1
            team_a = str(entry.get("team_a", "")).strip()
            team_b = str(entry.get("team_b", "")).strip()

            # --- Match to schedule: match_id first, then team pair fallback ---
            matched: ScheduledMatch | None = None
            match_method: str = ""

            # Priority 1: match_id (non-empty and found in schedule)
            entry_match_id = str(entry.get("match_id", "")).strip()
            if entry_match_id:
                by_id = match_id_index.get(entry_match_id)
                if by_id is not None:
                    matched = by_id
                    match_method = "match_id"

            # Priority 2: normalized team pair (both directions)
            if matched is None:
                key = (team_a.lower(), team_b.lower())
                by_team = match_index.get(key)
                if by_team is not None:
                    matched = by_team
                    match_method = "team_pair"

            if matched is None or not matched.is_completed:
                unsettled += 1
                continue

            # --- settled ---
            settled += 1
            if match_method == "match_id":
                matched_by_id += 1
            else:
                matched_by_team += 1

            actual_score = matched.score
            assert actual_score is not None
            actual_outcome = _actual_1x2(actual_score)

            probs = entry.get("result_probabilities", {})
            eg = entry.get("expected_goals", [0.0, 0.0])
            top_scores = entry.get("top_scores", [])
            over_under = entry.get("over_under", {})

            # Determine data_quality status
            dq_status = _match_data_quality(matched, groups, schedule)

            # Determine model_mode (default "unknown" for old logs)
            model_mode = str(entry.get("model_mode", "unknown")).strip()
            if model_mode not in model_mode_bundles:
                model_mode = "unknown"

            # Add to "all" bundle and the specific status bundle
            for bundle_key in ("all", dq_status):
                bundles[bundle_key].add_settled(
                    probs, actual_outcome,
                    (float(eg[0]), float(eg[1])),
                    actual_score,
                    top_scores,
                    over_under,
                )

            # Add to model_mode bundles
            for mm_key in ("all", model_mode):
                model_mode_bundles[mm_key].add_settled(
                    probs, actual_outcome,
                    (float(eg[0]), float(eg[1])),
                    actual_score,
                    top_scores,
                    over_under,
                )

            # --- by_stage / by_round 1X2 breakdown ---
            stage = _classify_stage(matched, groups)
            for s_key in ("all", stage):
                if s_key in stage_bundles:
                    stage_bundles[s_key].add_settled(
                        probs, actual_outcome,
                        (float(eg[0]), float(eg[1])),
                        actual_score,
                        top_scores,
                        over_under,
                    )

            round_name = _classify_round(matched)
            if round_name != "other":
                if round_name not in round_bundles:
                    round_bundles[round_name] = MetricBundle()
                round_bundles[round_name].add_settled(
                    probs, actual_outcome,
                    (float(eg[0]), float(eg[1])),
                    actual_score,
                    top_scores,
                    over_under,
                )

            # --- Market metrics (when odds data is available) ---
            if market_bundle is not None and odds_index is not None:
                odds_entry = odds_index.get(matched.match_id)
                if odds_entry is not None and _ODDS_AVAILABLE:
                    implied = compute_implied(odds_entry)
                    if implied is not None and implied.market_type == "1x2":
                        # Market uses team_a_win/draw/team_b_win — same keys as model
                        market_probs = implied.normalized
                        if len(market_probs) == 3:
                            market_bundle.add_settled(
                                market_probs, actual_outcome,
                                (float(eg[0]), float(eg[1])),
                                actual_score,
                                top_scores,  # model top_scores (market doesn't have)
                                {},  # no market over/under here
                            )

            # --- Advancement metrics (knockout only) ---
            if _is_knockout_entry(entry):
                adv_probs = entry["advancement_probabilities"]
                winner = _resolve_advancement_winner(
                    matched, entry, knockout_winners,
                )
                if winner is not None:
                    adv_all.add_settled(adv_probs, winner)
                    if stage == "knockout":
                        adv_by_stage["knockout"].add_settled(adv_probs, winner)
                    if round_name != "other":
                        if round_name not in adv_by_round:
                            adv_by_round[round_name] = AdvancementMetricBundle()
                        adv_by_round[round_name].add_settled(adv_probs, winner)
                else:
                    adv_all.record_missing()
                    if stage == "knockout":
                        adv_by_stage["knockout"].record_missing()
                    if round_name != "other":
                        if round_name not in adv_by_round:
                            adv_by_round[round_name] = AdvancementMetricBundle()
                        adv_by_round[round_name].record_missing()

    # Build output
    by_status = {}
    for key in ("all", "ok", "warning", "no_group", "no_match"):
        if bundles[key].count > 0 or key in ("all", "ok", "warning"):
            by_status[key] = bundles[key].to_dict()

    by_model = {}
    for key in ("all", "provisional", "fitted", "unknown"):
        if model_mode_bundles[key].count > 0 or key in ("all", "provisional", "fitted"):
            by_model[key] = model_mode_bundles[key].to_dict()

    # by_stage (1X2)
    by_stage = {}
    for key in ("all", "group", "knockout"):
        if stage_bundles[key].count > 0 or key in ("all", "group"):
            by_stage[key] = stage_bundles[key].to_dict()

    # by_round (1X2, knockout rounds only)
    by_round = {}
    for rname in sorted(round_bundles):
        if round_bundles[rname].count > 0:
            by_round[rname] = round_bundles[rname].to_dict()

    # Advancement metrics output
    adv_output: dict[str, Any] = {
        "all": adv_all.to_dict(),
    }
    adv_stage: dict[str, Any] = {}
    for key in ("knockout",):
        if adv_by_stage[key].count > 0 or adv_by_stage[key].missing_count > 0:
            adv_stage[key] = adv_by_stage[key].to_dict()
    if adv_stage:
        adv_output["by_stage"] = adv_stage

    adv_rounds: dict[str, Any] = {}
    for rname in sorted(adv_by_round):
        bundle = adv_by_round[rname]
        if bundle.count > 0 or bundle.missing_count > 0:
            adv_rounds[rname] = bundle.to_dict()
    if adv_rounds:
        adv_output["by_round"] = adv_rounds

    result: dict[str, Any] = {
        "total_predictions": total,
        "settled_predictions": settled,
        "unsettled_predictions": unsettled,
        "malformed_lines_skipped": malformed,
        "matching_stats": {
            "matched_by_match_id": matched_by_id,
            "matched_by_team_pair": matched_by_team,
            "unmatched": unsettled,
        },
        "warnings": warnings if warnings else None,
        "metrics": by_status.get("all", bundles["all"].to_dict()),
        "by_data_quality": by_status,
        "by_model_mode": by_model,
        "by_stage": by_stage,
        "advancement_metrics": adv_output,
        "data_sources": {
            "log_dir": str(log_path),
            "schedule_matches": len(schedule),
            "groups_loaded": len(groups),
        },
    }

    if by_round:
        result["by_round"] = by_round

    if market_bundle is not None:
        result["market_metrics"] = market_bundle.to_dict()

    return result


# ---------------------------------------------------------------------------
# Convenience: load from knowledge root
# ---------------------------------------------------------------------------


def evaluate_from_knowledge(
    log_dir: str | Path,
    knowledge_root: str | Path,
) -> dict[str, Any]:
    """Load schedule + groups from a knowledge root and evaluate."""
    root = Path(knowledge_root)
    aliases = load_aliases(root / "L2-states" / "team-aliases.yaml")
    groups = load_groups(root / "L2-states" / "groups.yaml", aliases)
    schedule = load_schedule(root / "L1-events" / "schedule.yaml", aliases)
    return evaluate(log_dir, schedule, groups)
