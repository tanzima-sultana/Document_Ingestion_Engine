#!/usr/bin/env bash

# Usage: ./benchmarks/pdf/run.sh
# Every setting is read from config.yaml next to this script; edit that file to change a run.
# Downloads the benchmark PDFs once, then runs LangChain and doc_ingest on the same local folder.

# Fail the whole pipeline (not just tee) if python exits with an error
set -o pipefail

# This script lives in benchmarks/pdf/, so the repo root is two folders up
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

source ~/pyenv/bin/activate

if [ -f .env ]; then
	source .env
fi

export PYTHONPATH="$REPO_ROOT/src"

CONFIG_PATH="$SCRIPT_DIR/config.yaml"

mkdir -p logs
RUN_TIME="$(date +%Y%m%d_%H%M%S)"

# 1. Download the benchmark PDFs (skipped if already downloaded)
python3 "$SCRIPT_DIR/download.py" --config_path "$CONFIG_PATH" || exit 1

# 2. LangChain
python3 "$SCRIPT_DIR/langchain.py" --config_path "$CONFIG_PATH" \
	2>&1 | tee "logs/benchmark_pdf_langchain_${RUN_TIME}.txt" || exit 1

# 3. doc_ingest
python3 -m doc_ingest --config_path "$CONFIG_PATH" \
	2>&1 | tee "logs/benchmark_pdf_doc_ingest_${RUN_TIME}.txt" || exit 1
