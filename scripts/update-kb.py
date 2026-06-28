"""赛后知识库更新 CLI 脚本。

用法:
  python scripts/update-kb.py --match-id "2026-WC-GROUP-A-01" \
    --date "2026-06-11" --stage "group" \
    --home "巴西" --away "墨西哥" \
    --score "3-0" --stats '{"xg":[2.1,0.4],"possession":[62,38],"shots":[18,6]}'
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp-server"))

from tools.update_post_match import update_post_match


def main():
    parser = argparse.ArgumentParser(description="World Cup Oracle 赛后知识库更新")
    parser.add_argument("--match-id", required=True, help="比赛唯一ID")
    parser.add_argument("--date", required=True, help="日期 YYYY-MM-DD")
    parser.add_argument("--stage", required=True, help="阶段 (group/R32/R16/QF/SF/F)")
    parser.add_argument("--home", required=True, help="主队名")
    parser.add_argument("--away", required=True, help="客队名")
    parser.add_argument("--score", required=True, help="比分 如 '3-0'")
    parser.add_argument("--ht-score", default="0-0", help="半场比分")
    parser.add_argument("--stats", default="{}", help="统计数据 JSON")
    parser.add_argument("--players", default="[]", help="球员表现 JSON 数组")
    parser.add_argument("--events", default="[]", help="关键事件 JSON 数组")
    parser.add_argument("--mvp", default="", help="最佳球员")
    parser.add_argument("--referee", default="", help="裁判")
    parser.add_argument("--weather", default="", help="天气")

    args = parser.parse_args()

    score_parts = args.score.split("-")
    ht_parts = args.ht_score.split("-")

    stats = json.loads(args.stats)
    players = json.loads(args.players)
    events = json.loads(args.events)

    result = update_post_match(
        match_id=args.match_id,
        date=args.date,
        stage=args.stage,
        home_team=args.home,
        away_team=args.away,
        score=[int(score_parts[0]), int(score_parts[1])],
        half_time=[int(ht_parts[0]), int(ht_parts[1])],
        stats=stats,
        player_performances=players,
        key_events=events,
        mvp=args.mvp,
        referee=args.referee,
        weather=args.weather,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
