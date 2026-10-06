"""
doc_ingest package.
Exposes the main CLI entry point.
"""

import argparse
import os
import sys

from doc_ingest import validate
from doc_ingest.ingest import ingest_documents

def parse_args(argument_list):
	"""
	Input:
		argument_list - list of command line strings, usually sys.argv[1:].
	Output:
		argparse.Namespace with three fields: size (int), input_path (str)
		and output_path (str).
	What it does:
		Reads the --size, --input_path and --output_path options that run.sh
		passes in. Stops the program with an error message if any is missing
		or if --size is not a whole number.
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
		"--output_path",
		type=str,
		required=True,
		help="Folder where the output JSON files are written.",
	)
	parsed_arguments = argument_parser.parse_args(argument_list)
	return parsed_arguments


if __name__ == "__main__":

	args = parse_args(sys.argv[1:])
	size = args.size
	input_path = args.input_path
	output_path = args.output_path 

	os.makedirs(args.output_path, exist_ok=True)

	print("Starting document ingestion")
	print("  size        : " + str(size))
	print("  input_path  : " + input_path)
	print("  output_path : " + output_path)


	# 1. Validation
	# A failed check prints a clean message (no traceback) and stops the program
	try:
		validate.validate_dataset(size, input_path, output_path)
	except (TypeError, ValueError) as validation_error:
		sys.stdout.flush()
		print("Validation failed: " + str(validation_error), file=sys.stderr)
		sys.exit(1)

	# 2. Ingestion
	documents = ingest_documents(
		size,
		input_path,
		output_path,
	)

	print("Document ingestion finished")

	# huggingface `datasets`/fsspec leaves a background thread alive after
	# streaming a dataset, which crashes normal interpreter shutdown with
	# "Fatal Python error: PyGILState_Release" (known upstream bug,
	# huggingface/datasets#7357). All work is done by this point, so skip
	# Python's normal finalization/thread-teardown instead of hitting it.
	sys.stdout.flush()
	sys.stderr.flush()
	os._exit(0)
