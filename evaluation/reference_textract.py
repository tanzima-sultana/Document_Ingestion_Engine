"""
evaluation/reference_textract.py

Builds the reference page text from Amazon Textract output, for any dataset that has it.
Usage: python evaluation/reference_textract.py --pdf_path FOLDER --textract_path FOLDER --output_path FILE
"""

import argparse
import json
import os


def list_pdf_files(pdf_folder: str) -> list[str]:
	"""
	Input: pdf_folder - a folder of PDFs.
	Output: the PDF file paths, in sorted order, built the same way as the engines build `source`.
	"""
	pdf_paths = []
	for current_folder, sub_folder_names, file_names in os.walk(pdf_folder):
		for file_name in file_names:
			if file_name.lower().endswith(".pdf"):
				pdf_paths.append(os.path.join(current_folder, file_name))

	pdf_paths.sort()
	return pdf_paths


def find_textract_file(pdf_path: str, textract_folder: str) -> str | None:
	"""
	Input: pdf_path - one PDF; textract_folder - the folder of Textract JSON files.
	Output: the path of the Textract file for this PDF, or None if there is none.
	What it does: picks the JSON file whose name is the PDF's name without ".pdf",
	followed by "." or "_" (for example "a.json" or "a_original.json" for "a.pdf").
	"""
	pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]

	matching_file_names = []
	for file_name in os.listdir(textract_folder):
		if not file_name.lower().endswith(".json"):
			continue
		if file_name.startswith(pdf_name + ".") or file_name.startswith(pdf_name + "_"):
			matching_file_names.append(file_name)

	if len(matching_file_names) == 0:
		return None

	matching_file_names.sort()
	return os.path.join(textract_folder, matching_file_names[0])


def read_textract_pages(textract_path: str) -> list[dict]:
	"""
	Input: textract_path - one Textract JSON file: one response, or a list of responses for a multi-page document.
	Output: the pages, each {"number": n, "text": its lines joined with newlines}, numbered from 1.
	What it does: takes the LINE blocks in order. A page with no lines is kept with empty text.
	"""
	with open(textract_path, encoding="utf-8") as textract_file:
		textract_data = json.load(textract_file)

	responses = textract_data
	if isinstance(textract_data, dict):
		responses = [textract_data]

	page_count = 0
	lines_by_page = {}
	for response in responses:
		document_metadata = response.get("DocumentMetadata", {})
		page_count = max(page_count, document_metadata.get("Pages", 0))

		for block in response.get("Blocks", []):
			if block.get("BlockType") != "LINE":
				continue
			# A single-page response has no "Page" key
			page_number = block.get("Page", 1)
			if page_number not in lines_by_page:
				lines_by_page[page_number] = []
			lines_by_page[page_number].append(block.get("Text", ""))
			page_count = max(page_count, page_number)

	pages = []
	for page_number in range(1, page_count + 1):
		page_lines = lines_by_page.get(page_number, [])
		pages.append({"number": page_number, "text": "\n".join(page_lines)})
	return pages


def main() -> None:
	"""
	Input: --pdf_path, --textract_path and --output_path from the command line.
	Output: none. Writes the reference JSONL file and prints how many PDFs it covers.
	What it does: for each PDF, reads its Textract file and writes one line: its source and its pages.
	A PDF with no Textract file is printed and left out.
	"""
	argument_parser = argparse.ArgumentParser(description="Build reference page text from Amazon Textract output.")
	argument_parser.add_argument("--pdf_path", required=True, help="Folder of the PDFs, the same path the engines read")
	argument_parser.add_argument("--textract_path", required=True, help="Folder of the Textract JSON files")
	argument_parser.add_argument("--output_path", required=True, help="Reference JSONL file to write")
	arguments = argument_parser.parse_args()

	output_folder = os.path.dirname(arguments.output_path)
	if output_folder != "":
		os.makedirs(output_folder, exist_ok=True)

	pdf_paths = list_pdf_files(arguments.pdf_path)
	references_written = 0
	pdfs_without_reference = 0

	with open(arguments.output_path, "w", encoding="utf-8") as output_file:
		for pdf_path in pdf_paths:
			textract_path = find_textract_file(pdf_path, arguments.textract_path)
			if textract_path is None:
				print("No Textract file for " + pdf_path)
				pdfs_without_reference = pdfs_without_reference + 1
				continue

			reference_values = {"source": pdf_path, "pages": read_textract_pages(textract_path)}
			output_file.write(json.dumps(reference_values, ensure_ascii=False) + "\n")
			references_written = references_written + 1

	print("PDFs: " + str(len(pdf_paths)))
	print("References written: " + str(references_written))
	print("PDFs without a reference: " + str(pdfs_without_reference))
	print("Saved to " + arguments.output_path)


if __name__ == "__main__":
	main()
