#!/usr/bin/env bash

# Usage: ./run.sh
# Every run setting is read from config.yaml next to this script; edit that file to change a run.

# Fail the whole pipeline (not just tee) if python exits with an error
set -o pipefail

# run.sh lives at the repo root, so the repo root is the script's own directory
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

source ~/pyenv/bin/activate

if [ -f .env ]; then
	source .env
fi

export PYTHONPATH="$REPO_ROOT/src"

CONFIG_PATH="$REPO_ROOT/config.yaml"

mkdir -p logs
LOG="logs/log_$(date +%Y%m%d_%H%M%S).txt"

# run

python3 -m doc_ingest \
	--config_path "$CONFIG_PATH" \
	2>&1 | tee "$LOG"
