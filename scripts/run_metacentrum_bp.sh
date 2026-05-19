#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_BASE_URL="${API_BASE_URL:-https://llm.ai.e-infra.cz/v1}"
API_KEY_ENV="${API_KEY_ENV:-E_infra_key}"
MODEL="${MODEL:-kimi-k2.6}"
POP_SIZE="${POP_SIZE:-4}"
N_POP="${N_POP:-2}"
N_PROC="${N_PROC:-4}"
E1_PARENTS="${E1_PARENTS:-2}"
E2_PARENTS="${E2_PARENTS:-2}"
MAX_ITEMS="${MAX_ITEMS:-}"
OUTPUT_DIR="${OUTPUT_DIR:-results/metacentrum_${MODEL}_pop${POP_SIZE}_gen${N_POP}}"
EXTRA_ARGS=("$@")

if [[ ! -x ./.venv/bin/python ]]; then
  echo "Missing .venv. Run 'make build' first." >&2
  exit 1
fi

if [[ -z "${!API_KEY_ENV:-}" ]]; then
  echo "Missing API key in environment variable ${API_KEY_ENV}." >&2
  exit 1
fi

CMD=(
  ./.venv/bin/python
  scripts/run_official_bp_smoke.py
  --api-base-url "$API_BASE_URL"
  --api-key-env "$API_KEY_ENV"
  --model "$MODEL"
  --pop-size "$POP_SIZE"
  --n-pop "$N_POP"
  --n-proc "$N_PROC"
  --e1-parents "$E1_PARENTS"
  --e2-parents "$E2_PARENTS"
  --log-responses
  --output-dir "$OUTPUT_DIR"
)

if [[ -n "$MAX_ITEMS" ]]; then
  CMD+=(--max-items "$MAX_ITEMS")
fi

CMD+=("${EXTRA_ARGS[@]}")

echo "Running in $ROOT_DIR"
echo "Model: $MODEL"
echo "API base: $API_BASE_URL"
echo "Output dir: $OUTPUT_DIR"
echo "pop_size=$POP_SIZE n_pop=$N_POP n_proc=$N_PROC e1_parents=$E1_PARENTS e2_parents=$E2_PARENTS"

exec "${CMD[@]}"
