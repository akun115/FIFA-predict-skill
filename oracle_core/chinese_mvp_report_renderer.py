"""Chinese MVP report renderer — Patch 34 Part 2.

Renders ``MVPReportInput`` into a structured Chinese-language prediction
report.  Only displays probabilities that exist in model_output.  Does NOT
invent fake probabilities, scores, or advancement probabilities.

Context, scout evidence, and market data are clearly labeled as
report-only/context-only.
"""

from __future__ import annotations

from oracle_core.mvp_report_input_builder import MVPReportInput


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_chinese_mvp_report(report_input: MVPReportInput) -> str:
    """Render a Chinese MVP prediction report from ``MVPReportInput``.

    Args:
        report_input: The assembled report input.

    Returns:
        A Chinese-language string containing the full report.

    Rules:
        - Only displays probabilities present in model_output.
        - Does NOT generate fake probabilities, scores, or advancement.
        - Clearly labels context as report-only/context-only.
        - Includes data gaps, caveats, and provenance.
    """
    lines: list[str] = []
    ri = report_input
    mo = ri.model_output

    # ── 1. Title ──
    team_a = mo.get("team_a", "Unknown A")
    team_b = mo.get("team_b", "Unknown B")
    lines.append("=" * 60)
    lines.append(f"  FIFA World Cup Oracle — MVP 预测报告")
    lines.append(f"  {team_a} vs {team_b}")
    lines.append("=" * 60)
    lines.append("")

    # ── 2. Match info ──
    lines.append("【比赛信息】")
    lines.append(f"  队伍A: {team_a}")
    lines.append(f"  队伍B: {team_b}")
    if mo.get("model_version"):
        lines.append(f"  模型版本: {mo['model_version']}")
    if mo.get("model_status"):
        lines.append(f"  模型状态: {mo['model_status']}")
    lines.append("")

    # ── 3. Local model prediction summary ──
    lines.append("【本地模型预测摘要】")
    lines.append("  说明：以下概率全部来自本地 prediction engine 输出。")
    lines.append("  provider context / Scout evidence / odds 均不入模。")
    lines.append("")

    # ── 4. 90-minute result probabilities ──
    lines.append("  ── 90分钟胜平负概率 ──")
    rp = mo.get("result_probabilities")
    if rp:
        lines.append(f"    主胜 (team_a_win): {_fmt_pct(rp.get('team_a_win'))}")
        lines.append(f"    平局 (draw):       {_fmt_pct(rp.get('draw'))}")
        lines.append(f"    客胜 (team_b_win): {_fmt_pct(rp.get('team_b_win'))}")
    else:
        lines.append("    （模型输出中无 result_probabilities）")
    lines.append("")

    # ── 5. Top scores ──
    lines.append("  ── 可能比分 (Top Scores) ──")
    top_scores = mo.get("top_scores")
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
        lines.append("    （模型输出中无 top_scores）")
    lines.append("")

    # ── 6. Advancement probabilities ──
    lines.append("  ── 淘汰赛晋级概率 ──")
    ap = mo.get("advancement_probabilities")
    if ap:
        for key, val in ap.items():
            lines.append(f"    {key}: {_fmt_pct(val)}")
    else:
        lines.append("    （模型输出中无 advancement_probabilities）")
    lines.append("")

    # ── 7. Free provider context ──
    lines.append("【免费 Provider Context】")
    lines.append("  说明：以下为免费公开数据提供商 (TheSportsDB) 提供的 context。")
    lines.append("  provider context 为 report-only / context-only，不入模型。")
    lines.append("  TheSportsDB remains needs_more_info — 未 approved_for_live_adapter。")
    if ri.provider_context:
        ctx = ri.provider_context
        lines.append(f"  数据源: {ri.provider_name or '未知'}")
        if ctx.get("canonical_teams"):
            lines.append(f"  规范队伍数: {len(ctx['canonical_teams'])}")
        if ctx.get("canonical_matches"):
            lines.append(f"  规范比赛数: {len(ctx['canonical_matches'])}")
        if ri.snapshot_id:
            lines.append(f"  Snapshot ID: {ri.snapshot_id}")
    else:
        lines.append("  （无 provider context 数据）")
    lines.append("")

    # ── 8. Web Scout evidence ──
    lines.append("【Web Scout Evidence】")
    lines.append("  说明：Web Scout evidence 为 report-only / context-only，不入模型。")
    lines.append("  Scout 不会修改 xG、概率、赔率或队伍实力。")
    if ri.scout_evidence:
        for i, ev in enumerate(ri.scout_evidence, 1):
            evidence_type = ev.get("evidence_type", "unknown")
            summary = ev.get("summary", "")
            confidence = ev.get("confidence", "low")
            source = ev.get("source_url_or_reference", "")
            lines.append(f"  {i}. [{evidence_type}] {summary[:100]}")
            lines.append(f"     可信度: {confidence} | 来源: {source}")
    else:
        lines.append("  Web Scout 未启用或无搜索结果。")
        lines.append("  如启用真实 Web Scout，需显式 opt-in 并配置搜索 provider。")
    lines.append("")

    # ── 9. Market comparison ──
    lines.append("【Market Comparison（赔率对比）】")
    lines.append("  说明：赔率仅用于市场对比，不入模型、不做 blend。")
    if ri.market_comparison:
        mc = ri.market_comparison
        if isinstance(mc, dict):
            for key, val in mc.items():
                lines.append(f"  {key}: {val}")
    else:
        lines.append("  未接入赔率数据 (market comparison not available)。")
    lines.append("")

    # ── 10. Data gaps ──
    lines.append("【数据缺口 (Gap List)】")
    lines.append("  以下数据项当前缺失：")
    if ri.data_gaps:
        for gap in ri.data_gaps:
            lines.append(f"    - {gap}")
    else:
        lines.append("    （无数据缺口记录）")
    lines.append("")

    # ── 11. Caveats / 风险说明 ──
    lines.append("【Caveats / 风险说明】")
    if ri.caveats:
        for i, caveat in enumerate(ri.caveats, 1):
            lines.append(f"  {i}. {caveat}")
    else:
        lines.append("  （无额外风险说明）")
    lines.append("")

    # ── 12. Replay / provenance ──
    lines.append("【Replay / Provenance 摘要】")
    lines.append(f"  Snapshot ID: {ri.snapshot_id or 'N/A'}")
    lines.append(f"  Provider: {ri.provider_name or 'N/A'}")
    if ri.assembled_at:
        lines.append(f"  Assembled at: {ri.assembled_at}")
    lines.append(f"  Model boundary: affects_model={ri.model_boundary.get('affects_model', False)}, "
                 f"report_only={ri.model_boundary.get('report_only_or_context_only', True)}, "
                 f"enters_prediction_engine={ri.model_boundary.get('enters_prediction_engine', False)}")
    lines.append("")

    # ── Footer ──
    lines.append("=" * 60)
    lines.append("  Production-Oriented MVP — World Cup Oracle")
    lines.append("  概率仅来自本地 prediction engine")
    lines.append("  Provider context / Scout evidence / Odds 均不入模")
    lines.append("  TheSportsDB remains needs_more_info")
    lines.append("=" * 60)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_pct(value: float | None) -> str:
    """Format a probability as a percentage string."""
    if value is None:
        return "N/A"
    try:
        pct = float(value) * 100
        return f"{pct:.1f}%"
    except (TypeError, ValueError):
        return "N/A"
