---
name: world-cup-oracle
description: Use when predicting or analyzing a FIFA World Cup match, including score probabilities, injuries, lineups, form, tactics, Socratic pre-match belief clarification, or post-match calibration.
metadata:
  version: "2.3.0"
  status: "fitted-or-provisional"
---

# World Cup Oracle

这是“统计模型 + 有来源的赛前研究 + 人机共同分析”工作流。数值概率必须来自 MCP `predict_match`；不要手改概率，不要把定性判断伪装成模型输出。

## 预测流程

1. 确认球队、比赛日期、赛事阶段、`category`、是否中立场，以及是否有主队。世界杯正赛使用 `world_cup`，世界杯预选赛使用 `world_cup_qualifier`。
   - **World Cup group-stage and knockout matches default to `neutral_site=true`** unless an explicit host/home team is designated and home-advantage modeling is intended.
   - If `neutral_site=false`, you must specify `home_team` as one of the two participants.
2. 用 `search_prematch` 生成检索计划，再联网核验伤停、阵容、场地、天气、教练声明和赛程背景。搜索计划不是证据，必须引用实际来源。
2a. **推荐：** 调用 `get_tournament_state(match_id, state_mode="pre_match")` 获取赛前小组形势和出线压力。将返回的 JSON 作为 `tournament_context_json` 传入 `predict_match`。这不会修改概率，但会在输出中标注 tournament context 和 neutral limitations。
3. 调用 `predict_match`，原样保留 `model_status`、`model_version`、`data_quality`、预期进球、胜平负概率和 Top 5 比分。
4. 明确区分模型状态：
   - `fitted`：已加载经过校验的 `current.json` 和晋升模型工件；说明训练数据截止日和样本外回测限制。
   - `provisional`：没有可用晋升工件，使用旧统计先验；展示 `defaults_used` 和缺失数据。
   - `unseen_team_prior`：至少一队不在拟合工件中，必须说明使用群体先验，可信度较低。
5. Scout、Form、Tactical、Psychology 等 agent 只能解释模型可能失效的条件，不能偷偷修改 `predict_match` 的概率。

## 可选使用路线：苏格拉底式赛前追问

当用户想“先聊判断逻辑”“帮我想清楚怎么看这场”“不要直接给结论”或明确要求苏格拉底式追问时，先走 `references/socratic-guided-route.md`，再回到标准预测流程。

这条路线的目标是让用户先形成可检验的赛前判断，再用来源证据和 `predict_match` 输出校准；它不替代模型，也不得把用户直觉写入概率。

最小流程：

1. **澄清判断对象**：追问用户真正想判断什么，例如胜平负、比分区间、爆冷风险、某队晋级概率、战术 matchup，或“模型可能错在哪里”。
2. **收集用户承诺**：在展示模型概率前，请用户给出自己的初始判断与信心等级，并标记为 `[USER_PRIOR: ...]`。
3. **追问依据与假设**：围绕阵容、状态、风格、赛程、心理压力和样本偏差提出 1-2 个聚焦问题；每轮只问少量问题，避免直接替用户下结论。
4. **证据校准**：联网核验后，用来源证据区分“事实”“传闻/不确定”“用户假设”；如发现反例，用提问方式引导用户修正判断。
5. **模型对照**：调用 `predict_match` 后，比较 `[USER_PRIOR]` 与模型输出，说明一致点、分歧点、关键 caveat；概率仍以 `predict_match` 为准。
6. **收束输出**：在正式预测中加入“用户判断校准摘要”，但不要暴露内部追问标签，除非用户要求保留推理过程记录。

## 输出要求

- 最可能比分与 Top 5 比分。
- 胜平负概率和双方预期进球。
- `model_status`、`model_version`、`data_quality`、训练截止日或 provisional 默认值。
- 数据来源、缺失项、关键假设和失效条件。
- 定性赛前情境；不得把传闻写成事实。
- 若启用苏格拉底式赛前追问：给出用户初始判断、证据校准后的变化、以及模型分歧点；不要把用户判断混入模型概率。

## MCP 工具

| Tool | 行为 |
|---|---|
| `predict_match` | 优先加载已晋升 fitted 工件；无 `current.json` 时回退 provisional |
| `record_prediction` | 开赛前保存预测和输入快照 |
| `query_kb` | 查询分层知识库，主要用于 provisional 回退和解释 |
| `update_post_match` | 幂等记录赛果并结算已有预测 |
| `calibration_report` | 报告 Brier、RPS、log-loss 和校准分箱，不自动调权 |
| `search_prematch` | 生成联网搜索计划，不执行搜索 |
| `fetch_live_odds` | 生成赔率搜索计划，不抓取赔率 |

## 护栏

1. 禁止编造伤病、阵容、球员评分、引语、赔率和来源。
2. 不提供下注金额或操作建议，不声称能击败市场。
3. `fitted` 只表示工件完整且通过当前回测门槛，不等于未来比赛保证准确。
4. 不根据赛后信息回填赛前输入；正式预测应在开赛前调用 `record_prediction`。
5. 普通预测不得触发训练、回测或晋升；模型维护使用 `oracle-model-lab`。
6. 苏格拉底式追问只能澄清用户判断、暴露假设和校准证据；不得绕过 `predict_match`、不得诱导投注、不得为了制造分歧而夸大不确定信息。