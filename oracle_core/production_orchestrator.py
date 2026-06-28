"""Production orchestrator — Patch 36.

Wires together the full production pipeline from input through report
rendering.  Does NOT call the prediction engine.  Does NOT calculate or
invent probabilities.  Preserves ``model_output`` exactly.

Pipeline:
  1. Validate input.
  2. Attach external context to model output (if supplied).
  3. Run live provider runtime (if configured + allowed).
  4. Run web scout runtime (if configured + allowed).
  5. Run odds provider runtime (if configured + allowed).
  6. Build ``MVPReportInput``.
  7. Render Chinese MVP report.
  8. Create audit record.
  9. Return ``OrchestratorOutput``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from oracle_core.production_config import (
    ProductionConfig,
    DEFAULT_OFFLINE_CONFIG,
    validate_config,
)
from oracle_core.prediction_context_boundary import (
    attach_external_context_to_prediction_output,
)
from oracle_core.web_scout_runtime import (
    WebScoutRuntimeRequest,
    WebScoutRuntimeResponse,
    create_web_scout_runtime,
    run_web_scout,
)
from oracle_core.mvp_report_input_builder import (
    build_mvp_report_input,
    MVPReportInput,
)
from oracle_core.chinese_mvp_report_renderer import (
    render_chinese_mvp_report,
)


# ---------------------------------------------------------------------------
# Orchestrator input / output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrchestratorInput:
    """Input to the production pipeline."""

    home_team: str
    """Home team name."""

    away_team: str
    """Away team name."""

    match_date: str = ""
    """Match date (ISO format or free text)."""

    competition: str = ""
    """Competition name, e.g. ``"FIFA World Cup 2026"``."""

    model_output: Mapping[str, Any] | None = None
    """Model output dict (e.g. from ``Prediction.to_dict()``).  Optional."""

    context_snapshot: Mapping[str, Any] | None = None
    """Optional external context snapshot dict."""

    config: ProductionConfig = field(default_factory=lambda: DEFAULT_OFFLINE_CONFIG)
    """Production configuration.  Defaults to fully locked-down offline."""

    allow_live: bool = False
    """Opt-in flag for live provider network access."""

    allow_web_scout: bool = False
    """Opt-in flag for web scout network access."""

    def __post_init__(self) -> None:
        if not self.home_team.strip():
            raise ValueError("home_team must not be empty")
        if not self.away_team.strip():
            raise ValueError("away_team must not be empty")


@dataclass(frozen=True)
class OrchestratorOutput:
    """Output of the production pipeline."""

    report_text: str = ""
    """The rendered Chinese report string."""

    model_output_used: Mapping[str, Any] = field(default_factory=dict)
    """Model output dict that was used (preserved exactly)."""

    provider_context_used: Mapping[str, Any] | None = None
    """Provider context that was used (if any)."""

    scout_result: WebScoutRuntimeResponse | None = None
    """Web Scout runtime response (if any)."""

    odds_result: Any | None = None
    """Odds provider runtime result (if any)."""

    audit_record: Mapping[str, Any] = field(default_factory=dict)
    """Audit record describing what happened during the pipeline run."""

    gaps: tuple[str, ...] = ()
    """All data gaps from the pipeline run."""

    caveats: tuple[str, ...] = ()
    """All caveats / warnings from the pipeline run."""

    snapshot_id: str = ""
    """Replay snapshot ID, if available."""

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """Additional metadata about the pipeline run."""

    completed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When the pipeline completed."""

    def __post_init__(self) -> None:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")


# ---------------------------------------------------------------------------
# Internal helpers — stub runtime wrappers
# ---------------------------------------------------------------------------


def _run_live_provider_if_configured(
    config: ProductionConfig,
    allow_live: bool,
    home_team: str,
    away_team: str,
) -> tuple[Mapping[str, Any] | None, list[str], list[str]]:
    """Attempt to run the live provider runtime.

    Returns ``(context, gaps, caveats)``.  Context is ``None`` when
    the provider is not configured or not allowed.
    """
    gaps: list[str] = []
    caveats: list[str] = []

    if config.runtime_mode != "live_opt_in":
        gaps.append("live_provider_not_enabled:runtime_mode_not_live_opt_in")
        caveats.append(
            "Live provider runtime is not enabled. "
            "Set runtime_mode='live_opt_in' to enable."
        )
        return None, gaps, caveats

    if not config.network_allowed:
        gaps.append("live_provider_not_enabled:network_not_allowed")
        caveats.append(
            "Live provider runtime requires network_allowed=True."
        )
        return None, gaps, caveats

    if not allow_live:
        gaps.append("live_provider_not_allowed:allow_live_flag_false")
        caveats.append(
            "Live provider runtime is configured but not allowed "
            "for this request. Set allow_live=True to enable."
        )
        return None, gaps, caveats

    if config.provider_mode != "enabled":
        gaps.append(f"live_provider_not_enabled:provider_mode={config.provider_mode}")
        caveats.append(
            "Live provider runtime is not enabled. "
            f"provider_mode='{config.provider_mode}'."
        )
        return None, gaps, caveats

    # Stub: live provider runtime not yet implemented
    gaps.append("live_provider_runtime_not_implemented")
    caveats.append(
        "Live provider runtime is not yet implemented. "
        "Provider context is unavailable for this pipeline run."
    )
    return None, gaps, caveats


def _run_odds_if_configured(
    config: ProductionConfig,
    allow_odds: bool,
) -> tuple[Any | None, list[str], list[str]]:
    """Attempt to run the odds provider runtime.

    Returns ``(odds_result, gaps, caveats)``.  Result is ``None`` when
    the provider is not configured or not allowed.
    """
    gaps: list[str] = []
    caveats: list[str] = []

    if not allow_odds:
        gaps.append("odds_provider_not_allowed:allow_odds_flag_false")
        caveats.append(
            "Odds provider runtime is not allowed for this request."
        )
        return None, gaps, caveats

    if config.odds_mode != "enabled":
        gaps.append(f"odds_provider_not_enabled:odds_mode={config.odds_mode}")
        caveats.append(
            "Odds provider runtime is not enabled."
        )
        return None, gaps, caveats

    if config.runtime_mode == "offline":
        gaps.append("odds_provider_not_enabled:offline_mode")
        caveats.append(
            "Cannot run odds provider in offline mode."
        )
        return None, gaps, caveats

    # Stub: odds provider runtime not yet implemented
    gaps.append("odds_provider_runtime_not_implemented")
    caveats.append(
        "Odds provider runtime is not yet implemented. "
        "Market odds are unavailable for this pipeline run."
    )
    return None, gaps, caveats


def _is_scout_allowed(
    config: ProductionConfig,
    allow_web_scout: bool,
) -> tuple[bool, list[str], list[str]]:
    """Check whether web scout is allowed.

    Returns ``(allowed, gaps, caveats)``.
    """
    gaps: list[str] = []
    caveats: list[str] = []

    if not allow_web_scout:
        gaps.append("web_scout_not_allowed:allow_web_scout_flag_false")
        caveats.append(
            "Web Scout runtime is not allowed for this request. "
            "Set allow_web_scout=True to enable."
        )
        return False, gaps, caveats

    if config.scout_mode != "enabled":
        gaps.append(f"web_scout_not_enabled:scout_mode={config.scout_mode}")
        caveats.append(
            "Web Scout runtime is not enabled."
        )
        return False, gaps, caveats

    if config.runtime_mode == "offline":
        gaps.append("web_scout_not_enabled:offline_mode")
        caveats.append(
            "Cannot run web scout in offline mode."
        )
        return False, gaps, caveats

    return True, gaps, caveats


# ---------------------------------------------------------------------------
# Production pipeline
# ---------------------------------------------------------------------------


def run_production_pipeline(
    pipeline_input: OrchestratorInput,
) -> OrchestratorOutput:
    """Run the full production pipeline.

    Args:
        pipeline_input: The orchestrator input with teams, config, and
            optional model output / context.

    Returns:
        ``OrchestratorOutput`` with the rendered report, audit record,
        gaps, and caveats.

    Rules:
        - Does NOT call the prediction engine.
        - Does NOT calculate or invent probabilities.
        - Preserves ``model_output`` exactly.
        - Provider / scout / odds are report-only/context-only.
        - Outputs gaps/caveats for ALL missing data.
        - No fake data anywhere.
    """
    all_gaps: list[str] = []
    all_caveats: list[str] = []

    # ── Step 1: Validate input ──
    validate_config(pipeline_input.config)

    # ── Step 2: Attach context to model output (if supplied) ──
    model_output_used: Mapping[str, Any] = {}
    contextualized = None
    snapshot_id = ""

    if pipeline_input.model_output is not None:
        contextualized = attach_external_context_to_prediction_output(
            model_output=pipeline_input.model_output,
            context_snapshot=pipeline_input.context_snapshot,
        )
        model_output_used = contextualized.model_output
        all_gaps.extend(contextualized.data_gaps)
        all_caveats.extend(contextualized.caveats)
    else:
        all_caveats.append(
            "No model_output provided. "
            "Prediction probabilities are not available for report generation."
        )
        all_gaps.append("model_output_missing")

    # ── Step 3: Run live provider runtime (if configured + allowed) ──
    provider_context, live_gaps, live_caveats = _run_live_provider_if_configured(
        pipeline_input.config,
        pipeline_input.allow_live,
        pipeline_input.home_team,
        pipeline_input.away_team,
    )
    all_gaps.extend(live_gaps)
    all_caveats.extend(live_caveats)

    # ── Step 4: Run web scout runtime (if configured + allowed) ──
    scout_allowed, scout_allowed_gaps, scout_allowed_caveats = _is_scout_allowed(
        pipeline_input.config,
        pipeline_input.allow_web_scout,
    )
    all_gaps.extend(scout_allowed_gaps)
    all_caveats.extend(scout_allowed_caveats)

    scout_response: WebScoutRuntimeResponse | None = None
    if scout_allowed:
        scout_adapter = create_web_scout_runtime(
            provider_name=pipeline_input.config.allowed_provider_names[0]
            if pipeline_input.config.allowed_provider_names
            else "",
            allow_web_scout=pipeline_input.config.runtime_mode == "live_opt_in",
        )
        scout_request = WebScoutRuntimeRequest(
            query_topics=("injuries", "lineups", "suspensions", "weather", "news"),
            match_id="",
            team_ids=(),
            allow_web_scout=pipeline_input.allow_web_scout,
            max_results_per_topic=5,
        )
        scout_response = run_web_scout(scout_adapter, scout_request)
        all_gaps.extend(scout_response.gaps)
        all_caveats.extend(scout_response.caveats)
    else:
        all_caveats.append(
            "Web Scout runtime is not allowed or not enabled. "
            "No scout evidence gathered."
        )

    # ── Step 5: Run odds provider runtime (if configured + allowed) ──
    odds_result, odds_gaps, odds_caveats = _run_odds_if_configured(
        pipeline_input.config,
        pipeline_input.config.runtime_mode == "live_opt_in",
    )
    all_gaps.extend(odds_gaps)
    all_caveats.extend(odds_caveats)

    # ── Step 6: Build report input ──
    report_input: MVPReportInput = build_mvp_report_input(
        model_output=model_output_used,
        context_view_or_assembly_result=contextualized,
        market_comparison=None,
        scout_result=scout_response,
    )

    # ── Step 7: Render Chinese report ──
    report_text = render_chinese_mvp_report(report_input)

    # ── Step 8: Create audit record ──
    now = datetime.now(timezone.utc)
    audit_record: dict[str, Any] = {
        "orchestrator_version": "production-v1",
        "pipeline_steps": [
            "input_validation",
            "context_attachment",
            "live_provider_runtime",
            "web_scout_runtime",
            "odds_provider_runtime",
            "report_input_builder",
            "report_renderer",
        ],
        "model_output_provided": pipeline_input.model_output is not None,
        "context_snapshot_provided": pipeline_input.context_snapshot is not None,
        "live_provider_ran": provider_context is not None,
        "web_scout_ran": scout_response is not None and scout_response.success,
        "odds_provider_ran": odds_result is not None,
        "network_called": (
            (scout_response is not None and scout_response.network_called)
            or False
        ),
        "env_read": (
            (scout_response is not None and scout_response.env_read)
            or False
        ),
        "runtime_mode": pipeline_input.config.runtime_mode,
        "generated_at": now.isoformat(),
    }

    # ── Step 9: Return output ──
    return OrchestratorOutput(
        report_text=report_text,
        model_output_used=dict(model_output_used),
        provider_context_used=(
            dict(provider_context) if provider_context else None
        ),
        scout_result=scout_response,
        odds_result=odds_result,
        audit_record=audit_record,
        gaps=tuple(all_gaps),
        caveats=tuple(all_caveats),
        snapshot_id=snapshot_id,
        metadata={
            "home_team": pipeline_input.home_team,
            "away_team": pipeline_input.away_team,
            "match_date": pipeline_input.match_date,
            "competition": pipeline_input.competition,
            "config_mode": pipeline_input.config.runtime_mode,
        },
    )
