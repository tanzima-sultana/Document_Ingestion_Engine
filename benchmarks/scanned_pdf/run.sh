#!/usr/bin/env bash

# Usage: ./benchmarks/scanned_pdf/run.sh
# Runs plain LangChain scanned PDF loading (with RapidOCR) with the settings in benchmarks/scanned_pdf/config.yaml.

# Fail the whole pipeline (not just tee) if python exits with an error
set -o pipefail

# This script lives in benchmarks/scanned_pdf/, so the repo root is two folders up
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

source ~/pyenv/bin/activate

export PYTHONPATH="$REPO_ROOT/src"

CONFIG_PATH="$REPO_ROOT/benchmarks/scanned_pdf/config.yaml"

mkdir -p logs
LOG="logs/langchain_scanned_pdf_log.txt"

# run

python3 benchmarks/scanned_pdf/langchain.py \
	--config_path "$CONFIG_PATH" \
	2>&1 | tee "$LOG"
