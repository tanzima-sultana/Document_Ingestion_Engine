#!/usr/bin/env bash

# Usage: ./benchmarks/pdf/run.sh
# Runs plain LangChain PDF loading with the settings in benchmarks/pdf/config.yaml.

# Fail the whole pipeline (not just tee) if python exits with an error
set -o pipefail

# This script lives in benchmarks/pdf/, so the repo root is two folders up
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

source ~/pyenv/bin/activate

export PYTHONPATH="$REPO_ROOT/src"

CONFIG_PATH="$REPO_ROOT/benchmarks/pdf/config.yaml"

mkdir -p logs
LOG="logs/langchain_log_$(date +%Y%m%d_%H%M%S).txt"

# run

python3 benchmarks/pdf/langchain.py \
	--config_path "$CONFIG_PATH" \
	2>&1 | tee "$LOG"
