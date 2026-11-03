"""
benchmarks/pdf/langchain.py

Plain LangChain PDF loading, using the same PyPDFium2 parsing as doc_ingest.
"""

import os

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
