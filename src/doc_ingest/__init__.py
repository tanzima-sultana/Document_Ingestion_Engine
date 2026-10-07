"""
doc_ingest package.
Exposes the main CLI entry point.
"""

import argparse
import os
import sys

from doc_ingest import cache
from doc_ingest.dataset_config import normalize_input_path
from doc_ingest.ingest import DEFAULT_DOWNLOAD_WORKERS
from doc_ingest.ingest import ingest_documents

def parse_args(argument_list):
	"""
	Input:
		argument_list - list of command line strings, usually sys.argv[1:].
	Output:
		argparse.Namespace with size, input_path, download_workers and
		parse_workers.
	What it does:
		Reads the options run.sh passes in. The worker counts are optional.
		Stops with an error message if a required option is missing or a
		number option is not a whole number.
	"""
	argument_parser = argparse.ArgumentParser(
		description="Ingest documents into clean, deduplicated JSON."
	)
	argument_parser.add_argument(
		"--size",
		type=int,
		required=True,
		help="Maximum number of documents to process.",
	)
	argument_parser.add_argument(
		"--input_path",
		type=str,
		required=True,
		help="Local path, URL, or dataset name to read documents from.",
	)
	argument_parser.add_argument(
		"--download_workers",
		type=int,
		default=DEFAULT_DOWNLOAD_WORKERS,
		help="Number of documents downloaded/decoded at the same time (default: %(default)s).",
	)
	argument_parser.add_argument(
		"--parse_workers",
		type=int,
		default=None,
		help="Number of documents parsed at the same time (default: number of CPU cores).",
	)
	parsed_arguments = argument_parser.parse_args(argument_list)
	return parsed_arguments


if __name__ == "__main__":

	args = parse_args(sys.argv[1:])
	size = args.size
	# A Hugging Face dataset page URL is turned into the dataset name
	input_path = normalize_input_path(args.input_path)
	storage_path = cache.get_storage_path()
	download_workers = args.download_workers
	parse_workers = args.parse_workers

	print("Starting document ingestion")
	print("  size        : " + str(size))
	print("  input_path  : " + input_path)
	print("  storage_path : " + storage_path)
	print("  download_workers : " + str(download_workers))
	if parse_workers is None:
		print("  parse_workers    : number of CPU cores")
	else:
		print("  parse_workers    : " + str(parse_workers))


	# Ingestion. ingest_documents validates the inputs first.
	# A ValueError (failed check or damaged progress file) prints a clean
	# message (no traceback) and stops the program
	try:
		documents = ingest_documents(
			size,
			input_path,
			download_workers=download_workers,
			parse_workers=parse_workers,
		)
	except ValueError as ingestion_error:
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
