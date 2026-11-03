"""
evaluation/evaluation.py

Runs the evaluation of one engine's output against the reference page text.
Usage: python evaluation/evaluation.py --documents_path FILE --reference_path FILE
It only reads files, so it scores every engine the same way.
"""

import argparse
import json
import os

import cleanup_quality
import metadata_quality
import text_accuracy


def load_documents_by_source(jsonl_path: str) -> dict:
	"""
	Input: jsonl_path - a JSONL file with one document per line, each with "source" and "pages".
	Output: a dict of source -> {page number -> page text}.
	"""
	documents_by_source = {}
	with open(jsonl_path, encoding="utf-8") as jsonl_file:
		for line in jsonl_file:
			if line.strip() == "":
				continue
			document_values = json.loads(line)

			page_texts_by_number = {}
			for page in document_values["pages"]:
				page_texts_by_number[page["number"]] = page["text"]
			documents_by_source[document_values["source"]] = page_texts_by_number

	return documents_by_source


def load_sources_read(sources_read_path: str) -> set[str]:
	"""
	Input: sources_read_path - the engine's sources_read.txt, one source per line.
	Output: the set of sources the engine read.
	What it does: stops with an error if the file does not exist, since the reference cannot be cut to what was read without it.
	"""
	if not os.path.isfile(sources_read_path):
		raise SystemExit("sources_read.txt not found: " + sources_read_path + " (run the engine again to save it)")

	sources_read = set()
	with open(sources_read_path, encoding="utf-8") as sources_read_file:
		for line in sources_read_file:
			source = line.rstrip("\n")
			if source != "":
				sources_read.add(source)
	return sources_read


def keep_sources_read(reference_documents: dict, sources_read: set[str]) -> dict:
	"""
	Input: reference_documents - source -> {page number -> page text}; sources_read - from load_sources_read.
	Output: only the reference documents the engine read.
	"""
	reference_documents_read = {}
	for source in reference_documents:
		if source in sources_read:
			reference_documents_read[source] = reference_documents[source]
	return reference_documents_read


def match_pages(reference_documents: dict, output_documents: dict) -> list[dict]:
	"""
	Input: reference_documents and output_documents - each a dict of source -> {page number -> page text}.
	Output: one dict per reference page: source, number, reference_text, output_text and document_returned.
	What it does: pairs each reference page with the engine's page of the same source and number.
	If the engine did not return the document or the page, output_text is "", and
	document_returned says whether the document was returned at all.
	"""
	matched_pages = []

	reference_sources = list(reference_documents.keys())
	reference_sources.sort()

	for source in reference_sources:
		reference_pages = reference_documents[source]
		document_returned = source in output_documents

		output_pages = {}
		if document_returned:
			output_pages = output_documents[source]

		page_numbers = list(reference_pages.keys())
		page_numbers.sort()

		for page_number in page_numbers:
			output_text = output_pages.get(page_number, "")
			matched_pages.append({
				"source": source,
				"number": page_number,
				"reference_text": reference_pages[page_number],
				"output_text": output_text,
				"document_returned": document_returned,
			})

	return matched_pages


def count_matching(reference_documents: dict, output_documents: dict, matched_pages: list[dict]) -> dict:
	"""
	Input: the reference and output documents (source -> pages) and the matched pages.
	Output: a dict of counts that say how the engine's output lines up with the reference.
	"""
	documents_returned = 0
	for source in reference_documents:
		if source in output_documents:
			documents_returned = documents_returned + 1

	documents_not_in_reference = 0
	for source in output_documents:
		if source not in reference_documents:
			documents_not_in_reference = documents_not_in_reference + 1

	pages_of_returned_documents = 0
	for matched_page in matched_pages:
		if matched_page["document_returned"]:
			pages_of_returned_documents = pages_of_returned_documents + 1

	return {
		"reference_documents": len(reference_documents),
		"documents_returned": documents_returned,
		"documents_not_returned": len(reference_documents) - documents_returned,
		"documents_not_in_reference": documents_not_in_reference,
		"reference_pages": len(matched_pages),
		"pages_of_returned_documents": pages_of_returned_documents,
		"pages_of_documents_not_returned": len(matched_pages) - pages_of_returned_documents,
	}


def main() -> None:
	"""
	Input: --documents_path and --reference_path from the command line.
	Output: none. Saves the results as evaluation.json next to the documents file and prints where.
	What it does: loads both files, keeps the reference documents listed in sources_read.txt next to the documents file,
	pairs every reference page with the engine's page, and saves the counts and scores.
	"""
	argument_parser = argparse.ArgumentParser(description="Evaluate one engine's output against the reference.")
	argument_parser.add_argument("--documents_path", required=True, help="The engine's documents.jsonl")
	argument_parser.add_argument("--reference_path", required=True, help="The reference pages.jsonl")
	arguments = argument_parser.parse_args()

	# The reference covers the whole raw folder; only the documents the engine read are scored
	sources_read_path = os.path.join(os.path.dirname(arguments.documents_path), "sources_read.txt")
	sources_read = load_sources_read(sources_read_path)
	reference_documents = keep_sources_read(load_documents_by_source(arguments.reference_path), sources_read)
	output_documents = load_documents_by_source(arguments.documents_path)
	matched_pages = match_pages(reference_documents, output_documents)

	evaluation_values = {
		"documents_path": arguments.documents_path,
		"reference_path": arguments.reference_path,
		"matching": count_matching(reference_documents, output_documents, matched_pages),
		"text_accuracy": text_accuracy.evaluate_text_accuracy(matched_pages),
		"cleanup_quality": cleanup_quality.evaluate_cleanup_quality(matched_pages),
		"metadata_quality": metadata_quality.evaluate_metadata_quality(arguments.documents_path, reference_documents),
	}

	evaluation_path = os.path.join(os.path.dirname(arguments.documents_path), "evaluation.json")
	with open(evaluation_path, "w", encoding="utf-8") as evaluation_file:
		json.dump(evaluation_values, evaluation_file, indent=2)

	print("Evaluation saved to " + evaluation_path)


if __name__ == "__main__":
	main()
