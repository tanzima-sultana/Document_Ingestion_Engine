#!/usr/bin/env bash

# Usage: ./benchmarks/langchain/run_langchain.sh [input_path]

# Fail the whole pipeline (not just tee) if python exits with an error
set -o pipefail

# This script lives in benchmarks/langchain/, so the repo root is two folders up
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

source ~/pyenv/bin/activate

export PYTHONPATH="$REPO_ROOT/src"

# Same PDFs doc_ingest downloaded; run.sh deletes outputs/, so copy them elsewhere for repeat runs
INPUT_PATH="${1:-$REPO_ROOT/outputs/data_pdfa-eng-wds_6b87b8a4/raw}"

mkdir -p logs
LOG="logs/log_langchain.txt"

# run

python3 "$SCRIPT_DIR/langchain.py" \
	--input_path "$INPUT_PATH" \
	2>&1 | tee "$LOG"
