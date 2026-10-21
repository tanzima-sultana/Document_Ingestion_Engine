"""
Benchmark baseline: load the benchmark's local PDF folder with a LangChain loader (one process) and
report the shared doc_ingest Summary, so the result can be compared field by field with doc_ingest's.
"""

import argparse
import datetime
import json
import logging
import os
import sys
import time

import yaml
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.document_loaders import PyPDFium2Loader

from doc_ingest.settings import DownloadSettings
from doc_ingest.settings import ProcessSettings
from doc_ingest.settings import ParserSettings
from doc_ingest.summary import Summary
from doc_ingest.summary import print_run_summary
from doc_ingest.summary import summary_to_dict

# Loader name in config.yaml -> (the PDF library it uses, the loader class)
LOADERS = {
	"PyPDFLoader": ("pypdf", PyPDFLoader),
	"PyPDFium2Loader": ("pypdfium2", PyPDFium2Loader),
}


def load_config(config_path: str) -> dict:
	"""
	Input: config_path - the benchmark's config.yaml.
	Output: the config as a dict.
	"""
	with open(config_path, encoding="utf-8") as config_file:
		config = yaml.safe_load(config_file)
	return config


def list_pdf_files(folder_path: str) -> list[str]:
	"""
	Input: a folder path. Output: sorted list of .pdf file paths in it (subfolders included).
	Hidden files and folders are skipped, like doc_ingest's local loader.
	"""
	pdf_paths = []
	for current_folder, subfolder_names, file_names in os.walk(folder_path):
		visible_subfolder_names = []
		for subfolder_name in subfolder_names:
			if not subfolder_name.startswith("."):
				visible_subfolder_names.append(subfolder_name)
		subfolder_names[:] = visible_subfolder_names
		for file_name in file_names:
			if file_name.startswith("."):
				continue
			if file_name.lower().endswith(".pdf"):
				pdf_paths.append(os.path.join(current_folder, file_name))
	pdf_paths.sort()
	return pdf_paths


def make_summary(config: dict, pdf_library: str) -> Summary:
	"""
	Input: config - the benchmark config; pdf_library - the library the chosen loader uses.
	Output: an empty Summary for a LangChain run. Settings LangChain does not have are None.
	"""
	summary = Summary()
	summary.tool = "langchain"
	summary.doc_types = ["pdf"]
	summary.dataset = config["dataset"]
	summary.requested_size = config["size"]
	summary.download_settings = DownloadSettings(download_workers=None, max_batch_rows=None, hugging_face_split=None)
	summary.process_settings = ProcessSettings(parse_workers=1, dedup_threshold=None)
	summary.parser_settings = ParserSettings(pdf_parser=pdf_library, parse_timeout_seconds=None)
	return summary


def load_all_pdfs(pdf_paths: list[str], loader_class, summary: Summary) -> None:
	"""
	Input: pdf_paths - the files to load; loader_class - the LangChain loader; summary - filled in place.
	Output: none. Loads every file one by one, timing each, and counts pages, characters and failures.
	"""
	parse_start = time.perf_counter()
	for pdf_path in pdf_paths:
		summary.files_read = summary.files_read + 1
		summary.downloaded = summary.downloaded + 1

		document_start = time.perf_counter()
		try:
			page_documents = loader_class(pdf_path).load()
		except Exception as error:
			print(f"Skipped {pdf_path}: {type(error).__name__}: {error}")
			summary.parse_failed = summary.parse_failed + 1
			summary.skipped = summary.skipped + 1
			continue
		document_seconds = time.perf_counter() - document_start

		summary.document_parse_seconds.append(document_seconds)
		summary.documents_returned = summary.documents_returned + 1
		# PDF loaders return one LangChain Document per page
		summary.pages = summary.pages + len(page_documents)
		for page_document in page_documents:
			summary.characters = summary.characters + len(page_document.page_content)

	summary.parse_seconds = time.perf_counter() - parse_start


def save_summary_json(summary: Summary) -> str:
	"""
	Input: the run's Summary. Output: the path of the saved file, logs/summary_langchain_pdf_<date>_<time>.json.
	"""
	run_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
	summary_path = os.path.join("logs", "summary_langchain_pdf_" + run_time + ".json")
	os.makedirs("logs", exist_ok=True)
	with open(summary_path, "w", encoding="utf-8") as summary_file:
		json.dump(summary_to_dict(summary), summary_file, indent=2)
	return summary_path


def main() -> None:
	"""
	Input: --config_path from the command line (run.sh passes it).
	Output: none. Loads every PDF in input_path with the configured loader, then prints and saves the Summary.
	"""
	# print_run_summary logs through doc_ingest's logger; show it like the doc_ingest CLI does
	logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)
	logging.getLogger("doc_ingest").setLevel(logging.INFO)

	argument_parser = argparse.ArgumentParser(description="Load the benchmark PDFs with a LangChain loader and time it.")
	argument_parser.add_argument("--config_path", required=True, help="The benchmark's config.yaml")
	arguments = argument_parser.parse_args()

	config = load_config(arguments.config_path)
	loader_name = config["langchain"]["loader"]
	if loader_name not in LOADERS:
		print(f"Unknown loader {loader_name!r}. Choose one of: {list(LOADERS.keys())}")
		sys.exit(1)
	pdf_library, loader_class = LOADERS[loader_name]

	input_path = config["input_path"]
	pdf_paths = list_pdf_files(input_path)
	print(f"LangChain {loader_name} on {input_path}: {len(pdf_paths)} PDF file(s)")

	run_start = time.perf_counter()
	summary = make_summary(config, pdf_library)
	load_all_pdfs(pdf_paths, loader_class, summary)
	# LangChain reads every file in the folder
	summary.source_exhausted = True
	summary.total_seconds = time.perf_counter() - run_start

	print_run_summary(summary)
	summary_path = save_summary_json(summary)
	print("Summary saved to " + summary_path)


if __name__ == "__main__":
	main()
