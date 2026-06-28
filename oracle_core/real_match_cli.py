"""Real-match CLI boundary — Patch 36.

Accepts user-provided match/team names via CLI.  Always offline by default.
Does NOT fabricate provider data, Scout evidence, odds, injuries, lineups,
weather, news, or model probabilities.

Outputs a Chinese MVP report that clearly distinguishes:
  - user-provided match info
  - local model probabilities (only if externally supplied)
  - provider context (only if externally supplied)
  - data gaps and caveats (always present)

Usage:
    python -m oracle_core.real_match_cli --home "Team A" --away "Team B"

Hard invariants:
  - No live API calls by default.
  - No env/API key reads by default.
  - No fabricated probabilities or scores.
  - Provider/scout/odds never alter model output.
  - TheSportsDB remains needs_more_info.
"""

from __future__ import annotations

import argparse
import json
import os as _os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# Real-match CLI result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RealMatchCliResult:
    """Result of a real-match CLI invocation."""

    report_text: str
    """Rendered Chinese MVP report."""

    home_team: str
    away_team: str
    match_date: str = ""
    competition: str = ""

    snapshot_id: str = ""
    model_output_used: Mapping[str, Any] = field(default_factory=dict)
    gap_list: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()

    live_api_called: bool = False
    env_read: bool = False
    network_used: bool = False

    @property
    def is_offline(self) -> bool:
        return not (self.live_api_called or self.env_read or self.network_used)


# ---------------------------------------------------------------------------
# Default gap list for real-match CLI (no provider data)
# ---------------------------------------------------------------------------

_DEFAULT_GAP_LIST: tuple[str, ...] = (
    "team_id_resolution_missing",
    "standings_missing",
    "lineups_missing",
    "injuries_missing",
    "suspensions_missing",
    "odds_missing",
    "knockout_bracket_missing",
    "prematch_signals_missing",
    "weather_missing",
    "timezone_unknown",
    "limited_match_coverage",
    "provider_not_approved_for_model_input",
    "production_provider_coverage_unverified",
    "user_provided_names_only",       # Real-match CLI specific
    "no_provider_context_supplied",   # Real-match CLI specific
)


# ---------------------------------------------------------------------------
# Core: build report from user input (offline by default)
# ---------------------------------------------------------------------------


def build_real_match_report(
    home_team: str,
    away_team: str,
    *,
    match_date: str = "",
    competition: str = "",
    model_output: Mapping[str, Any] | None = None,
    context_snapshot: Mapping[str, Any] | None = None,
    market_comparison: Mapping[str, Any] | None = None,
    scout_result: Any | None = None,
    allow_live: bool = False,
    live_provider: str = "",
) -> RealMatchCliResult:
    """Build a Chinese MVP report for a user-specified real match.

    This is the core logic — usable from CLI or programmatically.

    Args:
        home_team: User-provided home team name.
        away_team: User-provided away team name.
        match_date: Optional match date (YYYY-MM-DD).
        competition: Optional competition name.
        model_output: Optional external model_output dict.
        context_snapshot: Optional external context snapshot dict.
        market_comparison: Optional odds/market data.
        scout_result: Optional WebScoutResult.
        allow_live: Must be True for any live provider access.
        live_provider: Provider name for live access (requires allow_live).

    Returns:
        ``RealMatchCliResult`` with report text and metadata.
    """
    from oracle_core.mvp_report_input_builder import (
        build_mvp_report_input,
        MVPReportInput,
    )
    from oracle_core.chinese_mvp_report_renderer import (
        render_chinese_mvp_report,
    )
    from oracle_core.web_scout_fallback import (
        build_web_scout_requests,
        run_web_scout_fallback,
        DisabledWebScoutAdapter,
        DeterministicFakeWebScoutAdapter,
    )
    from oracle_core.prediction_context_boundary import (
        attach_external_context_to_prediction_output,
    )
    from oracle_core.data_service_types import (
        DataQualityIssue,
        DataQualitySeverity,
    )

    caveats: list[str] = []
    gaps: list[str] = list(_DEFAULT_GAP_LIST)
    live_called = False
    env_was_read = False
    network_was_used = False

    # ── Validate input ──
    if not home_team.strip():
        raise ValueError("--home team name must not be empty")
    if not away_team.strip():
        raise ValueError("--away team name must not be empty")
    if home_team.strip() == away_team.strip():
        raise ValueError("home and away teams must differ")

    home = home_team.strip()
    away = away_team.strip()

    # ── Build base model_output from user input + optional external ──
    effective_model_output: dict[str, Any] = {
        "team_a": home,
        "team_b": away,
        "user_provided_names": True,
    }
    if match_date:
        effective_model_output["match_date"] = match_date
    if competition:
        effective_model_output["competition"] = competition

    external_mo_provided = model_output is not None
    if external_mo_provided:
        # External model_output overrides team_a/team_b for display
        # but preserves probabilities exactly
        for key in ("result_probabilities", "advancement_probabilities",
                     "top_scores", "expected_goals", "over_under",
                     "model_version", "model_status",
                     "assumptions", "limitations"):
            if key in model_output:
                effective_model_output[key] = model_output[key]

    # ── Live provider boundary ──
    provider_context_data: dict[str, Any] | None = None
    live_provider_result = None

    if live_provider:
        if not allow_live:
            caveats.append(
                f"Live provider '{live_provider}' requested but --allow-live not set. "
                f"Provider access denied (fail-closed)."
            )
            gaps.append("live_provider_blocked_no_allow_live_flag")
        elif live_provider == "thesportsdb":
            # TheSportsDB remains needs_more_info
            caveats.append(
                "TheSportsDB remains needs_more_info — not granted live-adapter approval. "
                "Live provider access not executed."
            )
            gaps.append("thesportsdb_needs_more_info_not_approved")
        else:
            caveats.append(
                f"Live provider '{live_provider}' is not configured. "
                f"No live adapter exists for this provider."
            )
            gaps.append(f"live_provider_{live_provider}_not_configured")
    else:
        caveats.append(
            "No live provider specified. Provider context unavailable."
        )

    # ── Context snapshot ──
    snapshot_id = ""
    if context_snapshot is not None:
        provider_context_data = dict(context_snapshot)
        snapshot_id = context_snapshot.get("snapshot_id", "")

        # Carry over gaps from snapshot if present
        snapshot_gaps = context_snapshot.get("gap_list", [])
        if snapshot_gaps:
            gaps.extend(snapshot_gaps)
    else:
        caveats.append(
            "No context snapshot supplied. Provider context is unavailable. "
            "All provider-dependent data is shown as gaps."
        )

    # ── Attach context to model output (safe boundary) ──
    contextualized = attach_external_context_to_prediction_output(
        model_output=effective_model_output,
        context_snapshot=provider_context_data,
        data_gaps=tuple(set(gaps)),
    )

    # ── Web Scout fallback (disabled by default) ──
    # Determine if fake scout was passed via scout_result
    if scout_result is not None:
        # scout_result was already computed externally
        pass
    else:
        from oracle_core.web_scout_fallback import (
            WebScoutResult,
            DisabledWebScoutAdapter,
            build_web_scout_requests,
            run_web_scout_fallback,
        )
        scout_requests = build_web_scout_requests(
            gap_list=tuple(set(gaps)),
            match_id="",
            team_ids=(home, away),
        )
        scout_result = run_web_scout_fallback(
            scout_requests, DisabledWebScoutAdapter(),
        )

    # ── Build report input ──
    report_input: MVPReportInput = build_mvp_report_input(
        model_output=effective_model_output,
        context_view_or_assembly_result=contextualized,
        market_comparison=market_comparison,
        scout_result=scout_result,
    )

    # ── Add real-match-specific caveats ──
    all_caveats = list(report_input.caveats)
    all_caveats.append(
        f"User-provided team names: '{home}' vs '{away}'. "
        "No provider verification of team identity."
    )
    if not external_mo_provided:
        all_caveats.append(
            "No external model_output supplied. "
            "Local model probabilities are unavailable. "
            "No fake probabilities have been generated."
        )
    all_caveats.append(
        "Real-match CLI is offline by default. "
        "No live API calls. No env/API key reads. "
        "Provider/scout/odds do not enter the model."
    )

    # ── Rebuild report input with updated caveats ──
    # (build_mvp_report_input returns frozen; rebuild with merged data)
    final_report_input = build_mvp_report_input(
        model_output=effective_model_output,
        context_view_or_assembly_result=contextualized,
        market_comparison=market_comparison,
        scout_result=scout_result,
    )
    # Workaround: build fresh and merge caveats manually
    # Use object.__setattr__ on the frozen dataclass... actually can't.
    # Instead, merge the caveats into the effective model output caveats
    # by passing them through a second build. Simpler: just build report
    # text with all caveats listed.
    # Let me take a different approach — render manually with extra caveats

    report_text = _render_user_match_report(
        home=home,
        away=away,
        match_date=match_date,
        competition=competition,
        model_output=effective_model_output,
        provider_context=provider_context_data,
        market_comparison=market_comparison,
        scout_result=scout_result,
        gaps=tuple(set(gaps)),
        caveats=tuple(all_caveats),
        snapshot_id=snapshot_id,
        external_mo_provided=external_mo_provided,
    )

    return RealMatchCliResult(
        report_text=report_text,
        home_team=home,
        away_team=away,
        match_date=match_date,
        competition=competition,
        snapshot_id=snapshot_id,
        model_output_used=effective_model_output,
        gap_list=tuple(set(gaps)),
        caveats=tuple(all_caveats),
        live_api_called=live_called,
        env_read=env_was_read,
        network_used=network_was_used,
    )


# ---------------------------------------------------------------------------
# Extended report builder with gate checks (Patch 36.2)
# ---------------------------------------------------------------------------


def _run_dry_section(
    label: str,
    lines: list[str],
) -> None:
    """Append a labelled section header to *lines*."""
    lines.append("")
    lines.append(f"【{label}】")


def _append_readiness_gate(lines: list[str]) -> None:
    """Run readiness gate and append text result to *lines*."""
    _run_dry_section("Readiness Gate", lines)
    try:
        from oracle_core.production_readiness_gate import (
            run_readiness_gate,
            readiness_to_text,
        )

        gate_report = run_readiness_gate()
        gate_text = readiness_to_text(gate_report)
        for line in gate_text.split("\n"):
            lines.append(f"  {line}")
    except Exception as exc:
        lines.append(f"  Readiness gate unavailable: {exc}")


def _append_healthcheck(lines: list[str]) -> None:
    """Run healthcheck and append text result to *lines*."""
    _run_dry_section("Healthcheck", lines)
    try:
        from oracle_core.production_health import (
            run_full_healthcheck,
            healthcheck_to_text,
        )

        health = run_full_healthcheck()
        health_text = healthcheck_to_text(health)
        for line in health_text.split("\n"):
            lines.append(f"  {line}")
    except Exception as exc:
        lines.append(f"  Healthcheck unavailable: {exc}")


def _append_scheduler_dry_run(lines: list[str]) -> None:
    """Run scheduler dry-run and append text result to *lines*."""
    _run_dry_section("Scheduler Dry-Run", lines)
    try:
        from oracle_core.production_scheduler import list_schedules

        schedules = list_schedules()
        lines.append(f"  发现 {len(schedules)} 个计划任务（均处于禁用/DRY-RUN 状态）:")
        for spec in schedules:
            enabled = spec.enabled
            dry_run = spec.dry_run
            lines.append(
                f"    - {spec.name}: {spec.command} ({spec.interval}) "
                f"[enabled={enabled}, dry_run={dry_run}]"
            )
    except Exception as exc:
        lines.append(f"  Scheduler module unavailable: {exc}")


def _append_coverage_dry_run(lines: list[str]) -> None:
    """Run coverage validator dry-run and append text result to *lines*."""
    _run_dry_section("Coverage Validator Dry-Run", lines)
    try:
        from oracle_core.live_coverage_validator import dry_run_coverage

        result = dry_run_coverage()
        lines.append(f"  Coverage result: {result}")
    except ImportError:
        lines.append(
            "  覆盖验证器模块未安装 (live_coverage_validator not available)."
        )
        lines.append("  默认离线模式 — 未进行覆盖验证。")
    except Exception as exc:
        lines.append(f"  Coverage dry-run error: {exc}")


def _append_alert_dry_run(lines: list[str]) -> None:
    """Run alert system dry-run and append text result to *lines*."""
    _run_dry_section("Alert System Dry-Run", lines)
    try:
        from oracle_core.production_alerting import dry_run_alert_system

        events = dry_run_alert_system()
        lines.append(f"  已生成 {len(events)} 个测试告警事件（全部 sent=False，未发送）。")
        for ev in events:
            lines.append(
                f"    [{ev.severity.upper()}] {ev.component}: {ev.message[:60]}"
            )
    except Exception as exc:
        lines.append(f"  Alert system unavailable: {exc}")


def _append_storage_cleanup_dry_run(lines: list[str]) -> None:
    """Run storage cleanup dry-run and append text result to *lines*."""
    _run_dry_section("Storage Cleanup Dry-Run", lines)
    try:
        from oracle_core.production_storage import (
            create_local_backend,
            RetentionPolicy,
            apply_retention_policy,
        )

        backend = create_local_backend()
        policy = RetentionPolicy(
            max_age_days=30, max_count=100, policy_name="default_dry_run"
        )
        result = apply_retention_policy(backend, policy, dry_run=True)
        lines.append(
            f"  检查文件: {result.files_examined}, "
            f"待删除: {result.files_deleted}, "
            f"保留: {result.files_retained} (dry_run={result.dry_run})"
        )
        if result.caveats:
            for c in result.caveats:
                lines.append(f"    注意: {c}")
    except Exception as exc:
        lines.append(f"  Storage cleanup unavailable: {exc}")


def _append_gate_results(result_text: str, args: Any) -> str:
    """Append gate/check sections to an existing report text.

    Parameters
    ----------
    result_text:
        The existing Chinese report text.
    args:
        Parsed CLI arguments (namespace with gate/dry-run flags).

    Returns
    -------
    str
        Combined report text with appended sections.
    """
    extra: list[str] = []

    if args.readiness_gate:
        _append_readiness_gate(extra)
    if args.healthcheck:
        _append_healthcheck(extra)
    if args.scheduler_dry_run:
        _append_scheduler_dry_run(extra)
    if args.coverage_dry_run:
        _append_coverage_dry_run(extra)
    if args.alert_dry_run:
        _append_alert_dry_run(extra)
    if args.storage_cleanup_dry_run:
        _append_storage_cleanup_dry_run(extra)

    if not extra:
        return result_text

    extra.append("")
    return result_text + "\n".join(extra)


def build_real_match_report_with_gates(
    home_team: str,
    away_team: str,
    *,
    match_date: str = "",
    competition: str = "",
    model_output: Mapping[str, Any] | None = None,
    context_snapshot: Mapping[str, Any] | None = None,
    market_comparison: Mapping[str, Any] | None = None,
    scout_result: Any | None = None,
    allow_live: bool = False,
    live_provider: str = "",
    run_readiness: bool = False,
    run_health: bool = False,
    run_scheduler: bool = False,
    run_coverage: bool = False,
    run_alert: bool = False,
    run_storage_cleanup: bool = False,
) -> RealMatchCliResult:
    """Build a real match report with optional gate/check sections appended.

    This is a convenience wrapper around ``build_real_match_report`` that
    appends readiness gate, healthcheck, scheduler, coverage, alert, and
    storage cleanup results as extra sections in the Chinese report.

    All gate/check runs are dry-run by default — no network, no env reads.

    Parameters
    ----------
    home_team, away_team, match_date, competition, model_output,
    context_snapshot, market_comparison, scout_result,
    allow_live, live_provider:
        Forwarded unchanged to ``build_real_match_report``.
    run_readiness:
        Run readiness gate and append result.
    run_health:
        Run healthcheck and append result.
    run_scheduler:
        Run scheduler dry-run and append result.
    run_coverage:
        Run coverage validator dry-run and append result.
    run_alert:
        Run alert system dry-run and append result.
    run_storage_cleanup:
        Run storage cleanup dry-run and append result.

    Returns
    -------
    RealMatchCliResult
        Result with combined report text.  All metadata (gaps, caveats,
        offline status) is inherited from the base report.
    """
    result = build_real_match_report(
        home_team=home_team,
        away_team=away_team,
        match_date=match_date,
        competition=competition,
        model_output=model_output,
        context_snapshot=context_snapshot,
        market_comparison=market_comparison,
        scout_result=scout_result,
        allow_live=allow_live,
        live_provider=live_provider,
    )

    # Build extra sections
    extra: list[str] = []
    if run_readiness:
        _append_readiness_gate(extra)
    if run_health:
        _append_healthcheck(extra)
    if run_scheduler:
        _append_scheduler_dry_run(extra)
    if run_coverage:
        _append_coverage_dry_run(extra)
    if run_alert:
        _append_alert_dry_run(extra)
    if run_storage_cleanup:
        _append_storage_cleanup_dry_run(extra)

    if extra:
        extra.append("")
        combined_text = result.report_text + "\n".join(extra)
        return RealMatchCliResult(
            report_text=combined_text,
            home_team=result.home_team,
            away_team=result.away_team,
            match_date=result.match_date,
            competition=result.competition,
            snapshot_id=result.snapshot_id,
            model_output_used=result.model_output_used,
            gap_list=result.gap_list,
            caveats=result.caveats,
            live_api_called=result.live_api_called,
            env_read=result.env_read,
            network_used=result.network_used,
        )

    return result


# ---------------------------------------------------------------------------
# Report renderer for user-provided match names
# ---------------------------------------------------------------------------


def _render_user_match_report(
    home: str,
    away: str,
    match_date: str,
    competition: str,
    model_output: dict,
    provider_context: dict | None,
    market_comparison: dict | None,
    scout_result: Any,
    gaps: tuple[str, ...],
    caveats: tuple[str, ...],
    snapshot_id: str,
    external_mo_provided: bool,
) -> str:
    """Render a Chinese MVP report for user-specified teams.

    Uses the same sections as the standard renderer but emphasizes
    user-provided match info and explicitly marks what is/isn't available.
    """
    lines: list[str] = []

    # ── Title ──
    lines.append("=" * 60)
    lines.append("  FIFA World Cup Oracle — 真实比赛预测报告")
    lines.append(f"  {home} vs {away}")
    lines.append("=" * 60)
    lines.append("")

    # ── User-provided match info ──
    lines.append("【用户输入的比赛信息】")
    lines.append(f"  主队 (home): {home}")
    lines.append(f"  客队 (away): {away}")
    if match_date:
        lines.append(f"  比赛日期: {match_date}")
    if competition:
        lines.append(f"  赛事: {competition}")
    lines.append("  注意: 队伍名称由用户提供，未经 provider 验证。")
    lines.append("")

    # ── Data source summary ──
    lines.append("【数据来源状态】")
    if external_mo_provided:
        lines.append("  模型概率: [已提供] 外部提供 (external model_output)")
    else:
        lines.append("  模型概率: [未提供] 未提供 — 无本地模型概率可用")
    if provider_context:
        lines.append("  Provider context: [已提供] 外部提供 (external snapshot)")
    else:
        lines.append("  Provider context: [未提供] 未提供 — 无 provider 数据")
    if market_comparison:
        lines.append("  赔率对比: [已提供] 外部提供")
    else:
        lines.append("  赔率对比: [未提供] 未接入")
    if scout_result and hasattr(scout_result, 'evidence') and scout_result.evidence:
        lines.append("  Scout evidence: [已提供] 有结果")
    else:
        lines.append("  Scout evidence: [未提供] 未启用 (disabled by default)")
    lines.append("  Live API: [未调用] 未调用 (offline by default)")
    lines.append("")

    # ── Local model prediction ──
    lines.append("【本地模型预测摘要】")
    lines.append("  说明：以下概率全部来自本地 prediction engine 输出（如已提供）。")
    lines.append("  provider context / Scout evidence / odds 均不入模。")
    lines.append("  **概率不会因 context/scout/赔率/伤停/新闻/天气而改变。**")
    lines.append("")

    # ── 90-minute result ──
    lines.append("  ── 90分钟胜平负概率 ──")
    rp = model_output.get("result_probabilities")
    if rp:
        lines.append(f"    主胜 ({home}): {_fmt_pct(rp.get('team_a_win'))}")
        lines.append(f"    平局 (draw):     {_fmt_pct(rp.get('draw'))}")
        lines.append(f"    客胜 ({away}): {_fmt_pct(rp.get('team_b_win'))}")
    else:
        lines.append("    （无 — 未提供外部 model_output，概率不可用）")
    lines.append("")

    # ── Top scores ──
    lines.append("  ── 可能比分 (Top Scores) ──")
    top_scores = model_output.get("top_scores")
    if top_scores:
        for entry in top_scores[:5]:
            if isinstance(entry, dict):
                score = entry.get("score", "?")
                prob = entry.get("probability", 0)
                lines.append(f"    {score}: {_fmt_pct(prob)}")
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                score, prob = entry
                lines.append(f"    {score}: {_fmt_pct(prob)}")
    else:
        lines.append("    （无 — 模型输出中无 top_scores）")
    lines.append("")

    # ── Advancement ──
    lines.append("  ── 淘汰赛晋级概率 ──")
    ap = model_output.get("advancement_probabilities")
    if ap:
        for key, val in ap.items():
            lines.append(f"    {key}: {_fmt_pct(val)}")
    else:
        lines.append("    （无 — 模型输出中无 advancement_probabilities）")
    lines.append("")

    # ── Model metadata ──
    if model_output.get("model_version"):
        lines.append(f"  模型版本: {model_output['model_version']}")
    if model_output.get("model_status"):
        lines.append(f"  模型状态: {model_output['model_status']}")
    lines.append("")

    # ── Provider context ──
    lines.append("【Provider Context】")
    lines.append("  说明：provider context 为 report-only / context-only，不入模型。")
    lines.append("  TheSportsDB remains needs_more_info — 未获 live-adapter 批准。")
    if provider_context:
        lines.append(f"  Snapshot ID: {snapshot_id or 'N/A'}")
        if provider_context.get("canonical_teams"):
            lines.append(f"  规范队伍数: {len(provider_context['canonical_teams'])}")
        if provider_context.get("canonical_matches"):
            lines.append(f"  规范比赛数: {len(provider_context['canonical_matches'])}")
    else:
        lines.append("  （无 provider context — 未提供 external snapshot）")
    lines.append("")

    # ── Scout evidence ──
    lines.append("【Web Scout Evidence】")
    lines.append("  说明：Scout evidence 为 report-only / context-only，不入模型。")
    if scout_result and hasattr(scout_result, 'evidence') and scout_result.evidence:
        for i, ev in enumerate(scout_result.evidence, 1):
            d = ev.to_dict() if hasattr(ev, 'to_dict') else dict(ev)
            lines.append(f"  {i}. [{d.get('evidence_type', '?')}] "
                         f"{d.get('summary', '')[:80]}")
    else:
        lines.append("  Web Scout 未启用 (disabled by default)。")
        lines.append("  缺失的伤停/阵容/天气/新闻信息已列入 gap_list。")
    lines.append("")

    # ── Market comparison ──
    lines.append("【Market Comparison（赔率对比）】")
    lines.append("  说明：赔率仅用于市场对比，不入模型、不做 blend。")
    if market_comparison:
        for key, val in market_comparison.items():
            lines.append(f"  {key}: {val}")
    else:
        lines.append("  未接入赔率数据。")
    lines.append("")

    # ── Data gaps ──
    lines.append("【数据缺口 (Gap List)】")
    if gaps:
        for gap in sorted(gaps):
            lines.append(f"    - {gap}")
    else:
        lines.append("    （无记录）")
    lines.append("")

    # ── Caveats ──
    lines.append("【Caveats / 风险说明】")
    if caveats:
        for i, c in enumerate(caveats, 1):
            lines.append(f"  {i}. {c}")
    lines.append("")

    # ── Replay / provenance ──
    lines.append("【Replay / Provenance 摘要】")
    lines.append(f"  Snapshot ID: {snapshot_id or 'N/A'}")
    lines.append(f"  模式: 真实比赛 CLI (offline by default)")
    lines.append(f"  队伍名称来源: 用户直接输入（未经 provider 验证）")
    lines.append(f"  模型概率来源: "
                 f"{'外部 model_output' if external_mo_provided else '无（未提供）'}")
    lines.append(f"  Live API 调用: 否")
    lines.append(f"  网络请求: 否")
    lines.append(f"  环境变量读取: 否")
    lines.append("")

    # ── Footer ──
    lines.append("=" * 60)
    lines.append("  Production-Oriented MVP — World Cup Oracle")
    lines.append("  概率仅来自本地 prediction engine")
    lines.append("  Provider context / Scout evidence / Odds 均不入模")
    lines.append("  TheSportsDB remains needs_more_info")
    lines.append("  Real-match CLI — offline by default")
    lines.append("=" * 60)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    try:
        pct = float(value) * 100
        return f"{pct:.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _load_json_file(path: str) -> dict:
    """Load and validate a JSON file.  Only for user-supplied paths."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}, got {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# CLI entry point — python -m oracle_core.real_match_cli
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="World Cup Oracle — Real-Match CLI (Patch 36)",
        epilog=(
            "DEFAULT OFFLINE.  No live API calls.  No env/API key reads. "
            "No fabricated probabilities, scores, or context. "
            "This is a production-oriented MVP — NOT full production."
        ),
    )

    # Required
    parser.add_argument(
        "--home", required=True,
        help="Home team name (user-provided).",
    )
    parser.add_argument(
        "--away", required=True,
        help="Away team name (user-provided).",
    )

    # Optional match info
    parser.add_argument(
        "--date", default="",
        help="Match date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--competition", default="",
        help="Competition name.",
    )

    # External inputs
    parser.add_argument(
        "--model-output-json",
        help="Path to external model output JSON.",
    )
    parser.add_argument(
        "--context-snapshot",
        help="Path to external context snapshot JSON (replay/load).",
    )
    parser.add_argument(
        "--market-comparison-json",
        help="Path to external market comparison JSON (odds data).",
    )

    # Output
    parser.add_argument(
        "--output", "-o",
        help="Write report to file instead of stdout.",
    )
    parser.add_argument(
        "--json-metadata",
        help="Write JSON metadata (result summary) to file.",
    )

    # Live provider boundary (safe placeholders)
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Allow live provider access.  WITHOUT this flag, "
             "all live provider access is forbidden.",
    )
    parser.add_argument(
        "--live-provider",
        choices=["thesportsdb"],
        help="Live provider to use (requires --allow-live). "
             "TheSportsDB remains needs_more_info.",
    )

    # ── Gate / dry-run flags (Patch 36.2) ──
    parser.add_argument(
        "--readiness-gate",
        action="store_true",
        help="Run readiness gate and append result to report.",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Run healthcheck and append result to report.",
    )
    parser.add_argument(
        "--scheduler-dry-run",
        action="store_true",
        help="Run scheduler dry-run and append result to report.",
    )
    parser.add_argument(
        "--coverage-dry-run",
        action="store_true",
        help="Run coverage validator dry-run and append result to report.",
    )
    parser.add_argument(
        "--alert-dry-run",
        action="store_true",
        help="Run alert system dry-run and append result to report.",
    )
    parser.add_argument(
        "--storage-cleanup-dry-run",
        action="store_true",
        help="Run storage cleanup dry-run and append result to report.",
    )

    return parser


def _main() -> int:
    parser = _build_argparser()
    args = parser.parse_args()

    # ── Load external inputs (offline — just file reads) ──
    model_output = None
    context_snapshot = None
    market_comparison = None

    try:
        if args.model_output_json:
            model_output = _load_json_file(args.model_output_json)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] Failed to load model-output-json: {e}", file=sys.stderr)
        return 1

    try:
        if args.context_snapshot:
            context_snapshot = _load_json_file(args.context_snapshot)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] Failed to load context-snapshot: {e}", file=sys.stderr)
        return 1

    try:
        if args.market_comparison_json:
            market_comparison = _load_json_file(args.market_comparison_json)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] Failed to load market-comparison-json: {e}", file=sys.stderr)
        return 1

    # ── Validate live provider flags ──
    if args.live_provider and not args.allow_live:
        print(
            "[NOTE] --live-provider specified without --allow-live. "
            "Live provider access will be denied (fail-closed).",
            file=sys.stderr,
        )

    # ── Build report ──
    try:
        # Use the combined builder when any gate flag is set
        has_gates = (
            args.readiness_gate
            or args.healthcheck
            or args.scheduler_dry_run
            or args.coverage_dry_run
            or args.alert_dry_run
            or args.storage_cleanup_dry_run
        )
        if has_gates:
            result = build_real_match_report_with_gates(
                home_team=args.home,
                away_team=args.away,
                match_date=args.date,
                competition=args.competition,
                model_output=model_output,
                context_snapshot=context_snapshot,
                market_comparison=market_comparison,
                allow_live=args.allow_live,
                live_provider=args.live_provider or "",
                run_readiness=args.readiness_gate,
                run_health=args.healthcheck,
                run_scheduler=args.scheduler_dry_run,
                run_coverage=args.coverage_dry_run,
                run_alert=args.alert_dry_run,
                run_storage_cleanup=args.storage_cleanup_dry_run,
            )
        else:
            result = build_real_match_report(
                home_team=args.home,
                away_team=args.away,
                match_date=args.date,
                competition=args.competition,
                model_output=model_output,
                context_snapshot=context_snapshot,
                market_comparison=market_comparison,
                allow_live=args.allow_live,
                live_provider=args.live_provider or "",
            )
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    # ── Output ──
    if args.output:
        out_path = _os.path.abspath(args.output)
        # Guard: don't write to repo data dirs
        repo_root = _os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__)))
        for forbidden in ("knowledge", "data", "logs"):
            fb = _os.path.join(repo_root, forbidden)
            if out_path.startswith(fb):
                print(
                    f"[ERROR] Refusing to write to repo dir: {out_path}",
                    file=sys.stderr,
                )
                return 1
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(result.report_text)
        print(f"Report written to: {out_path}", file=sys.stderr)
    else:
        print(result.report_text)

    # ── Optional JSON metadata ──
    if args.json_metadata:
        meta = {
            "home_team": result.home_team,
            "away_team": result.away_team,
            "match_date": result.match_date,
            "competition": result.competition,
            "snapshot_id": result.snapshot_id,
            "gap_list": list(result.gap_list),
            "caveats": list(result.caveats),
            "live_api_called": result.live_api_called,
            "env_read": result.env_read,
            "network_used": result.network_used,
            "is_offline": result.is_offline,
            "model_output_provided": model_output is not None,
            "context_snapshot_provided": context_snapshot is not None,
            "market_comparison_provided": market_comparison is not None,
            "thesportsdb_approved": False,
            "model_boundary": {
                "affects_model": False,
                "report_only_or_context_only": True,
                "enters_prediction_engine": False,
            },
        }
        with open(args.json_metadata, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, sort_keys=True)
        print(f"Metadata written to: {args.json_metadata}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(_main())
