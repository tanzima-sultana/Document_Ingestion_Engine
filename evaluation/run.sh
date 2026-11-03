#!/usr/bin/env bash

# Usage: ./evaluation/run.sh
# Scores both engines' saved output with the settings in evaluation/config.yaml:
# evaluation.py for each engine, dedup quality for doc_ingest (if enabled), then the side-by-side report.

# Stop at the first failed step, and fail the whole pipeline (not just tee) if python exits with an error
set -eo pipefail

# This script lives in evaluation/, so the repo root is one folder up
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

source ~/pyenv/bin/activate

export PYTHONPATH="$REPO_ROOT/src"

CONFIG_PATH="$REPO_ROOT/evaluation/config.yaml"

mkdir -p logs
LOG="logs/evaluation_log.txt"

# Prints one value of the config file; a nested key is written with dots, e.g. dedup.output_path
read_config_value() {
	python3 - "$CONFIG_PATH" "$1" <<'EOF'
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as config_file:
	config_values = yaml.safe_load(config_file)

value = config_values
for key in sys.argv[2].split("."):
	value = value[key]
print(value)
EOF
}

run_evaluation() {
	# The engines save their output to logs/<dataset>_<size>/
	LOGS_PATH="logs/$(read_config_value dataset)_$(read_config_value size)"
	REFERENCE_PATH="$(read_config_value reference_path)"
	DEDUP_ENABLED="$(read_config_value dedup.enabled)"

	for ENGINE_NAME in doc_ingest langchain; do
		echo "== Evaluating $ENGINE_NAME"
		python3 evaluation/evaluation.py \
			--documents_path "$LOGS_PATH/$ENGINE_NAME/documents.jsonl" \
			--reference_path "$REFERENCE_PATH"
	done

	if [ "$DEDUP_ENABLED" != "True" ]; then
		echo "== Dedup quality skipped (dedup.enabled is not true)"
		python3 evaluation/report.py --dataset_path "$LOGS_PATH"
		return
	fi

	DEDUP_OUTPUT_PATH="$(read_config_value dedup.output_path)"
	DEDUP_MANIFEST_PATH="$(read_config_value dedup.manifest_path)"

	if [ -d "$DEDUP_OUTPUT_PATH" ]; then
		echo "== Dedup test folder $DEDUP_OUTPUT_PATH already exists; using it as it is"
	else
		echo "== Building dedup test folder"
		python3 evaluation/dedup_quality.py build \
			--reference_path "$REFERENCE_PATH" \
			--output_path "$DEDUP_OUTPUT_PATH" \
			--manifest_path "$DEDUP_MANIFEST_PATH" \
			--exact_copies "$(read_config_value dedup.exact_copies)" \
			--near_copies "$(read_config_value dedup.near_copies)" \
			--seed "$(read_config_value dedup.seed)"
	fi

	# Every file in the test folder is asked for, so none is left out by size
	DEDUP_FILE_COUNT="$(find "$DEDUP_OUTPUT_PATH" -type f | wc -l)"

	echo "== Running doc_ingest on the dedup test folder"
	python3 -m doc_ingest \
		--config_path "$REPO_ROOT/config.yaml" \
		--path "$DEDUP_OUTPUT_PATH" \
		--size "$DEDUP_FILE_COUNT"

	# doc_ingest saves to logs/<test folder name>_<size>/doc_ingest/
	DEDUP_LOGS_PATH="logs/$(basename "$DEDUP_OUTPUT_PATH")_$DEDUP_FILE_COUNT"

	echo "== Scoring dedup quality"
	python3 evaluation/dedup_quality.py score \
		--documents_path "$DEDUP_LOGS_PATH/doc_ingest/documents.jsonl" \
		--manifest_path "$DEDUP_MANIFEST_PATH"

	echo "== Report"
	python3 evaluation/report.py \
		--dataset_path "$LOGS_PATH" \
		--dedup_path "$DEDUP_LOGS_PATH/doc_ingest/dedup_quality.json"
}

# run

run_evaluation 2>&1 | tee "$LOG"
