"""MCP Tool: search_prematch — 赛前情报联网搜索。"""


def build_search_queries(team_a: str, team_b: str, match_date: str) -> dict:
    """生成赛前搜索关键词列表。"""
    return {
        "task_type": "parallel_web_search",
        "queries": [
            {
                "id": "injuries_a",
                "query": f'"{team_a}" 伤病 停赛 最新消息 2026',
                "purpose": f"获取 {team_a} 伤病和停赛信息",
            },
            {
                "id": "injuries_b",
                "query": f'"{team_b}" 伤病 停赛 最新消息 2026',
                "purpose": f"获取 {team_b} 伤病和停赛信息",
            },
            {
                "id": "lineup_a",
                "query": f'"{team_a}" 首发阵容 预测 {team_b}',
                "purpose": f"获取 {team_a} 预计首发",
            },
            {
                "id": "lineup_b",
                "query": f'"{team_b}" 首发阵容 预测 {team_a}',
                "purpose": f"获取 {team_b} 预计首发",
            },
            {
                "id": "coach_a",
                "query": f'"{team_a}" 教练 赛前采访 战术',
                "purpose": f"获取 {team_a} 教练赛前言论",
            },
            {
                "id": "coach_b",
                "query": f'"{team_b}" 教练 赛前采访 战术',
                "purpose": f"获取 {team_b} 教练赛前言论",
            },
            {
                "id": "h2h",
                "query": f'"{team_a}" "{team_b}" 历史交锋 战绩',
                "purpose": "获取双方历史交锋记录",
            },
            {
                "id": "weather",
                "query": f'"{team_a}" vs "{team_b}" 比赛场地 天气 {match_date}',
                "purpose": "获取比赛天气和场地信息",
            },
            {
                "id": "news",
                "query": f'"{team_a}" "{team_b}" 赛前新闻 2026世界杯',
                "purpose": "获取综合赛前新闻",
            },
        ],
        "data_freshness_note": f"搜索于赛前，目标比赛日期: {match_date}。",
    }
