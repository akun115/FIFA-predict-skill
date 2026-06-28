"""Compatibility entry point for validated post-match updates."""

from pathlib import Path
import sys

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from oracle_core.storage import KnowledgeStore


def update_post_match(
    match_id: str,
    date: str,
    stage: str,
    home_team: str,
    away_team: str,
    score: list[int],
    half_time: list[int] | None = None,
    stats: dict | None = None,
    player_performances: list[dict] | None = None,
    key_events: list[dict] | None = None,
    mvp: str = "",
    referee: str = "",
    weather: str = "",
    *,
    knowledge_root: str | Path | None = None,
    neutral_site: bool = True,
) -> dict:
    root = Path(knowledge_root) if knowledge_root is not None else PLUGIN_ROOT / "knowledge"
    merged_stats = dict(stats or {})
    if half_time is not None:
        merged_stats["half_time"] = half_time
    if player_performances:
        merged_stats["player_performances"] = player_performances
    if key_events:
        merged_stats["key_events"] = key_events
    if mvp:
        merged_stats["mvp"] = mvp
    if referee:
        merged_stats["referee"] = referee
    if weather:
        merged_stats["weather"] = weather
    return KnowledgeStore(root).record_result(
        match_id,
        date,
        stage,
        home_team,
        away_team,
        score,
        neutral_site=neutral_site,
        home_team=None if neutral_site else home_team,
        stats=merged_stats,
    )
