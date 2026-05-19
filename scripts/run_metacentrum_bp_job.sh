#!/bin/bash
#PBS -N eoh_bp_kimi
#PBS -l select=1:ncpus=2:mem=24gb:scratch_local=20gb
#PBS -l walltime=48:00:00
#PBS -o /storage/praha1/home/papaceka/EoH/logs/
#PBS -e /storage/praha1/home/papaceka/EoH/logs/

set -euo pipefail

PROJECT_DIR="/storage/praha1/home/papaceka/EoH"
LOG_DIR="$PROJECT_DIR/logs"
RUNNER_SCRIPT="$PROJECT_DIR/scripts/run_metacentrum_bp.sh"

cd "$PROJECT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

API_KEY_ENV="${API_KEY_ENV:-E_infra_key}"
API_KEY_ENVS="${API_KEY_ENVS:-}"
API_BASE_URL="${API_BASE_URL:-https://llm.ai.e-infra.cz/v1}"
MODEL="${MODEL:-kimi-k2.6}"
POP_SIZE="${POP_SIZE:-10}"
N_POP="${N_POP:-10}"
N_PROC="${N_PROC:-2}"
E1_PARENTS="${E1_PARENTS:-3}"
E2_PARENTS="${E2_PARENTS:-3}"
MAX_ITEMS="${MAX_ITEMS:-}"
OUTPUT_DIR="${OUTPUT_DIR:-results/metacentrum_${MODEL}_pop${POP_SIZE}_gen${N_POP}_p3}"

mkdir -p "$LOG_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
JOB_TAG="${PBS_JOBID:-manual}_${STAMP}"
RUN_LOG="$LOG_DIR/eoh_bp_${JOB_TAG}.log"

exec > >(tee -a "$RUN_LOG") 2>&1

if [[ -z "$API_KEY_ENVS" ]]; then
  AUTO_KEY_NAMES=()
  for KEY_NAME in E_infra_key_1 E_infra_key_2 E_infra_key_3; do
    if [[ -n "${!KEY_NAME:-}" ]]; then
      AUTO_KEY_NAMES+=("$KEY_NAME")
    fi
  done
  if [[ "${#AUTO_KEY_NAMES[@]}" -ge 2 ]]; then
    API_KEY_ENVS="$(IFS=,; echo "${AUTO_KEY_NAMES[*]}")"
  fi
fi

echo "=== Job started ==="
date
hostname
echo "PBS_JOBID=${PBS_JOBID:-}"
echo "Working directory: $PWD"
echo "Runner: $RUNNER_SCRIPT"
echo "API_KEY_ENV=$API_KEY_ENV"
echo "API_KEY_ENVS=$API_KEY_ENVS"
echo "API_BASE_URL=$API_BASE_URL"
echo "MODEL=$MODEL"
echo "POP_SIZE=$POP_SIZE"
echo "N_POP=$N_POP"
echo "N_PROC=$N_PROC"
echo "E1_PARENTS=$E1_PARENTS"
echo "E2_PARENTS=$E2_PARENTS"
echo "MAX_ITEMS=$MAX_ITEMS"
echo "OUTPUT_DIR=$OUTPUT_DIR"
echo "SCRATCHDIR=${SCRATCHDIR:-}"

if [[ ! -x "$RUNNER_SCRIPT" ]]; then
  echo "Missing runner script: $RUNNER_SCRIPT" >&2
  exit 1
fi

if [[ -n "$API_KEY_ENVS" ]]; then
  IFS=',' read -r -a KEY_NAMES <<< "$API_KEY_ENVS"
  HAVE_KEY=0
  for KEY_NAME in "${KEY_NAMES[@]}"; do
    KEY_NAME="${KEY_NAME// /}"
    if [[ -n "$KEY_NAME" && -n "${!KEY_NAME:-}" ]]; then
      HAVE_KEY=1
      break
    fi
  done
  if [[ "$HAVE_KEY" -ne 1 ]]; then
    echo "Missing API keys in environment variables: $API_KEY_ENVS" >&2
    exit 1
  fi
elif [[ -z "${!API_KEY_ENV:-}" ]]; then
  echo "Missing API key in environment variable ${API_KEY_ENV}." >&2
  exit 1
fi

CMD=(
  "$RUNNER_SCRIPT"
)

if [[ -n "$MAX_ITEMS" ]]; then
  CMD+=(--max-items "$MAX_ITEMS")
fi

echo "Command: ${CMD[*]} $*"

API_KEY_ENV="$API_KEY_ENV" \
API_KEY_ENVS="$API_KEY_ENVS" \
API_BASE_URL="$API_BASE_URL" \
MODEL="$MODEL" \
POP_SIZE="$POP_SIZE" \
N_POP="$N_POP" \
N_PROC="$N_PROC" \
E1_PARENTS="$E1_PARENTS" \
E2_PARENTS="$E2_PARENTS" \
OUTPUT_DIR="$OUTPUT_DIR" \
"${CMD[@]}" "$@"

echo "=== Job finished ==="
date

clean_scratch || true
