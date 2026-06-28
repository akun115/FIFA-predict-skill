---
name: football-data-maintenance
description: Use when configuring football data providers, checking API credentials, inspecting cache size, diagnosing freshness or coverage, resolving football entities, or synchronizing supported competition data.
metadata:
  version: "1.0.1"
---

# Football Data Maintenance

Use this workflow for provider setup and data diagnostics. It manages data quality; it does not change prediction coefficients or model promotion state.

1. Call `provider_status` before requesting remote data.
2. Identify the required capability and whether an enabled provider supports it.
3. Call `sync_match_context` only with an explicit competition, season, and timezone-aware `as_of` cutoff.
4. Report the returned state exactly: `fresh`, `cached`, `stale`, `partial`, or `blocked`.
5. Use `resolve_football_entity` for existing mappings. Resolve ambiguous results explicitly; never merge automatically.
6. Call `cache_status` before proposing `purge_cache`. Purging affects only evictable API responses, not snapshots or entity mappings.
7. Use `get_data_quality` and `get_prediction_snapshot` for provenance audits.

## Guardrails

- 不得编造数据、来源、球员、教练、伤停、阵容、赔率或覆盖范围。
- Never print, echo, persist, or place API credentials in tool arguments.
- A disabled provider means its capability is unavailable, not that the value is zero.
- `stale` data must include its retrieval time and must never be presented as live.
- `partial` and `blocked` results must list missing fields or blocking reasons.
- Results observed after the requested `as_of` cutoff are excluded and reported as blocked.
- Data maintenance never changes whether the prediction runtime is `fitted`, `provisional`, or `unseen_team_prior`.
