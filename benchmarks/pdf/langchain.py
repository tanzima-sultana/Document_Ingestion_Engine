"""
benchmarks/pdf/langchain.py

Plain LangChain PDF loading, using the same PyPDFium2 parsing as doc_ingest.
"""

import argparse
import json
import os

import yaml
from langchain_community.document_loaders import PyPDFium2Loader


def list_pdf_files(path: str) -> list[str]:
	"""
	Input: path - a PDF file or a folder of PDFs.
	Output: the PDF file paths, in sorted order.
	"""
	if os.path.isfile(path):
		return [path]

	pdf_paths = []
	for current_folder, sub_folder_names, file_names in os.walk(path):
		for file_name in file_names:
			if file_name.lower().endswith(".pdf"):
				pdf_paths.append(os.path.join(current_folder, file_name))

	pdf_paths.sort()
	return pdf_paths


def load_pages(path: str, size: int) -> list:
	"""
	Input: path - a PDF file or a folder of PDFs; size - the most PDF files to load.
	Output: a list of pages, each one a LangChain Document (page_content and metadata).
	"""
	pages = []
	for pdf_path in list_pdf_files(path)[:size]:
		loader = PyPDFium2Loader(pdf_path)
		pages.extend(loader.load())

	return pages


def main() -> None:
	"""
	Input: --config_path from the command line (a YAML file with path and size).
	Output: none. Prints the counts for the run and saves them to logs/<dataset name>/langchain/summary.json,
	and the pages to logs/<dataset name>/langchain/documents.jsonl. Both replace the last run's files.
	What it does: loads each PDF with plain LangChain and counts the files it loads, the pages it returns,
	the blank pages (only whitespace) and the raw characters of all pages. Each loaded file is saved
	as one line: its source and its pages, each with a number from 1 and its raw text.
	"""
	argument_parser = argparse.ArgumentParser(description="Plain LangChain PDF loading.")
	argument_parser.add_argument("--config_path", required=True, help="YAML file with path and size")
	arguments = argument_parser.parse_args()

	with open(arguments.config_path, encoding="utf-8") as config_file:
		config_values = yaml.safe_load(config_file)

	pdf_paths = list_pdf_files(config_values["path"])[:config_values["size"]]

	dataset_name = os.path.basename(os.path.normpath(config_values["path"]))
	output_folder = os.path.join("logs", dataset_name, "langchain")
	os.makedirs(output_folder, exist_ok=True)
	documents_path = os.path.join(output_folder, "documents.jsonl")
	documents_file = open(documents_path, "w", encoding="utf-8")

	documents_requested = config_values["size"]
	documents_returned = 0
	total_pages = 0
	blank_pages = 0
	total_characters = 0

	for pdf_path in pdf_paths:
		try:
			loader = PyPDFium2Loader(pdf_path)
			loaded_pages = loader.load()
		except Exception as load_error:
			print("Failed: " + pdf_path + " (" + repr(load_error) + ")")
			continue

		documents_returned = documents_returned + 1
		saved_pages = []
		page_number = 0
		for page in loaded_pages:
			page_number = page_number + 1
			saved_pages.append({"number": page_number, "text": page.page_content})
			total_pages = total_pages + 1
			if page.page_content.strip() == "":
				blank_pages = blank_pages + 1
			total_characters = total_characters + len(page.page_content)

		document_values = {"source": pdf_path, "pages": saved_pages}
		documents_file.write(json.dumps(document_values, ensure_ascii=False) + "\n")

	documents_file.close()

	print("LangChain run summary")
	print("  documents_requested : " + str(documents_requested))
	print("  documents_returned  : " + str(documents_returned))
	print("  total_pages         : " + str(total_pages))
	print("  blank_pages         : " + str(blank_pages))
	print("  total_characters    : " + str(total_characters))

	summary_values = {
		"documents_requested": documents_requested,
		"documents_returned": documents_returned,
		"total_pages": total_pages,
		"blank_pages": blank_pages,
		"total_characters": total_characters,
	}
	summary_path = os.path.join(output_folder, "summary.json")
	with open(summary_path, "w", encoding="utf-8") as summary_file:
		json.dump(summary_values, summary_file, indent=2)

	print("Summary saved to " + summary_path)
	print("Documents saved to " + documents_path)


if __name__ == "__main__":
	main()
