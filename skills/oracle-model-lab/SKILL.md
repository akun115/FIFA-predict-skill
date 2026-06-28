---
name: oracle-model-lab
description: Use when ingesting historical national-team data, training or backtesting the Dixon-Coles model, inspecting model status, or explicitly promoting a validated candidate.
metadata:
  version: "1.0.0"
---

# Oracle Model Lab

1. Call `model_status` before changing model state.
2. Every ingestion, training, or backtest request requires an explicit timezone-independent `as_of` date.
3. Call `backtest_model` before `train_model`; report every failed gate.
4. Call `promote_model` only with explicit user confirmation and only after all gates pass.
5. Report candidate version, cutoff, source hash, fold count, proper scores, convergence, and promotion status.

## Guardrails

- 不得在普通预测中触发训练。
- 不得自动发布、降低门槛或隐藏失败折。
- Never train on future, scoreless, conflicting, or post-cutoff rows.
- Never claim that Claude itself was trained; only the Python statistical artifact is fitted.
- A candidate is not production until `current.json` points to it and all checksums validate.

