"""Prediction runner external context boundary — Patch 32.

Allows a prediction runner or boundary adapter to accept an external context
snapshot, but ONLY reads context — NEVER modifies model probabilities.

Model output is externally provided.  This module does NOT call the
prediction engine, does NOT recalculate probabilities, and does NOT merge
provider context into model output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from oracle_core.free_provider_context_assembly import (
    MatchContextAssemblyResult,
    ModelBoundary,
)


# ---------------------------------------------------------------------------
# Contextualized prediction output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextualizedPredictionOutput:
    """Prediction output with external context attached — read-only context.

    ``model_output`` is preserved EXACTLY as provided.  Context is stored
    separately and does NOT override any model field.

    **v1 boundary:**
      - result_probabilities preserved exactly.
      - advancement_probabilities preserved exactly.
      - context_snapshot kept separate.
      - data_gaps / caveats kept separate.
      - odds / scout / provider context does NOT override probabilities.
    """

    model_output: Mapping[str, Any]
    """The original model output dict, preserved exactly."""

    context_snapshot: Mapping[str, Any] | None = None
    """External context snapshot — read-only, not merged into model."""

    data_gaps: tuple[str, ...] = ()
    """Data gaps from context assembly."""

    caveats: tuple[str, ...] = ()
    """Caveats / warnings for the prediction."""

    model_boundary: dict = field(default_factory=lambda: {
        "affects_model": False,
        "report_only_or_context_only": True,
        "enters_prediction_engine": False,
    })
    """Model boundary declaration."""

    attached_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When context was attached."""

    def __post_init__(self) -> None:
        if self.attached_at.tzinfo is None or self.attached_at.utcoffset() is None:
            raise ValueError("attached_at must be timezone-aware")

    @property
    def result_probabilities(self) -> Mapping[str, float] | None:
        """Convenience accessor — returns model_output result_probabilities."""
        rp = self.model_output.get("result_probabilities")
        if rp is None:
            rp = self.model_output.get("result_probabilities")
        return rp

    @property
    def advancement_probabilities(self) -> Mapping[str, float] | None:
        """Convenience accessor — returns model_output advancement_probabilities."""
        return self.model_output.get("advancement_probabilities")

    def to_dict(self) -> dict:
        return {
            "model_output": dict(self.model_output),
            "context_snapshot": (
                dict(self.context_snapshot) if self.context_snapshot else None
            ),
            "data_gaps": list(self.data_gaps),
            "caveats": list(self.caveats),
            "model_boundary": dict(self.model_boundary),
            "attached_at": self.attached_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def attach_external_context_to_prediction_output(
    model_output: Mapping[str, Any],
    context_snapshot: Mapping[str, Any] | None = None,
    *,
    data_gaps: tuple[str, ...] = (),
    caveats: tuple[str, ...] = (),
) -> ContextualizedPredictionOutput:
    """Attach external context to a model output WITHOUT modifying it.

    The ``model_output`` is preserved exactly as provided.  Context is stored
    alongside but never merged into the model output.

    Args:
        model_output: The model output dict (e.g. from ``Prediction.to_dict()``).
        context_snapshot: Optional external context snapshot dict.
        data_gaps: Known data gaps.
        caveats: Known caveats.

    Returns:
        ``ContextualizedPredictionOutput`` with model output preserved exactly
        and context attached separately.
    """
    # Deep-copy model_output to prove we don't mutate the original
    preserved = dict(model_output)

    all_caveats = list(caveats)

    # Check for missing probabilities and add caveats (do NOT invent values)
    if not preserved.get("result_probabilities"):
        all_caveats.append(
            "model_output missing result_probabilities — "
            "no fake probabilities generated"
        )
    if not preserved.get("advancement_probabilities"):
        all_caveats.append(
            "model_output missing advancement_probabilities — "
            "no fake advancement probabilities generated"
        )

    # Model boundary caveat
    all_caveats.append(
        "External context is report-only/context-only. "
        "Provider context, odds, scout evidence do NOT modify model probabilities."
    )

    return ContextualizedPredictionOutput(
        model_output=preserved,
        context_snapshot=dict(context_snapshot) if context_snapshot else None,
        data_gaps=data_gaps,
        caveats=tuple(all_caveats),
    )


def build_contextualized_prediction_view(
    model_output: Mapping[str, Any],
    context_assembly_result: MatchContextAssemblyResult | None = None,
) -> ContextualizedPredictionOutput:
    """Build a contextualized prediction view from an assembly result.

    Convenience wrapper around ``attach_external_context_to_prediction_output``
    that extracts context from a ``MatchContextAssemblyResult``.

    Args:
        model_output: The model output dict.
        context_assembly_result: Optional assembly result.

    Returns:
        ``ContextualizedPredictionOutput``.
    """
    snapshot = None
    gaps: tuple[str, ...] = ()
    caveats: list[str] = []

    if context_assembly_result is not None:
        if context_assembly_result.context_snapshot:
            snapshot = context_assembly_result.context_snapshot.to_dict()
        gaps = context_assembly_result.gap_list
        caveats.append(
            f"Provider '{context_assembly_result.provider_name}' "
            f"context is report-only — does not affect model probabilities."
        )

    return attach_external_context_to_prediction_output(
        model_output=model_output,
        context_snapshot=snapshot,
        data_gaps=gaps,
        caveats=tuple(caveats),
    )
