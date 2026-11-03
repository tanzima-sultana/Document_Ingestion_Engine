"""
__main__.py

Command line entry point: python -m doc_ingest --path PATH --size N --document_type pdf
or python -m doc_ingest --config_path config.yaml (run.sh does this).
"""

import argparse
import json
import logging
import os
import sys

import yaml

from doc_ingest.ingest import ingest_documents
from doc_ingest.error import IngestError
from doc_ingest.settings import DEFAULT_DEDUP_THRESHOLD
from doc_ingest.settings import DEFAULT_PARSE_TIMEOUT_SECONDS
from doc_ingest.settings import Settings

# Keys a config file may set: top-level keys, then each settings group and its keys.
# Every key has the same name as its command line option.
CONFIG_TOP_LEVEL_KEYS = ["path", "size", "document_type"]
CONFIG_GROUP_KEYS = {
	"settings": ["dedup_threshold", "timeout_seconds"],
}


def load_config_file(config_path: str) -> dict:
	"""
	Input: config_path - path of a YAML config file (see config.yaml at the repo root).
	Output: a flat dict of option name -> value, e.g. {"size": 5000, "timeout_seconds": 120}.
	What it does: reads the file and checks that every key is a known option. Raises ValueError with a readable
		message if the file is missing, is not valid YAML, or has an unknown key.
	"""
	try:
		with open(config_path, encoding="utf-8") as config_file:
			config_data = yaml.safe_load(config_file)
	except OSError as read_error:
		raise ValueError("config file could not be read: " + repr(config_path) + " (" + str(read_error) + ")")
	except yaml.YAMLError as yaml_error:
		raise ValueError("config file is not valid YAML: " + repr(config_path) + " (" + str(yaml_error) + ")")

	# An empty file sets nothing
	if config_data is None:
		return {}
	if not isinstance(config_data, dict):
		raise ValueError("config file must hold key: value pairs: " + repr(config_path))

	config_values = {}
	for key, value in config_data.items():
		if key in CONFIG_TOP_LEVEL_KEYS:
			config_values[key] = value
			continue

		if key not in CONFIG_GROUP_KEYS:
			raise ValueError("unknown key in config file: " + repr(key))

		# A group with nothing under it sets nothing
		if value is None:
			continue
		if not isinstance(value, dict):
			raise ValueError("config key " + repr(key) + " must hold key: value pairs")

		for setting_name, setting_value in value.items():
			if setting_name not in CONFIG_GROUP_KEYS[key]:
				raise ValueError("unknown key in config file: " + repr(key + "." + str(setting_name)))
			config_values[setting_name] = setting_value

	return config_values


def parse_args(argument_list):
	"""
	Input:
		argument_list - list of command line strings, usually sys.argv[1:].
	Output:
		argparse.Namespace with config_path, path, size, document_type and
		every setting.
	What it does:
		Reads the command line options. With --config_path, the values in
		that config file are used first; an option typed on the command
		line still wins, and anything set in neither uses the library
		default. path, size and document_type must be set in one of the
		two; every setting is optional and shown in the --help settings
		group. Stops with an error message if one of them is missing, the
		config file is bad, or a number option is not a number.
	"""
	argument_parser = argparse.ArgumentParser(
		description="Ingest documents into clean, deduplicated JSON."
	)
	argument_parser.add_argument(
		"--config_path",
		type=str,
		default=None,
		help="YAML file with the options below; options typed on the command line override it.",
	)
	# Not required=True here: these may come from the config file instead (checked below)
	argument_parser.add_argument(
		"--path",
		type=str,
		default=None,
		help="Local file or folder to read documents from (required, here or in the config file).",
	)
	argument_parser.add_argument(
		"--size",
		type=int,
		default=None,
		help="Maximum number of documents to process (required, here or in the config file).",
	)
	argument_parser.add_argument(
		"--document_type",
		type=str,
		default=None,
		help="Type of document to keep, e.g. pdf; other documents are discarded (required, here or in the config file).",
	)

	settings_group = argument_parser.add_argument_group("settings")
	settings_group.add_argument(
		"--dedup_threshold",
		type=float,
		default=DEFAULT_DEDUP_THRESHOLD,
		help="Similarity at or above which two documents are near-duplicates (default: %(default)s).",
	)
	settings_group.add_argument(
		"--timeout_seconds",
		type=int,
		default=DEFAULT_PARSE_TIMEOUT_SECONDS,
		help="Longest time one document may take to parse before it is skipped (default: %(default)s).",
	)

	# Read --config_path on its own first, so the config file's values can
	# become the defaults before the full command line is read
	config_path_parser = argparse.ArgumentParser(add_help=False)
	config_path_parser.add_argument("--config_path", type=str, default=None)
	# parse_known_args returns (known options, the other options); only the known ones are needed here
	config_path_arguments = config_path_parser.parse_known_args(argument_list)[0]

	if config_path_arguments.config_path is not None:
		try:
			config_values = load_config_file(config_path_arguments.config_path)
		except ValueError as config_error:
			argument_parser.error(str(config_error))
		argument_parser.set_defaults(**config_values)

	parsed_arguments = argument_parser.parse_args(argument_list)

	if parsed_arguments.path is None:
		argument_parser.error("path is required: pass --path or set path in the config file")
	if parsed_arguments.size is None:
		argument_parser.error("size is required: pass --size or set size in the config file")
	if parsed_arguments.document_type is None:
		argument_parser.error("document_type is required: pass --document_type or set document_type in the config file")

	return parsed_arguments


def make_output_folder(input_path: str, document_type: str, size: int) -> str:
	"""
	Input: input_path - the file or folder the run read; document_type - the type asked for; size - the number of documents asked for.
	Output: the run's output folder, logs/<dataset name>_<document type>_<size>/doc_ingest, created if it does not exist.
	"""
	dataset_name = os.path.basename(os.path.normpath(input_path))
	output_folder = os.path.join("logs", dataset_name + "_" + document_type + "_" + str(size), "doc_ingest")
	os.makedirs(output_folder, exist_ok=True)
	return output_folder


def save_summary_json(summary_values: dict, input_path: str, document_type: str, size: int) -> str:
	"""
	Input: summary_values - the run's summary as a dict; input_path - the file or folder the run read;
		document_type - the type asked for; size - the number of documents asked for.
	Output: the path of the saved file, logs/<dataset name>_<document type>_<size>/doc_ingest/summary.json.
	What it does: writes it as indented JSON, replacing the last run's file.
	"""
	output_folder = make_output_folder(input_path, document_type, size)
	summary_path = os.path.join(output_folder, "summary.json")

	with open(summary_path, "w", encoding="utf-8") as summary_file:
		json.dump(summary_values, summary_file, indent=2)
	return summary_path


def save_documents_jsonl(documents: list, input_path: str, document_type: str, size: int) -> str:
	"""
	Input: documents - the returned Documents; input_path - the file or folder the run read;
		document_type - the type asked for; size - the number of documents asked for.
	Output: the path of the saved file, logs/<dataset name>_<document type>_<size>/doc_ingest/documents.jsonl.
	What it does: writes one Document per line as JSON (id, type, source, title, pages), replacing the last run's file.
	"""
	output_folder = make_output_folder(input_path, document_type, size)
	documents_path = os.path.join(output_folder, "documents.jsonl")

	with open(documents_path, "w", encoding="utf-8") as documents_file:
		for document in documents:
			document_values = document.model_dump(mode="json")
			documents_file.write(json.dumps(document_values, ensure_ascii=False) + "\n")
	return documents_path


def save_sources_read(sources_read: list[str], input_path: str, document_type: str, size: int) -> str:
	"""
	Input: sources_read - the source of every document the run read; input_path - the file or folder the run read;
		document_type - the type asked for; size - the number of documents asked for.
	Output: the path of the saved file, logs/<dataset name>_<document type>_<size>/doc_ingest/sources_read.txt.
	What it does: writes one source per line, replacing the last run's file.
	"""
	output_folder = make_output_folder(input_path, document_type, size)
	sources_read_path = os.path.join(output_folder, "sources_read.txt")

	with open(sources_read_path, "w", encoding="utf-8") as sources_read_file:
		for source in sources_read:
			sources_read_file.write(source + "\n")
	return sources_read_path


def main():
	"""
	Input: none (reads sys.argv). Output: none; exits the process (0 on success, 1 on an IngestError).
	What it does: sets up logging, prints the run settings, runs ingest_documents and prints when it is done.
	"""
	# The library only logs; the CLI decides how logs are shown.
	# stdout, so they stay in order with the prints below.
	# Other libraries (e.g. httpx, used by Hugging Face) show warnings only; doc_ingest shows its progress too.
	logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)
	logging.getLogger("doc_ingest").setLevel(logging.INFO)

	args = parse_args(sys.argv[1:])
	settings = Settings(
		dedup_threshold=args.dedup_threshold,
		timeout_seconds=args.timeout_seconds,
	)

	print("Starting document ingestion")
	if args.config_path is not None:
		print("  config_path   : " + args.config_path)
	print("  path          : " + args.path)
	print("  size          : " + str(args.size))
	print("  document_type : " + args.document_type)
	print("  settings      : " + str(settings))


	# Ingestion. ingest_documents validates the inputs first.
	# An IngestError (failed check) prints a clean
	# message (no traceback) and stops the program. Any other error is a
	# bug or a system problem and keeps its full traceback.
	try:
		ingest_result = ingest_documents(
			args.path,
			args.size,
			args.document_type,
			settings=settings,
		)
	except IngestError as ingestion_error:
		sys.stdout.flush()
		print("Ingestion stopped: " + str(ingestion_error), file=sys.stderr)
		sys.exit(1)

	print("Document ingestion finished")

	summary_path = save_summary_json(ingest_result.summary.to_dict(), args.path, args.document_type, args.size)
	print("Summary saved to " + summary_path)

	documents_path = save_documents_jsonl(ingest_result.documents, args.path, args.document_type, args.size)
	print("Documents saved to " + documents_path)

	sources_read_path = save_sources_read(ingest_result.sources_read, args.path, args.document_type, args.size)
	print("Sources read saved to " + sources_read_path)

	# huggingface `datasets`/fsspec leaves a background thread alive after
	# streaming a dataset, which crashes normal interpreter shutdown with
	# "Fatal Python error: PyGILState_Release" (known upstream bug,
	# huggingface/datasets#7357). All work is done by this point, so skip
	# Python's normal finalization/thread-teardown instead of hitting it.
	sys.stdout.flush()
	sys.stderr.flush()
	os._exit(0)


if __name__ == "__main__":
	main()
