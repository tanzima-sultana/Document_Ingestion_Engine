"""
__main__.py

Command line entry point: python -m doc_ingest --size N --input_path PATH
or python -m doc_ingest --config_path config.yaml (run.sh does this).
"""

import argparse
import logging
import os
import sys

import yaml

from doc_ingest.ingest import ingest_documents
from doc_ingest.error import IngestError
from doc_ingest.settings import DEFAULT_DEDUP_THRESHOLD
from doc_ingest.settings import DEFAULT_DOWNLOAD_WORKERS
from doc_ingest.settings import DEFAULT_HUGGING_FACE_SPLIT
from doc_ingest.settings import DEFAULT_MAX_BATCH_ROWS
from doc_ingest.settings import DEFAULT_PARSE_TIMEOUT_SECONDS
from doc_ingest.settings import DEFAULT_PDF_PARSER
from doc_ingest.settings import PDF_PARSER_NAMES
from doc_ingest.settings import DownloadSettings
from doc_ingest.settings import ProcessSettings
from doc_ingest.settings import ParserSettings

# Keys a config file may set: top-level keys, then each settings group and its keys.
# Every key has the same name as its command line option.
CONFIG_TOP_LEVEL_KEYS = ["size", "input_path"]
CONFIG_GROUP_KEYS = {
	"download_settings": ["download_workers", "max_batch_rows", "hugging_face_split"],
	"process_settings": ["parse_workers", "dedup_threshold"],
	"parser_settings": ["pdf_parser", "parse_timeout_seconds"],
}


def load_config_file(config_path: str) -> dict:
	"""
	Input: config_path - path of a YAML config file (see config.yaml at the repo root).
	Output: a flat dict of option name -> value, e.g. {"size": 5000, "download_workers": 64}.
	What it does: reads the file and checks that every key is a known option, in its right group.
		Raises ValueError with a readable message if the file is missing, is not valid YAML, or has an unknown key.
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
		argparse.Namespace with config_path, size, input_path, and every
		download, process and parser setting.
	What it does:
		Reads the command line options. With --config_path, the values in
		that config file are used first; an option typed on the command
		line still wins, and anything set in neither uses the library
		default. size and input_path must be set in one of the two; every
		setting is optional and shown in its own --help group. Stops with
		an error message if size or input_path is missing, the config file
		is bad, or a number option is not a number.
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
	# Not required=True here: size and input_path may come from the config file instead (checked below)
	argument_parser.add_argument(
		"--size",
		type=int,
		default=None,
		help="Maximum number of documents to process (required, here or in the config file).",
	)
	argument_parser.add_argument(
		"--input_path",
		type=str,
		default=None,
		help="Local path, or Hugging Face dataset name (or its page URL), to read documents from (required, here or in the config file).",
	)

	download_group = argument_parser.add_argument_group("download settings")
	download_group.add_argument(
		"--download_workers",
		type=int,
		default=DEFAULT_DOWNLOAD_WORKERS,
		help="Number of documents downloaded/decoded at the same time (default: %(default)s).",
	)
	download_group.add_argument(
		"--max_batch_rows",
		type=int,
		default=DEFAULT_MAX_BATCH_ROWS,
		help="Most rows read in one batch; limits memory use (default: %(default)s).",
	)
	download_group.add_argument(
		"--hugging_face_split",
		type=str,
		default=DEFAULT_HUGGING_FACE_SPLIT,
		help="Split read from a Hugging Face dataset (default: %(default)s).",
	)

	process_group = argument_parser.add_argument_group("process settings")
	process_group.add_argument(
		"--parse_workers",
		type=int,
		default=None,
		help="Number of documents parsed at the same time (default: number of CPU cores).",
	)
	process_group.add_argument(
		"--dedup_threshold",
		type=float,
		default=DEFAULT_DEDUP_THRESHOLD,
		help="Similarity at or above which two documents are near-duplicates (default: %(default)s).",
	)

	parser_group = argument_parser.add_argument_group("parser settings")
	parser_group.add_argument(
		"--pdf_parser",
		type=str,
		choices=PDF_PARSER_NAMES,
		default=DEFAULT_PDF_PARSER,
		help="Library that parses PDFs; pypdfium2 needs pip install pypdfium2 (default: %(default)s).",
	)
	parser_group.add_argument(
		"--parse_timeout_seconds",
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

	if parsed_arguments.size is None:
		argument_parser.error("size is required: pass --size or set size in the config file")
	if parsed_arguments.input_path is None:
		argument_parser.error("input_path is required: pass --input_path or set input_path in the config file")

	return parsed_arguments


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
	size = args.size
	input_path = args.input_path
	download_settings = DownloadSettings(
		download_workers=args.download_workers,
		max_batch_rows=args.max_batch_rows,
		hugging_face_split=args.hugging_face_split,
	)
	process_settings = ProcessSettings(
		parse_workers=args.parse_workers,
		dedup_threshold=args.dedup_threshold,
	)
	parser_settings = ParserSettings(
		pdf_parser=args.pdf_parser,
		parse_timeout_seconds=args.parse_timeout_seconds,
	)

	print("Starting document ingestion")
	if args.config_path is not None:
		print("  config_path : " + args.config_path)
	print("  size        : " + str(size))
	print("  input_path  : " + input_path)
	print("  download_settings : " + str(download_settings))
	print("  process_settings  : " + str(process_settings))
	print("  parser_settings   : " + str(parser_settings))


	# Ingestion. ingest_documents validates the inputs first.
	# An IngestError (failed check) prints a clean
	# message (no traceback) and stops the program. Any other error is a
	# bug or a system problem and keeps its full traceback.
	try:
		ingest_result = ingest_documents(
			size,
			input_path,
			download_settings=download_settings,
			process_settings=process_settings,
			parser_settings=parser_settings,
		)
	except IngestError as ingestion_error:
		sys.stdout.flush()
		print("Ingestion stopped: " + str(ingestion_error), file=sys.stderr)
		sys.exit(1)

	print("Document ingestion finished")

	# huggingface `datasets`/fsspec leaves a background thread alive after
	# streaming a dataset, which crashes normal interpreter shutdown with
	# "Fatal Python error: PyGILState_Release" (known upstream bug,
	# huggingface/datasets#7357). All work is done by this point, so skip
	# Python's normal finalization/thread-teardown instead of hitting it.
	sys.stdout.flush()
	sys.stderr.flush()
	os._exit(0)


# Guard: spawned parse workers re-import this module and must not start another run
if __name__ == "__main__":
	main()
