#!/usr/bin/env bash

# Fail the whole pipeline (not just tee) if python exits with an error
set -o pipefail

# run.sh lives at the repo root, so the repo root is the script's own directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source ~/pyenv/bin/activate

if [ -f .env ]; then
	source .env
fi

export PYTHONPATH="$(pwd)/src"

SIZE=5000
INPUT_PATH="https://huggingface.co/datasets/superdoc-dev/docx-corpus"
OUTPUT_PATH="outputs/"

mkdir -p logs
LOG="logs/log_${SIZE}.txt"

# run

python3 src/doc_ingest/__init__.py \
	--size "$SIZE" \
	--input_path "$INPUT_PATH" \
	--output_path "$OUTPUT_PATH" \
	2>&1 | tee "$LOG"
