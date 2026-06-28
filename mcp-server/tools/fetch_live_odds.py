"""MCP Tool: fetch_live_odds — 实时赔率抓取。"""


def build_odds_queries(team_a: str, team_b: str) -> dict:
    """生成赔率搜索任务。"""
    return {
        "task_type": "web_search_odds",
        "queries": [
            {
                "id": "1x2",
                "query": f'"{team_a}" vs "{team_b}" odds 1x2 betting 2026 World Cup',
                "purpose": "获取胜平负赔率",
            },
        ],
        "processing_instructions": """
从搜索结果中提取 1x2 赔率（多家博彩公司均值）。
计算去水隐含概率：
  total = 1/home_odds + 1/draw_odds + 1/away_odds
  隐含概率:
    P_home = (1/home_odds) / total
    P_draw = (1/draw_odds) / total
    P_away = (1/away_odds) / total
""",
    }
