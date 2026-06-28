# World Cup Oracle

World Cup Oracle is a Claude Code plugin for human-in-the-loop football match
analysis. It combines skills, specialist agents, MCP tools, a lightweight
Python prediction runtime, and an isolated model-maintenance pipeline.

It is intended for analysis and teaching. It is not betting advice, and a
fitted model does not guarantee future accuracy.

## Release status

**Repository-side production launch closure is complete.** All production
mechanisms (provider, scout, odds, scheduler, monitoring, storage, deployment,
readiness) are implemented in a fail-closed state — every component is
disabled by default, requires explicit opt-in, and never fabricates data.

This is **not** full live production proven. Live operation requires external
credentials, external deployment, and explicit validation outside this
repository.

## What this repository claims

- A deterministic Dixon-Coles score-probability engine with a fitted national-team model.
- Model E2E pipeline: ingest → backtest → train → promote, all with checksums and immutable snapshots.
- Plugin skills, specialist agents, and MCP tools for match analysis workflows.
- Provider, scout, odds, scheduler, monitoring, storage, and readiness mechanisms — all fail-closed.
- A repository-side readiness gate that verifies internal invariants.
- Default tests that pass offline with synthetic data, no env vars, and no API keys.

## What this repository does NOT claim

- Full live production is proven or deployed.
- World Cup 2026 coverage is verified by the repository.
- TheSportsDB is approved for live adapter use.
- Real provider credentials or live payloads are configured.
- The model can outperform betting markets.

## Included components

- `world-cup-oracle`: match-prediction workflow.
- `football-data-maintenance`: provider, cache, entity, freshness, and provenance.
- `oracle-model-lab`: historical ingest, walk-forward backtesting, candidate training, and explicit promotion.
- Six read-only analysis agents: scout, form, strength, tactical, context, oracle.
- MCP server `world-cup-oracle`: prediction, data maintenance, knowledge lookup, recording, settlement, calibration.
- MCP server `world-cup-oracle-model-lab`: model status, backtesting, training, promotion.
- Standalone runtime in `oracle_core/`; isolated training dependencies in `oracle_training/`.
- Promoted national-team model `national-dc-v1.0.1`.

## How to run default tests

```powershell
python -m pytest tests -q
# Expected: 0 failed, 0 skipped
```

Default tests are **offline**: no network, no env reads, no API keys, synthetic
data only. They protect model math, cutoff integrity, MCP behavior, artifact
promotion, provider contracts, and documentation invariants.

## Safety boundaries

| Layer | Rule |
|---|---|
| Provider / Scout | Fail-closed. Missing data → gaps/caveats, never fabricated content. |
| Odds | Market comparison only. Never blended into model probabilities. |
| Injuries / News / Weather / Lineups | Report-only or context-only. No xG adjustment. |
| Context (tournament) | Annotative only. Never modifies `predict_match` probabilities. |
| Report builder / Renderer | No fabricated probabilities. |
| Model (`predict_match`) | Probabilities come from Dixon-Coles math only. Agents must not alter them. |
| Readiness gate | Repository-side only. Does not certify external live readiness. |
| Default tests | Offline, synthetic, no env, no API key. 0 failed / 0 skipped. |

## Model formula (`provisional-v1` coefficients)

The Dixon-Coles engine uses transparent initial coefficients for strength terms.
These are NOT trained values — they are `provisional-v1` defaults applied
symmetrically to both teams. Home advantage only activates when the caller
explicitly designates a real home team.

```text
elo_term    = 0.20 * (elo_a     - elo_b)      / 400
attack_term = 0.16 * (attack_rating  - 70)    / 10
defense_term = 0.14 * (defense_rating - 70)   / 10
```

Player, coach, and chemistry information is used only for qualitative analysis
and data-quality notes until stable definitions and out-of-sample evidence exist.

## TheSportsDB status

TheSportsDB remains **`needs_more_info`** — NOT approved for live adapter use.
See `oracle_core.production_health.run_full_healthcheck()` for programmatic status checks.

## Live tests (`tests_live/`)

`tests_live/` contains opt-in live integration tests. They are **NOT** part of
the default test suite and require explicit opt-in:

```bash
WORLD_CUP_ORACLE_LIVE_PROVIDER_TESTS=1 \
FOOTBALL_DATA_ORG_API_KEY=<key> \
python -m unittest discover tests_live -v
```

Live tests make real HTTP calls. Missing credentials → fail closed (never skip).
Provider data does NOT modify model probabilities.

## Install

```powershell
cd world-cup-oracle
python -m pip install -r requirements.txt
python -m pip install -r requirements-training.txt
claude --plugin-dir .
```

## Data sources

Default or optional free sources:

- [International football results](https://github.com/martj42/international_results) for national-team model snapshots.
- [OpenFootball JSON](https://github.com/openfootball/football.json) for public fixture/result datasets.
- [football-data.org](https://www.football-data.org/) as an optional token-based provider (set `FOOTBALL_DATA_ORG_TOKEN`).

Paid/commercial providers (Stats Perform, Sportradar, etc.) are paid reserved only —
no live adapters are configured and no credentials are present in this repository.
Never commit credentials.

## Predict a match

Ask Claude Code:

```text
使用 world-cup-oracle 分析巴西 vs 阿根廷。比赛日期是 2026-07-10，中立场，世界杯正赛。先联网核验最新阵容和伤停，再给出比分概率。
```

Ordinary prediction does not retrain the model. Current team news is researched
for sourced qualitative analysis and risk notes only.

## Maintain the model

Every data-changing command requires an explicit, timezone-independent `--as-of` date.

```powershell
python scripts/model-lab.py status --version national-dc-v1.0.1 --models-root .local\models
python scripts/model-lab.py ingest --as-of 2026-06-23 --training-root .local\training
python scripts/model-lab.py backtest --as-of 2026-06-23 --first-test-year 2010 --training-root .local\training
python scripts/model-lab.py train --as-of 2026-06-23 --version national-dc-v1.0.2 --training-root .local\training --models-root .local\models
```

Promotion is a separate explicit action:

```powershell
python scripts/model-lab.py promote --version national-dc-v1.0.2 --models-root .local\models --confirm
```

## Real Match CLI (offline by default)

```bash
python -m oracle_core.real_match_cli --home "Team A" --away "Team B"
python -m oracle_core.real_match_cli --home "Team A" --away "Team B" \
  --model-output-json model_output.json --output report.txt
```

**Synthetic E2E (FIC-* fictional data only):**

```bash
python -m oracle_core.mvp_end_to_end_command
```

## Environment variables

```text
FOOTBALL_DATA_ORG_TOKEN=
WORLD_CUP_ORACLE_CACHE_MB=500
WORLD_CUP_ORACLE_DB=
WORLD_CUP_ORACLE_MODELS=
WORLD_CUP_ORACLE_TRAINING_DATA=
```

When loaded as a plugin, `.mcp.json` defaults storage to plugin-local `.local/` paths.

## Project structure

```text
world-cup-oracle/
├─ .claude-plugin/          Claude Code plugin manifest
├─ .mcp.json                MCP auto-registration
├─ .local/                  Promoted artifacts and immutable training data
├─ agents/                  Read-only specialist agent instructions (prompt templates)
├─ deploy/                  Deployment templates (cron, docker, systemd, env)
├─ football_data/           Provider, cache, entity, quality, and snapshot layer
├─ knowledge/               Small provisional fallback and audit store (YAML)
├─ mcp-server/              Runtime and model-lab MCP servers
├─ oracle_core/             Standalone prediction and scoring runtime
├─ oracle_training/         Ingest, Elo, Dixon-Coles, backtest, and registry
├─ scripts/                 Standalone maintenance entrypoints
├─ skills/                  Three plugin workflows
├─ tests/                   Default offline regression and release-contract tests
└─ tests_live/              Opt-in live provider integration tests
```

Provider dossiers, readiness reports, integration plans, and fallback policies are
NOT separate documents — all release-facing information lives in this README.
Salient invariants are enforced by code in `oracle_core/` and verified by tests.

## Operating rules summary

- Probabilities come from `predict_match`; agents must not alter them manually.
- Provider context / Scout evidence / Odds do NOT enter the model.
- Odds are market comparison only — never blended.
- Injuries / lineups / news / weather are report-only — no xG adjustment.
- Missing or stale facts must be reported as gaps/caveats, not invented.
- Fitted artifacts and historical snapshots must pass checksum validation.
- Results observed after an `as_of` cutoff are excluded.
- Candidate promotion requires passing gates and explicit confirmation.
- Default mode is offline — no network, no env reads, no live data.
- All providers fail closed; missing data → gaps/caveats, not fabrication.
- Default fixtures use synthetic/FIC-* fictional data only — no real teams or real match payloads.
- Live operation requires external credentials, external deployment, and explicit validation.
