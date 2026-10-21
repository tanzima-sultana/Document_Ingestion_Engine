#!/usr/bin/env bash

# Usage: ./run.sh [download_workers] [parse_workers]   (defaults: 64 16)

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
INPUT_PATH="pixparse/pdfa-eng-wds"

# Download settings (each one is optional for the CLI; leaving a flag out uses the library default)
DOWNLOAD_WORKERS="${1:-64}"
MAX_BATCH_ROWS=256
HUGGING_FACE_SPLIT="train"

# Process settings
PARSE_WORKERS="${2:-16}"
PARSE_TIMEOUT_SECONDS=120
DEDUP_THRESHOLD=0.90

mkdir -p logs
LOG="logs/log_${SIZE}_download${DOWNLOAD_WORKERS}_parse${PARSE_WORKERS}.txt"

# run

python3 -m doc_ingest \
	--size "$SIZE" \
	--input_path "$INPUT_PATH" \
	--download_workers "$DOWNLOAD_WORKERS" \
	--max_batch_rows "$MAX_BATCH_ROWS" \
	--hugging_face_split "$HUGGING_FACE_SPLIT" \
	--parse_workers "$PARSE_WORKERS" \
	--parse_timeout_seconds "$PARSE_TIMEOUT_SECONDS" \
	--dedup_threshold "$DEDUP_THRESHOLD" \
	2>&1 | tee "$LOG"
