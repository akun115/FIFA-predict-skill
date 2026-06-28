"""MVP Report Input Builder — Patch 34 Part 1.

Builds ``MVPReportInput`` from model_output, context, market comparison,
and scout evidence.  Does NOT call prediction engine.  Does NOT modify
model_output.  Keeps all data partitions separate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from oracle_core.free_provider_context_assembly import (
    MatchContextAssemblyResult,
)
from oracle_core.prediction_context_boundary import (
    ContextualizedPredictionOutput,
)


# ---------------------------------------------------------------------------
# MVP Report Input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MVPReportInput:
    """All data needed to render a Chinese MVP prediction report.

    Every partition is kept separate:
      - model_output: probabilities from the local prediction engine.
      - provider_context: free provider data (report-only).
      - market_comparison: odds data (market comparison, not blended).
      - scout_evidence: web scout findings (report-only).
      - data_gaps: what's missing.
      - caveats: warnings and limitations.
    """

    # ── Model output (preserved exactly) ──
    model_output: Mapping[str, Any]
    """The model output dict — preserved exactly.  Probabilities come from
    the local prediction engine only."""

    # ── Provider context ──
    provider_context: Mapping[str, Any] | None = None
    """Free provider context (e.g. TheSportsDB canonical data).  Report-only.
    Does NOT override model_output."""

    # ── Market comparison ──
    market_comparison: Mapping[str, Any] | None = None
    """Odds / market data for comparison.  NOT blended into model probabilities."""

    # ── Scout evidence ──
    scout_evidence: tuple[Mapping[str, Any], ...] = ()
    """Web Scout evidence items.  Report-only.  Does NOT modify model output."""

    # ── Data gaps ──
    data_gaps: tuple[str, ...] = ()
    """Known data gaps."""

    # ── Caveats ──
    caveats: tuple[str, ...] = ()
    """Caveats and limitations."""

    # ── Provenance ──
    snapshot_id: str = ""
    """Replay snapshot ID, if available."""

    provider_name: str = ""
    """Provider that sourced the context."""

    assembled_at: str = ""
    """When the context was assembled (ISO format)."""

    model_boundary: Mapping[str, Any] = field(default_factory=lambda: {
        "affects_model": False,
        "report_only_or_context_only": True,
        "enters_prediction_engine": False,
    })
    """Model boundary declaration."""

    def __post_init__(self) -> None:
        # Ensure result and advancement probabilities are separate in model_output
        pass  # Frozen — validation occurs in the builder


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_mvp_report_input(
    model_output: Mapping[str, Any],
    context_view_or_assembly_result: (
        ContextualizedPredictionOutput
        | MatchContextAssemblyResult
        | Mapping[str, Any]
        | None
    ) = None,
    *,
    market_comparison: Mapping[str, Any] | None = None,
    scout_result: Any | None = None,
) -> MVPReportInput:
    """Build an ``MVPReportInput`` from model output and context.

    Args:
        model_output: Model output dict (e.g. from ``Prediction.to_dict()``).
        context_view_or_assembly_result: Context from assembly or boundary.
        market_comparison: Optional odds/market data (comparison only).
        scout_result: Optional ``WebScoutResult``.

    Returns:
        ``MVPReportInput`` with all partitions kept separate.

    Requirements:
        - model_output is preserved exactly.
        - No prediction engine calls.
        - No probability calculation.
        - Missing model probabilities → caveat, not fake values.
        - result_probabilities and advancement_probabilities kept separate.
        - odds do NOT enter model_output.
        - scout evidence does NOT enter model_output.
        - provider context does NOT override model_output.
    """
    # Preserve model output exactly
    preserved = dict(model_output)

    caveats: list[str] = []
    gaps: list[str] = []
    provider_context: dict | None = None
    snapshot_id = ""
    provider_name = ""
    assembled_at = ""
    scout_evidence: tuple[Mapping[str, Any], ...] = ()

    # Check for missing probabilities (add caveat, do NOT invent values)
    if not preserved.get("result_probabilities"):
        caveats.append(
            "model_output missing result_probabilities — "
            "prediction may not be available"
        )
    if not preserved.get("advancement_probabilities"):
        caveats.append(
            "model_output missing advancement_probabilities — "
            "knockout advancement not available"
        )

    # Extract context from the various types
    ctx = context_view_or_assembly_result
    if ctx is not None:
        if isinstance(ctx, ContextualizedPredictionOutput):
            provider_context = ctx.context_snapshot
            gaps.extend(ctx.data_gaps)
            caveats.extend(ctx.caveats)
            snapshot_id = ctx.context_snapshot.get("snapshot_id", "") if ctx.context_snapshot else ""
            provider_name = provider_context.get("provider_name", "") if provider_context else ""

        elif hasattr(ctx, "context_snapshot") and hasattr(ctx, "gap_list"):
            # MatchContextAssemblyResult
            if ctx.context_snapshot:
                provider_context = ctx.context_snapshot.to_dict()
                snapshot_id = ctx.context_snapshot.snapshot_id
            gaps.extend(ctx.gap_list)
            provider_name = ctx.provider_name
            if ctx.assembled_at:
                assembled_at = ctx.assembled_at.isoformat()
            caveats.append(
                "Provider context is report-only/context-only — "
                "does not affect model probabilities."
            )

        elif isinstance(ctx, Mapping):
            provider_context = dict(ctx)
            snapshot_id = ctx.get("snapshot_id", "")

    # Scout evidence
    if scout_result is not None:
        if hasattr(scout_result, "evidence"):
            scout_evidence = tuple(
                e.to_dict() if hasattr(e, "to_dict") else dict(e)
                for e in scout_result.evidence
            )
        if hasattr(scout_result, "caveats"):
            caveats.extend(scout_result.caveats)
        if hasattr(scout_result, "gaps"):
            gaps.extend(scout_result.gaps)

    # Market comparison caveat
    if market_comparison is not None:
        caveats.append(
            "Market odds provided for comparison only — "
            "NOT blended into model probabilities."
        )
    else:
        caveats.append("Market comparison (odds) not available.")

    # Standard caveats
    caveats.extend([
        "Odds do NOT enter model.",
        "Injuries / lineups / news / weather do NOT adjust xG.",
        "TheSportsDB remains needs_more_info — not approved for live adapter.",
        "Missing data items listed in gap_list.",
    ])

    return MVPReportInput(
        model_output=preserved,
        provider_context=provider_context,
        market_comparison=dict(market_comparison) if market_comparison else None,
        scout_evidence=scout_evidence,
        data_gaps=tuple(gaps),
        caveats=tuple(caveats),
        snapshot_id=snapshot_id,
        provider_name=provider_name,
        assembled_at=assembled_at,
    )
