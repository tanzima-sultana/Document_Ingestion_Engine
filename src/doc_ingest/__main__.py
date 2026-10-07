"""
__main__.py

Command line entry point: python -m doc_ingest --size N --input_path PATH
"""

import argparse
import logging
import os
import sys

from doc_ingest import cache
from doc_ingest.ingest import ingest_documents
from doc_ingest.error import IngestError
from doc_ingest.settings import DEFAULT_DEDUP_THRESHOLD
from doc_ingest.settings import DEFAULT_DOWNLOAD_WORKERS
from doc_ingest.settings import DEFAULT_HUGGING_FACE_SPLIT
from doc_ingest.settings import DEFAULT_MAX_BATCH_ROWS
from doc_ingest.settings import DEFAULT_PARSE_TIMEOUT_SECONDS
from doc_ingest.settings import DownloadSettings
from doc_ingest.settings import ProcessSettings


def parse_args(argument_list):
	"""
	Input:
		argument_list - list of command line strings, usually sys.argv[1:].
	Output:
		argparse.Namespace with size, input_path, and every download and
		process setting.
	What it does:
		Reads the options run.sh passes in. Only size and input_path are
		required; every setting is optional and shown in its own --help
		group. Stops with an error message if a required option is missing
		or a number option is not a number.
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
		help="Local path, or Hugging Face dataset name (or its page URL), to read documents from.",
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
		"--parse_timeout_seconds",
		type=int,
		default=DEFAULT_PARSE_TIMEOUT_SECONDS,
		help="Longest time one document may take to parse before it is skipped (default: %(default)s).",
	)
	process_group.add_argument(
		"--dedup_threshold",
		type=float,
		default=DEFAULT_DEDUP_THRESHOLD,
		help="Similarity at or above which two documents are near-duplicates (default: %(default)s).",
	)
	parsed_arguments = argument_parser.parse_args(argument_list)
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
	storage_path = cache.get_storage_path()
	download_settings = DownloadSettings(
		download_workers=args.download_workers,
		max_batch_rows=args.max_batch_rows,
		hugging_face_split=args.hugging_face_split,
	)
	process_settings = ProcessSettings(
		parse_workers=args.parse_workers,
		parse_timeout_seconds=args.parse_timeout_seconds,
		dedup_threshold=args.dedup_threshold,
	)

	print("Starting document ingestion")
	print("  size        : " + str(size))
	print("  input_path  : " + input_path)
	print("  storage_path : " + storage_path)
	print("  download_settings : " + str(download_settings))
	print("  process_settings  : " + str(process_settings))


	# Ingestion. ingest_documents validates the inputs first.
	# An IngestError (failed check or damaged progress file) prints a clean
	# message (no traceback) and stops the program. Any other error is a
	# bug or a system problem and keeps its full traceback.
	try:
		ingest_result = ingest_documents(
			size,
			input_path,
			download_settings=download_settings,
			process_settings=process_settings,
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
