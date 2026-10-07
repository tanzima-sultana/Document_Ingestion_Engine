"""Benchmark baseline: load a folder of PDFs with LangChain's PyPDFLoader and time it."""

import argparse
import os
import time

from langchain_community.document_loaders import PyPDFLoader


def list_pdf_files(folder_path: str) -> list[str]:
	"""Input: a folder path. Output: sorted list of .pdf file paths in it (subfolders included).
	Hidden files and folders are skipped, like doc_ingest's local loader."""
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


def main() -> None:
	"""Input: --input_path from the command line. Output: a timing summary printed to the screen.
	Loads every PDF one by one with PyPDFLoader (one page per LangChain Document) and skips failures."""
	argument_parser = argparse.ArgumentParser(description="Load PDFs with LangChain PyPDFLoader and time it.")
	argument_parser.add_argument("--input_path", required=True, help="Folder of PDF files")
	arguments = argument_parser.parse_args()

	pdf_paths = list_pdf_files(arguments.input_path)
	print(f"Input path: {arguments.input_path}")
	print(f"PDF files found: {len(pdf_paths)}")

	files_loaded = 0
	files_failed = 0
	pages_loaded = 0
	characters_loaded = 0

	start_time = time.perf_counter()
	for pdf_path in pdf_paths:
		try:
			page_documents = PyPDFLoader(pdf_path).load()
		except Exception as error:
			files_failed = files_failed + 1
			print(f"Skipped {pdf_path}: {type(error).__name__}: {error}")
			continue
		files_loaded = files_loaded + 1
		pages_loaded = pages_loaded + len(page_documents)
		for page_document in page_documents:
			characters_loaded = characters_loaded + len(page_document.page_content)
	total_seconds = time.perf_counter() - start_time

	documents_per_second = 0.0
	pages_per_second = 0.0
	if total_seconds > 0:
		documents_per_second = files_loaded / total_seconds
		pages_per_second = pages_loaded / total_seconds

	print("LangChain PyPDFLoader summary")
	print(f"  files_loaded: {files_loaded}")
	print(f"  files_failed: {files_failed}")
	print(f"  pages_loaded: {pages_loaded}")
	print(f"  characters_loaded: {characters_loaded}")
	print(f"  total_seconds: {total_seconds:.2f}")
	print(f"  documents_per_second: {documents_per_second:.2f}")
	print(f"  pages_per_second: {pages_per_second:.2f}")


if __name__ == "__main__":
	main()
