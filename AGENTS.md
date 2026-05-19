# AGENTS.md

This repository is a wrapper project for reproducing or partially reproducing the EoH online bin packing experiment from:

- Paper: https://arxiv.org/abs/2401.02051
- Official code: https://github.com/FeiLiu36/EoH

## Ground rules

- `EoH/` is cloned upstream code. Treat it as upstream-owned.
- Upstream code may be modified if necessary, but we do not plan to push those changes upstream from this wrapper repo.
- Prefer adding wrapper scripts, configs, and documentation in the repository root instead of editing files under `EoH/`.
- If any upstream file in `EoH/` is changed, document the exact file and reason in `README.md` and in the relevant experiment note.

## Reproducibility requirements

- Every experiment must have a clear rerun command.
- All generated outputs must go into `results/` or `logs/`.
- After each experiment, add a short note with:
  - command
  - date
  - model used
  - key parameters
  - result summary
- Keep experiment scripts deterministic when possible by exposing `--seed`.

## API and secrets

- Never commit API keys.
- Read API keys from environment variables or a local `.env` file that is not committed.
- For OpenRouter-based runs, prefer `OPENROUTER_API_KEY`.
- If a script supports custom endpoints, make them configurable by argument rather than hardcoding.

## Preferred workflow for future agents

- Inspect upstream behavior before changing anything.
- If a need is specific to this wrapper repo, implement it in `scripts/` first.
- Keep README instructions synced with what actually works in this repository now, not with idealized future behavior.
- If upstream packaging or runtime issues are discovered, document them explicitly.

## Current known repo-specific notes

- The upstream `eoh` package declares `numpy`, `numba`, and `joblib`, but remote API usage also needs `requests`.
- The upstream remote client hardcodes `/v1/chat/completions`, which is inconvenient for OpenRouter. Prefer the root wrapper script to adapt this rather than editing upstream immediately.
- The official wrapper script logs per-request LLM traces under `results/<run>/llm_traces/requests/` and keeps an aggregate `llm_summary.json`.
- The target experiment for this repo is online bin packing.

## Current experiment targets

- Primary target: official EoH online bin packing smoke run
- Fallback target: minimal local reproduction with baselines and a small evolutionary loop
- Baselines to preserve when possible:
  - First Fit
  - Best Fit
  - First Fit Decreasing
