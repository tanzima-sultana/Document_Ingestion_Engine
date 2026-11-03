"""
evaluation/report.py

Puts the saved scores of doc_ingest and LangChain for one dataset side by side in one table.
Usage: python evaluation/report.py --dataset_path logs/DATASET [--dedup_path FILE]
Numbers only: the table holds the saved values and nothing is concluded from them.
"""

import argparse
import json
import os


ENGINE_NAMES = ["doc_ingest", "langchain"]

# The groups of evaluation.json shown in the table, in order. "matching" is saved flat; the others keep their sums under "total".
EVALUATION_GROUPS = ["matching", "text_accuracy", "cleanup_quality", "metadata_quality"]

# Shown for a score an engine does not have
NOT_AVAILABLE = "N/A"


def load_json_file(json_path: str) -> dict | None:
	"""
	Input: json_path - a JSON file.
	Output: its contents, or None if the file does not exist.
	"""
	if not os.path.isfile(json_path):
		return None
	with open(json_path, encoding="utf-8") as json_file:
		return json.load(json_file)


def read_group_totals(evaluation_values: dict | None, group_name: str) -> dict:
	"""
	Input: evaluation_values - one engine's evaluation.json (or None); group_name - one of EVALUATION_GROUPS.
	Output: the group's total values, name -> value; an empty dict if the engine has none.
	"""
	if evaluation_values is None:
		return {}
	if group_name not in evaluation_values:
		return {}

	group_values = evaluation_values[group_name]
	if "total" in group_values:
		return group_values["total"]
	return group_values


def collect_rows(group_name: str, totals_by_engine: dict) -> list[list[str]]:
	"""
	Input: group_name; totals_by_engine - engine name -> that engine's totals for the group.
	Output: one row per value name: [group.name, then each engine's value as text]. A missing value is NOT_AVAILABLE.
	What it does: takes the value names in the order they were saved, first from doc_ingest, then any only LangChain has.
	"""
	value_names = []
	for engine_name in ENGINE_NAMES:
		for value_name in totals_by_engine[engine_name]:
			if value_name not in value_names:
				value_names.append(value_name)

	rows = []
	for value_name in value_names:
		row = [group_name + "." + value_name]
		for engine_name in ENGINE_NAMES:
			engine_totals = totals_by_engine[engine_name]
			if value_name in engine_totals and engine_totals[value_name] is not None:
				row.append(str(engine_totals[value_name]))
			else:
				row.append(NOT_AVAILABLE)
		rows.append(row)
	return rows


def build_table(dataset_path: str, dedup_path: str | None) -> str:
	"""
	Input: dataset_path - the dataset's logs folder, with <engine>/evaluation.json for each engine;
	dedup_path - doc_ingest's dedup_quality.json, or None.
	Output: the Markdown table: one row per saved total, one column per engine.
	What it does: reads each engine's evaluation.json and adds the dedup totals (doc_ingest only; LangChain has no dedup).
	"""
	evaluation_by_engine = {}
	for engine_name in ENGINE_NAMES:
		evaluation_path = os.path.join(dataset_path, engine_name, "evaluation.json")
		evaluation_by_engine[engine_name] = load_json_file(evaluation_path)

	rows = []
	for group_name in EVALUATION_GROUPS:
		totals_by_engine = {}
		for engine_name in ENGINE_NAMES:
			totals_by_engine[engine_name] = read_group_totals(evaluation_by_engine[engine_name], group_name)
		for row in collect_rows(group_name, totals_by_engine):
			rows.append(row)

	if dedup_path is not None:
		dedup_values = load_json_file(dedup_path)
		totals_by_engine = {"doc_ingest": {}, "langchain": {}}
		if dedup_values is not None:
			totals_by_engine["doc_ingest"] = dedup_values["dedup_quality"]["total"]
		for row in collect_rows("dedup_quality", totals_by_engine):
			rows.append(row)

	table_lines = []
	table_lines.append("| | " + " | ".join(ENGINE_NAMES) + " |")
	separator_cells = ["---"]
	for engine_name in ENGINE_NAMES:
		separator_cells.append("---")
	table_lines.append("|" + "|".join(separator_cells) + "|")
	for row in rows:
		table_lines.append("| " + " | ".join(row) + " |")

	return "\n".join(table_lines)


def main() -> None:
	"""
	Input: --dataset_path and optional --dedup_path from the command line.
	Output: none. Saves the table as report.md in the dataset's logs folder, prints it and where it was saved.
	"""
	argument_parser = argparse.ArgumentParser(description="Put both engines' saved scores for one dataset in one table.")
	argument_parser.add_argument("--dataset_path", required=True, help="The dataset's logs folder, e.g. logs/DUDE_50")
	argument_parser.add_argument("--dedup_path", default=None, help="doc_ingest's dedup_quality.json for this dataset, if there is one")
	arguments = argument_parser.parse_args()

	dataset_name = os.path.basename(os.path.normpath(arguments.dataset_path))
	report_text = "# " + dataset_name + "\n\n" + build_table(arguments.dataset_path, arguments.dedup_path) + "\n"

	report_path = os.path.join(arguments.dataset_path, "report.md")
	with open(report_path, "w", encoding="utf-8") as report_file:
		report_file.write(report_text)

	print(report_text)
	print("Report saved to " + report_path)


if __name__ == "__main__":
	main()
