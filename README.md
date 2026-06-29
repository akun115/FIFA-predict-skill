# World Cup Oracle

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-Plugin-orange)](https://claude.ai/code)

**Human-in-the-loop FIFA World Cup match analysis via Claude Code — deterministic Dixon-Coles probabilities + sourced pre-match research + reproducible model pipeline.**

---

## Philosophy

- **Probabilities are deterministic, not vibes.** Every forecast comes from Dixon-Coles math via `predict_match`. Agents annotate with sourced context but never touch the numbers.
- **Fail closed, not open.** Missing data → gaps/caveats. Never fabrication.
- **Model pipeline is reproducible.** Ingest → backtest → train → promote, all with checksums and immutable snapshots.
- **Skills + agents + MCP, composable.** Each component does one thing. Compose them for your workflow.

## Quick start

```powershell
cd world-cup-oracle
python -m pip install -r requirements.txt
python -m pip install -r requirements-training.txt

# verify
python -m pytest tests -q
```

Loaded as a Claude Code plugin, the skills and MCP servers activate automatically.

## Components

### Skills (3 workflow orchestrators)

| Skill | Purpose |
|-------|---------|
| `world-cup-oracle:world-cup-oracle` | Predict a World Cup match — scout → form → strength → tactical → oracle; optionally run a Socratic pre-match belief-clarification route before the model call |
| `world-cup-oracle:oracle-model-lab` | Train / backtest / promote the national-team Dixon-Coles model |
| `world-cup-oracle:football-data-maintenance` | Manage providers, entities, cache, freshness, and provenance |

### Specialist Agents (6 read-only analysts)

| Agent | Role |
|-------|------|
| `world-cup-scout` | Injury, suspension, lineup, venue, weather, coach statements |
| `world-cup-form-analyst` | Recent results, rest, travel, pre-match form (no post-match leak) |
| `world-cup-strength-analyst` | Verified Elo, attack/defense ratings, availability inputs |
| `world-cup-tactical-analyst` | Expected formations, player matchups, qualitative tactical read |
| `world-cup-context-analyst` | Qualification scenarios, motivation, pressure, referee, off-field |
| `world-cup-oracle` | Synthesis — present model probabilities with qualitative caveats |

### MCP Servers (2 deterministic runtimes)

| Server | Tools |
|--------|-------|
| `world-cup-oracle` | `predict_match`, `record_prediction`, `search_prematch`, `fetch_live_odds`, `get_tournament_state`, `update_post_match`, `calibration_report`, `query_kb`, `sync_match_context`, `provider_status`, `cache_status`, `purge_cache`, `resolve_football_entity` |
| `world-cup-oracle-model-lab` | `model_status`, `backtest_model`, `train_model`, `promote_model` |

## Predict a match

Ask Claude Code — the skill orchestrates the full workflow:

```text
使用 world-cup-oracle 分析巴西 vs 日本。
比赛日期是 2026-06-29，中立场，世界杯正赛。
先联网核验最新阵容和伤停，再给出比分概率。
```

What happens:
1. Scout agent researches injuries, lineups, venue (web search)
2. Form/strength/tactical/context agents produce sourced qualitative reads
3. `predict_match` returns Dixon-Coles probabilities, xG, top-5 scores
4. Oracle agent synthesizes model output + qualitative caveats

> Ordinary prediction does not retrain the model. Qualitative research informs risk notes only — probabilities come from math.

## Socratic guided route

Use this optional route when the user wants to reason through a match before seeing the model output:

```text
使用 world-cup-oracle，用苏格拉底式追问带我分析巴西 vs 日本。
先别直接给结论；先让我给出自己的判断和信心，再联网核验证据，最后对照 predict_match 的概率。
```

What happens:
1. The assistant frames the exact question: winner, score band, upset risk, advancement, tactical matchup, or model-failure risk.
2. The user states an initial prior and confidence before seeing model probabilities.
3. The assistant asks focused follow-up questions about assumptions, evidence, counterexamples, and match implications.
4. Sourced pre-match research checks injuries, lineups, schedule context, venue/weather, and coach statements.
5. `predict_match` still provides the official numeric probabilities; the user's prior is used only for calibration and explanation.
6. The final answer includes a short judgment-calibration summary: where the user's prior matched evidence, where it diverged from the model, and which caveats matter most.

See `skills/world-cup-oracle/references/socratic-guided-route.md` for the detailed route. This route is adapted as an original sports-analysis workflow inspired by Socratic guided questioning patterns; it does not copy external protocol text and does not change the model's probability source.

## Maintain the model

Every data-changing command requires an explicit `--as-of` date.

```powershell
# Check status
python scripts/model-lab.py status --models-root .local\models

# Sync latest data & train
python scripts/model-lab.py ingest --as-of 2026-06-29 --training-root .local\training
python scripts/model-lab.py backtest --as-of 2026-06-29 --first-test-year 2010 --training-root .local\training
python scripts/model-lab.py train --as-of 2026-06-29 --version national-dc-v1.0.3 --models-root .local\models

# Promote (explicit, separate action)
python scripts/model-lab.py promote --version national-dc-v1.0.3 --models-root .local\models --confirm
```

## Data sources

| Source | Type | Notes |
|--------|------|-------|
| [martj42/international_results](https://github.com/martj42/international_results) | Training data | 23k+ national-team results, CSV |
| [football-data.org](https://www.football-data.org/) | Live fixtures/results | Free token required (`FOOTBALL_DATA_ORG_TOKEN`) |
| [OpenFootball JSON](https://github.com/openfootball/football.json) | Public datasets | Fallback provider |

## Environment variables

```text
FOOTBALL_DATA_ORG_TOKEN=      # football-data.org API token
WORLD_CUP_ORACLE_CACHE_MB=500 # Response cache size
WORLD_CUP_ORACLE_DB=          # SQLite database path
WORLD_CUP_ORACLE_MODELS=      # Model artifacts root
WORLD_CUP_ORACLE_TRAINING_DATA= # Training data root
```

When loaded as a plugin, `.mcp.json` defaults storage to plugin-local `.local/` paths.

## Safety boundaries

| Layer | Rule |
|-------|------|
| Provider / Scout | Fail-closed. Missing data → gaps/caveats, never fabricated. |
| Odds | Market comparison only. Never blended into model probabilities. |
| Injuries / News / Lineups | Report-only or context-only. No xG adjustment. |
| Tournament context | Annotative only. Never modifies `predict_match` probabilities. |
| Model (`predict_match`) | Probabilities from Dixon-Coles math only. Agents must not alter them. |
| Socratic route | Clarifies user priors and assumptions only. Never modifies model probabilities or turns intuition into model output. |
| Training pipeline | All gates must pass. Promotion requires explicit confirmation. |
| Default tests | Offline, synthetic, no env, no API key. 0 failed / 0 skipped. |

## Project structure

```text
world-cup-oracle/
├── .claude-plugin/          Plugin manifest
├── .mcp.json                MCP auto-registration
├── .local/                  Promoted artifacts & immutable training data
├── agents/                  Read-only specialist agent prompts
├── deploy/                  Deployment templates (cron, docker, systemd)
├── football_data/           Provider, cache, entity, quality, snapshot layer
├── knowledge/               Provisional fallback & audit store (YAML)
├── mcp-server/              Runtime & model-lab MCP servers
├── oracle_core/             Standalone prediction & scoring runtime
├── oracle_training/         Ingest, Elo, Dixon-Coles, backtest, registry
├── scripts/                 Standalone maintenance entrypoints
├── skills/                  Three plugin workflows (SKILL.md + references)
├── tests/                   Default offline regression tests
├── tests_live/              Opt-in live provider integration tests
├── README.md
└── LICENSE
```

## Testing

```powershell
# Default offline tests (0 failed, 0 skipped)
python -m pytest tests -q

# Live integration tests (opt-in, requires credentials)
WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS=1 \
  FOOTBALL_DATA_ORG_TOKEN=<key> \
  python -m unittest discover tests_live -v
```

Default tests are **offline**: no network, no env reads, no API keys, synthetic data only.

## Operating rules

- Probabilities come from `predict_match`; agents must not alter them manually.
- Provider context / Scout evidence / Odds do NOT enter the model.
- Odds are market comparison only — never blended.
- Injuries / lineups / news / weather are report-only — no xG adjustment.
- Missing or stale facts must be reported as gaps/caveats, not invented.
- Fitted artifacts and historical snapshots must pass checksum validation.
- Results observed after an `as_of` cutoff are excluded.
- Candidate promotion requires passing gates and explicit confirmation.
- All providers fail closed; missing data → gaps/caveats, not fabrication.
- Live operation requires external credentials, deployment, and validation.
- Socratic questioning can calibrate user reasoning but cannot override, tune, or relabel model probabilities.

## What this project does NOT claim

- Full live production is proven or deployed.
- The model can outperform betting markets.
- Real provider credentials or live payloads are configured.
- A fitted model guarantees future accuracy.

## License

MIT — see [LICENSE](LICENSE) for full text.