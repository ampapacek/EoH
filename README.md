# EoH Online Bin Packing Reproduction Wrapper

This repository is a small wrapper project around the paper _“Evolution of Heuristics: Towards Efficient Automatic Algorithm Design Using Large Language Model”_.

Paper: https://arxiv.org/abs/2401.02051

Official code: https://github.com/FeiLiu36/EoH

This repository tracks only the wrapper code and documentation. `EoH/` is a local upstream clone created on demand by `make build`, so the wrapper stays lightweight and can be set up cleanly on another server.

Online bin packing means items arrive one by one, each item must be placed into a bin immediately, and the goal is to minimize the number of bins used.

## Repository layout

- `EoH/`: local clone of the official upstream repository, created by `make build`
- `scripts/run_official_bp_smoke.py`: root wrapper for a tiny official EoH smoke run
- `scripts/evaluate_official_bp_baselines.py`: evaluate hand-written baselines with the official upstream evaluator
- `scripts/minimal_bp_repro.py`: lightweight fallback reproduction with baselines and a small evolutionary loop
- `results/`: experiment outputs
- `logs/`: place for future run logs
- `notes/`: place for short experiment notes

## Setup

Recommended local setup:

```bash
make build
```

What `make build` does:

- creates `.venv/`
- clones `https://github.com/FeiLiu36/EoH.git` into `EoH/` if it is missing
- installs the upstream package with `pip install -e EoH/eoh`
- installs `requests`, which upstream imports but does not declare in `setup.py`
- creates local `results/`, `logs/`, and `notes/` directories

If you need a different Python executable, override it:

```bash
make build PYTHON=python3.11
```

## Git tracking

This wrapper repo is intended to track only reproducible project code and docs. The following stay local and are ignored by git:

- `EoH/`
- `results/`
- `logs/`
- `.venv/`
- `.env*`

You can keep API keys in a local `.env` file. Example:

```bash
E_infra_key_1=sk-...
E_infra_key_2=sk-...
```

The wrapper loads `.env` automatically at startup.

## How the official online bin packing example is wired upstream

Relevant upstream files:

- `EoH/examples/bp_online/runEoH.py`
- `EoH/eoh/src/eoh/problems/optimization/bp_online/run.py`
- `EoH/eoh/src/eoh/problems/optimization/bp_online/prompts.py`
- `EoH/examples/bp_online/evaluation/runEval.py`

What they do:

- The official example uses problem name `bp_online`.
- The prompt asks the LLM to generate a `score(item, bins)` function.
- Fitness is the average excess number of bins over an L1 lower bound on the bundled Weibull dataset.
- Upstream writes populations to `results/pops/` and best individuals to `results/pops_best/`.
- The example evaluation script writes a plain-text file `results.txt`.

Dependencies observed in practice:

- Declared by upstream: `numpy`, `numba`, `joblib`
- Needed in practice for remote API access: `requests`

LLM/API configuration observed upstream:

- Upstream expects an OpenAI-style chat completions API.
- The built-in client hardcodes the path `/v1/chat/completions`.
- For OpenRouter, this repository uses a root wrapper script so a custom base URL can be passed cleanly.

## Run the official smoke test

With an API key in `OPENROUTER_API_KEY`:

```bash
./.venv/bin/python scripts/run_official_bp_smoke.py \
  --api-base-url https://openrouter.ai/api/v1 \
  --model openai/gpt-3.5-turbo \
  --pop-size 1 \
  --n-pop 1 \
  --n-proc 1 \
  --log-responses \
  --output-dir results/official_smoke
```

To rotate requests across multiple keys, use `--api-key-envs` with a comma-separated list of environment variable names:

```bash
./.venv/bin/python scripts/run_official_bp_smoke.py \
  --api-base-url https://llm.ai.e-infra.cz/v1 \
  --api-key-envs E_infra_key_1,E_infra_key_2 \
  --model kimi-k2.6 \
  --pop-size 4 \
  --n-pop 2 \
  --n-proc 2 \
  --output-dir results/kimi_multi_key
```

The wrapper round-robins requests across the configured keys, which is useful when one key only supports a small number of concurrent requests.

Notes:

- This wrapper keeps `EoH/` unchanged and patches the API client at runtime.
- A direct upstream run with `llm_api_endpoint="openrouter.ai"` does not work because OpenRouter needs `/api/v1/...`.
- A probe request to OpenRouter succeeded, but a tiny upstream smoke test through the original client failed until the wrapper was introduced.
- The wrapper now logs one trace file per LLM request under `results/official_smoke/llm_traces/requests/`.
- The cumulative summary is written to `results/official_smoke/llm_traces/llm_summary.json`.
- If generation or evaluation fails, stage-specific diagnostics are written to `results/official_smoke/llm_traces/diagnostics/`.
- `run_metadata.json` also includes the current LLM summary snapshot.

LLM logging fields captured by the wrapper:

- timestamp (`started_at`, `finished_at`)
- model
- request payload / prompt
- HTTP status
- response text
- response id and provider when present
- token usage when present
- reported cost when present
- error details for failed requests
- parse/evaluation diagnostics when an offspring ends up with `objective = None`

If `--log-responses` is passed, full parsed response JSON is also stored in each request trace file.

## Run the minimal fallback reproduction

```bash
./.venv/bin/python scripts/minimal_bp_repro.py \
  --seed 7 \
  --generations 4 \
  --population-size 8 \
  --output-dir results/minimal_repro
```

This minimal reproduction is intentionally small:

- fixed synthetic online bin packing instances
- classical baselines: First Fit, Best Fit, First Fit Decreasing
- manually seeded score heuristics
- simple mutation over score-function weights
- several generations of selection and mutation

## Evaluate official baselines

To compare against simple hand-written heuristics on the exact official `bp_online` evaluator:

```bash
./.venv/bin/python scripts/evaluate_official_bp_baselines.py \
  --output-dir results/official_baselines
```

This currently evaluates:

- First Fit
- Best Fit
- Worst Fit
- an exact-fit-biased Best-Fit variant

## Results obtained

Current saved result:

- `results/minimal_repro/summary.csv`
- `results/minimal_repro/summary.json`
- `results/minimal_repro/experiment_note.md`

Short table from the current minimal reproduction:

| Method | Avg bins | Avg LB | Avg excess |
| --- | ---: | ---: | ---: |
| First Fit | 42.875 | 38.750 | 0.1059 |
| Best Fit | 42.250 | 38.750 | 0.0899 |
| First Fit Decreasing | 39.875 | 38.750 | 0.0285 |
| Evolved heuristic | 42.250 | 38.750 | 0.0899 |

Interpretation:

- The lightweight evolutionary reproduction reaches Best-Fit-level performance on the saved test set.
- On this small synthetic dataset, offline First Fit Decreasing remains strongest, which is expected because it gets to sort items first and is not strictly online.

Official baseline snapshot from `results/official_baselines/summary.csv`:

| Method | Objective |
| --- | ---: |
| best_fit | 0.03984 |
| exact_fit_bonus | 0.03984 |
| first_fit | 0.04226 |
| worst_fit | 1.51534 |

On the official objective, lower is better. The saved successful official EoH run at `results/official_smoke/` reached `0.03501`, which is better than the evaluated Best Fit baseline.

## Reproduction status

Status: partially works

Successfully run:

- cloned the official `EoH` repository into `EoH/`
- installed the official package in a clean Python 3.11 environment
- identified the official online bin packing implementation, prompt path, evaluator, and output files
- confirmed and documented an upstream dependency gap: missing `requests`
- confirmed OpenRouter connectivity with a direct API probe
- reached generation-0 output in an official wrapper-based smoke run at `results/official_smoke/results/pops/population_generation_0.json`
- created and ran a small local reproduction with saved results in `results/minimal_repro`

Still unresolved / not yet completed:

- a fully successful end-to-end official EoH smoke run has not been confirmed yet in this wrapper repo
- the upstream API client is brittle and requires the root wrapper for OpenRouter-style base URLs
- paper-scale reproduction was intentionally not attempted yet

## Suggested next step

First rerun the official smoke script above. If that still behaves unreliably, use the minimal reproduction outputs for the presentation and treat the official run as a documented partial reproduction with known API-client friction.

## Extension Ideas

Possible follow-up extensions for this repository:

- Add lineage-aware mutation prompts. The current official EoH prompts show the current parent algorithm and code, but not how that parent evolved over time. A useful extension would be to include recent parent history in mutation prompts, such as previous objective values, the immediate predecessor heuristic, and whether recent changes helped or hurt.
- Add fitness-aware prompts. The current upstream prompts do not explicitly show objective values to the LLM. Another extension would be to include parent scores or rank so the model can see which candidate heuristics performed better.
- Add a classical parameter-only evolutionary baseline. Many generated heuristics are effectively score formulas with a few weights, thresholds, penalties, or bonuses. A simpler non-LLM baseline would be to fix a score-function template and run a standard evolutionary search over only its numeric parameters.
- Compare LLM evolution against direct numeric optimization. For example, use random search, hill climbing, CMA-ES, or a small genetic algorithm on hand-designed heuristic parameters, then compare those results with EoH’s LLM-generated heuristics on the same truncated datasets.
- Track heuristic families explicitly. Another useful extension would be to classify generated heuristics into patterns such as Best-Fit-like, slack-balancing, exact-fit-biased, or diversity-penalized, then analyze which families survive most often.
