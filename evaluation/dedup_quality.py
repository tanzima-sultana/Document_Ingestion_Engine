"""
evaluation/dedup_quality.py

Dedup quality: copies caught, copies missed and false matches (distinct documents removed).

Two steps:
	build: python evaluation/dedup_quality.py build --reference_path FILE --output_path FOLDER --manifest_path FILE
		Writes one text PDF per reference document (the originals), plus exact copies (the same bytes)
		and near copies (the same text with a few words changed), and a manifest of which file is which.
	score: python evaluation/dedup_quality.py score --documents_path FILE --manifest_path FILE
		Reads the engine's documents.jsonl after a run on the test folder and counts what it removed.
"""

import argparse
import json
import os
import random
import shutil
import textwrap


# Share of a document's words changed in a near copy (at least one word)
NEAR_COPY_CHANGED_WORD_FRACTION = 0.005

# The word put in place of each changed word
CHANGED_WORD = "changed"

# Page layout of the generated PDFs: US Letter, Helvetica 9pt
PAGE_WIDTH = 612
PAGE_HEIGHT = 792
FONT_SIZE = 9
LINE_HEIGHT = 11
LEFT_MARGIN = 40
TOP_MARGIN = 40
CHARACTERS_PER_LINE = 100
LINES_PER_PAGE = 64

# Folder names inside the test folder. Engines read files in sorted path order,
# so every original comes before every copy and the original is the one kept.
ORIGINALS_FOLDER = "1_originals"
COPIES_FOLDER = "2_copies"


def load_reference_documents(reference_path: str) -> list[dict]:
	"""
	Input: reference_path - a JSONL file with one document per line, each with "source" and "pages".
	Output: the documents in file order, each {"source": ..., "page_texts": [text of each page]}.
	"""
	reference_documents = []
	with open(reference_path, encoding="utf-8") as reference_file:
		for line in reference_file:
			if line.strip() == "":
				continue
			document_values = json.loads(line)

			page_texts = []
			for page in document_values["pages"]:
				page_texts.append(page["text"])
			reference_documents.append({"source": document_values["source"], "page_texts": page_texts})

	return reference_documents


def count_words(page_texts: list[str]) -> int:
	"""
	Input: page_texts - the text of each page of a document.
	Output: the number of whitespace-separated words in all pages.
	"""
	word_count = 0
	for page_text in page_texts:
		word_count = word_count + len(page_text.split())
	return word_count


def change_words(page_texts: list[str], random_generator: random.Random) -> tuple[list[str], int]:
	"""
	Input: page_texts - the text of each page of a document; random_generator - for picking the words.
	Output: (the page texts with some words replaced by CHANGED_WORD, how many words were changed).
	What it does: picks NEAR_COPY_CHANGED_WORD_FRACTION of the document's words (at least one) at random
	and replaces each one. Line breaks are kept.
	"""
	pages_lines_words = []
	word_positions = []
	for page_index in range(len(page_texts)):
		page_lines_words = []
		page_lines = page_texts[page_index].splitlines()
		for line_index in range(len(page_lines)):
			line_words = page_lines[line_index].split()
			page_lines_words.append(line_words)
			for word_index in range(len(line_words)):
				word_positions.append((page_index, line_index, word_index))
		pages_lines_words.append(page_lines_words)

	changed_word_count = round(len(word_positions) * NEAR_COPY_CHANGED_WORD_FRACTION)
	if changed_word_count < 1:
		changed_word_count = 1

	positions_to_change = random_generator.sample(word_positions, changed_word_count)
	for page_index, line_index, word_index in positions_to_change:
		pages_lines_words[page_index][line_index][word_index] = CHANGED_WORD

	changed_page_texts = []
	for page_lines_words in pages_lines_words:
		page_lines = []
		for line_words in page_lines_words:
			page_lines.append(" ".join(line_words))
		changed_page_texts.append("\n".join(page_lines))

	return changed_page_texts, changed_word_count


def escape_pdf_text(line: str) -> bytes:
	"""
	Input: line - one line of text.
	Output: the line as Windows-1252 bytes (characters it cannot hold become "?"), escaped for a PDF string.
	"""
	line_bytes = line.encode("cp1252", errors="replace")
	line_bytes = line_bytes.replace(b"\\", b"\\\\")
	line_bytes = line_bytes.replace(b"(", b"\\(")
	line_bytes = line_bytes.replace(b")", b"\\)")
	return line_bytes


def layout_pdf_pages(page_texts: list[str]) -> list[list[str]]:
	"""
	Input: page_texts - the text of each page of a document.
	Output: the lines of each PDF page. Long lines are wrapped at CHARACTERS_PER_LINE, and a page with
	more than LINES_PER_PAGE lines continues on a new PDF page. An empty page stays a blank PDF page.
	"""
	pdf_pages_lines = []
	for page_text in page_texts:
		wrapped_lines = []
		for line in page_text.splitlines():
			if line.strip() == "":
				continue
			for wrapped_line in textwrap.wrap(line, CHARACTERS_PER_LINE):
				wrapped_lines.append(wrapped_line)

		if len(wrapped_lines) == 0:
			pdf_pages_lines.append([])
			continue

		line_start = 0
		while line_start < len(wrapped_lines):
			pdf_pages_lines.append(wrapped_lines[line_start:line_start + LINES_PER_PAGE])
			line_start = line_start + LINES_PER_PAGE

	return pdf_pages_lines


def write_text_pdf(page_texts: list[str], pdf_path: str) -> None:
	"""
	Input: page_texts - the text of each page of a document; pdf_path - the PDF file to write.
	Output: none. Writes a plain PDF with the text in Helvetica.
	What it does: builds the PDF objects (catalog, page tree, font, and a page and content stream per page)
	and writes them with their cross-reference table, so no PDF library is needed.
	"""
	pdf_pages_lines = layout_pdf_pages(page_texts)

	# Objects 1-3 are the catalog, page tree and font; each page then takes two objects
	page_object_numbers = []
	for page_position in range(len(pdf_pages_lines)):
		page_object_numbers.append(4 + 2 * page_position)

	page_references = []
	for page_object_number in page_object_numbers:
		page_references.append(str(page_object_number) + " 0 R")

	pdf_objects = []
	pdf_objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
	pdf_objects.append(
		("<< /Type /Pages /Kids [" + " ".join(page_references) + "] /Count " + str(len(page_references)) + " >>").encode("ascii")
	)
	pdf_objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

	for page_position in range(len(pdf_pages_lines)):
		content_object_number = page_object_numbers[page_position] + 1
		page_object = (
			"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " + str(PAGE_WIDTH) + " " + str(PAGE_HEIGHT) + "]"
			+ " /Resources << /Font << /F1 3 0 R >> >> /Contents " + str(content_object_number) + " 0 R >>"
		)
		pdf_objects.append(page_object.encode("ascii"))

		content_stream = b""
		page_lines = pdf_pages_lines[page_position]
		if len(page_lines) > 0:
			first_line_y = PAGE_HEIGHT - TOP_MARGIN
			content_stream = (
				"BT /F1 " + str(FONT_SIZE) + " Tf " + str(LINE_HEIGHT) + " TL "
				+ str(LEFT_MARGIN) + " " + str(first_line_y) + " Td\n"
			).encode("ascii")
			for line in page_lines:
				content_stream = content_stream + b"(" + escape_pdf_text(line) + b") Tj T*\n"
			content_stream = content_stream + b"ET"

		content_object = b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n" + content_stream + b"\nendstream"
		pdf_objects.append(content_object)

	pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
	object_offsets = []
	for object_index in range(len(pdf_objects)):
		object_offsets.append(len(pdf_bytes))
		object_number = object_index + 1
		pdf_bytes = pdf_bytes + str(object_number).encode("ascii") + b" 0 obj\n" + pdf_objects[object_index] + b"\nendobj\n"

	cross_reference_offset = len(pdf_bytes)
	pdf_bytes = pdf_bytes + b"xref\n0 " + str(len(pdf_objects) + 1).encode("ascii") + b"\n"
	pdf_bytes = pdf_bytes + b"0000000000 65535 f \n"
	for object_offset in object_offsets:
		pdf_bytes = pdf_bytes + str(object_offset).zfill(10).encode("ascii") + b" 00000 n \n"
	pdf_bytes = pdf_bytes + b"trailer\n<< /Size " + str(len(pdf_objects) + 1).encode("ascii") + b" /Root 1 0 R >>\n"
	pdf_bytes = pdf_bytes + b"startxref\n" + str(cross_reference_offset).encode("ascii") + b"\n%%EOF\n"

	with open(pdf_path, "wb") as pdf_file:
		pdf_file.write(pdf_bytes)


def build_test_folder(reference_path: str, output_path: str, manifest_path: str, exact_copy_count: int, near_copy_count: int, seed: int) -> dict:
	"""
	Input: the reference JSONL, the test folder and manifest file to write, how many exact and near copies to make,
	and the random seed.
	Output: the manifest: the settings, and one entry per file with its path, role
	("original", "exact_copy" or "near_copy"), its original's path and how many words were changed.
	What it does: writes one PDF per reference document that has words, then copies randomly picked
	originals: exact copies byte for byte, near copies with a few words changed. Each original gets at most one copy.
	"""
	originals_folder = os.path.join(output_path, ORIGINALS_FOLDER)
	copies_folder = os.path.join(output_path, COPIES_FOLDER)
	os.makedirs(originals_folder, exist_ok=False)
	os.makedirs(copies_folder, exist_ok=False)

	reference_documents = load_reference_documents(reference_path)

	originals = []
	reference_documents_without_words = 0
	for reference_document in reference_documents:
		if count_words(reference_document["page_texts"]) == 0:
			reference_documents_without_words = reference_documents_without_words + 1
			continue

		file_name = os.path.splitext(os.path.basename(reference_document["source"]))[0] + ".pdf"
		original_path = os.path.join(originals_folder, file_name)
		write_text_pdf(reference_document["page_texts"], original_path)
		originals.append({"path": original_path, "file_name": file_name, "page_texts": reference_document["page_texts"]})

	if exact_copy_count + near_copy_count > len(originals):
		raise ValueError("asked for " + str(exact_copy_count + near_copy_count) + " copies but there are only " + str(len(originals)) + " originals")

	random_generator = random.Random(seed)
	copied_originals = random_generator.sample(originals, exact_copy_count + near_copy_count)

	manifest_files = []
	for original in originals:
		manifest_files.append({"path": original["path"], "role": "original", "original": None, "words_changed": 0})

	for copy_position in range(len(copied_originals)):
		original = copied_originals[copy_position]
		if copy_position < exact_copy_count:
			copy_path = os.path.join(copies_folder, "exact_" + original["file_name"])
			shutil.copyfile(original["path"], copy_path)
			manifest_files.append({"path": copy_path, "role": "exact_copy", "original": original["path"], "words_changed": 0})
		else:
			changed_page_texts, changed_word_count = change_words(original["page_texts"], random_generator)
			copy_path = os.path.join(copies_folder, "near_" + original["file_name"])
			write_text_pdf(changed_page_texts, copy_path)
			manifest_files.append({"path": copy_path, "role": "near_copy", "original": original["path"], "words_changed": changed_word_count})

	manifest = {
		"reference_path": reference_path,
		"output_path": output_path,
		"seed": seed,
		"near_copy_changed_word_fraction": NEAR_COPY_CHANGED_WORD_FRACTION,
		"reference_documents": len(reference_documents),
		"reference_documents_without_words": reference_documents_without_words,
		"originals": len(originals),
		"exact_copies": exact_copy_count,
		"near_copies": near_copy_count,
		"files": manifest_files,
	}

	manifest_folder = os.path.dirname(manifest_path)
	if manifest_folder != "":
		os.makedirs(manifest_folder, exist_ok=True)
	with open(manifest_path, "w", encoding="utf-8") as manifest_file:
		json.dump(manifest, manifest_file, indent=2)

	return manifest


def load_returned_sources(documents_path: str) -> set[str]:
	"""
	Input: documents_path - the engine's documents.jsonl.
	Output: the normalized source paths of every document the engine returned.
	"""
	returned_sources = set()
	with open(documents_path, encoding="utf-8") as documents_file:
		for line in documents_file:
			if line.strip() == "":
				continue
			document_values = json.loads(line)
			returned_sources.add(os.path.normpath(document_values["source"]))
	return returned_sources


def compute_rate(count: int, total: int) -> float | None:
	"""
	Input: count and total.
	Output: count / total rounded to 4 places, or None if total is 0.
	"""
	if total == 0:
		return None
	return round(count / total, 4)


def evaluate_dedup_quality(manifest: dict, returned_sources: set[str]) -> dict:
	"""
	Input: manifest - from build_test_folder; returned_sources - from load_returned_sources.
	Output: a dict with "total" (counts and rates) and "files" (each file's role, original and whether it was removed).
	What it does: a copy the engine did not return is caught, one it returned is missed.
	An original the engine did not return is a false match (a distinct document removed).
	"""
	counts = {
		"originals": 0,
		"originals_kept": 0,
		"false_matches": 0,
		"exact_copies": 0,
		"exact_copies_caught": 0,
		"exact_copies_missed": 0,
		"near_copies": 0,
		"near_copies_caught": 0,
		"near_copies_missed": 0,
	}
	file_results = []

	for manifest_file in manifest["files"]:
		was_returned = os.path.normpath(manifest_file["path"]) in returned_sources
		role = manifest_file["role"]

		if role == "original":
			counts["originals"] = counts["originals"] + 1
			if was_returned:
				counts["originals_kept"] = counts["originals_kept"] + 1
			else:
				counts["false_matches"] = counts["false_matches"] + 1
		elif role == "exact_copy":
			counts["exact_copies"] = counts["exact_copies"] + 1
			if was_returned:
				counts["exact_copies_missed"] = counts["exact_copies_missed"] + 1
			else:
				counts["exact_copies_caught"] = counts["exact_copies_caught"] + 1
		elif role == "near_copy":
			counts["near_copies"] = counts["near_copies"] + 1
			if was_returned:
				counts["near_copies_missed"] = counts["near_copies_missed"] + 1
			else:
				counts["near_copies_caught"] = counts["near_copies_caught"] + 1

		file_results.append({
			"path": manifest_file["path"],
			"role": role,
			"original": manifest_file["original"],
			"words_changed": manifest_file["words_changed"],
			"returned": was_returned,
		})

	copies = counts["exact_copies"] + counts["near_copies"]
	copies_caught = counts["exact_copies_caught"] + counts["near_copies_caught"]

	total_result = dict(counts)
	total_result["copies"] = copies
	total_result["copies_caught"] = copies_caught
	total_result["copies_missed"] = copies - copies_caught
	total_result["exact_copy_catch_rate"] = compute_rate(counts["exact_copies_caught"], counts["exact_copies"])
	total_result["near_copy_catch_rate"] = compute_rate(counts["near_copies_caught"], counts["near_copies"])
	total_result["copy_catch_rate"] = compute_rate(copies_caught, copies)
	total_result["false_match_rate"] = compute_rate(counts["false_matches"], counts["originals"])

	return {"total": total_result, "files": file_results}


def main() -> None:
	"""
	Input: the "build" or "score" command and its options from the command line.
	Output: none. build writes the test folder and manifest; score saves dedup_quality.json next to the
	documents file. Both print what they wrote.
	"""
	argument_parser = argparse.ArgumentParser(description="Build a dedup test folder, or score an engine's run on it.")
	command_parsers = argument_parser.add_subparsers(dest="command", required=True)

	build_parser = command_parsers.add_parser("build", help="Write the test folder and its manifest")
	build_parser.add_argument("--reference_path", required=True, help="The reference pages.jsonl to take the text from")
	build_parser.add_argument("--output_path", required=True, help="New folder to write the test PDFs to")
	build_parser.add_argument("--manifest_path", required=True, help="Manifest JSON file to write, outside the test folder")
	build_parser.add_argument("--exact_copies", type=int, default=20, help="How many exact copies to make")
	build_parser.add_argument("--near_copies", type=int, default=20, help="How many near copies to make")
	build_parser.add_argument("--seed", type=int, default=0, help="Random seed for picking originals and words")

	score_parser = command_parsers.add_parser("score", help="Score an engine's run on the test folder")
	score_parser.add_argument("--documents_path", required=True, help="The engine's documents.jsonl from its run on the test folder")
	score_parser.add_argument("--manifest_path", required=True, help="The manifest written by build")

	arguments = argument_parser.parse_args()

	if arguments.command == "build":
		manifest = build_test_folder(
			arguments.reference_path,
			arguments.output_path,
			arguments.manifest_path,
			arguments.exact_copies,
			arguments.near_copies,
			arguments.seed,
		)
		print("Reference documents: " + str(manifest["reference_documents"]))
		print("Reference documents without words (left out): " + str(manifest["reference_documents_without_words"]))
		print("Originals: " + str(manifest["originals"]))
		print("Exact copies: " + str(manifest["exact_copies"]))
		print("Near copies: " + str(manifest["near_copies"]))
		print("Files written: " + str(len(manifest["files"])) + " in " + arguments.output_path)
		print("Manifest saved to " + arguments.manifest_path)
		return

	with open(arguments.manifest_path, encoding="utf-8") as manifest_file:
		manifest = json.load(manifest_file)
	returned_sources = load_returned_sources(arguments.documents_path)

	dedup_values = {
		"documents_path": arguments.documents_path,
		"manifest_path": arguments.manifest_path,
		"dedup_quality": evaluate_dedup_quality(manifest, returned_sources),
	}

	dedup_path = os.path.join(os.path.dirname(arguments.documents_path), "dedup_quality.json")
	with open(dedup_path, "w", encoding="utf-8") as dedup_file:
		json.dump(dedup_values, dedup_file, indent=2)

	print("Dedup quality saved to " + dedup_path)


if __name__ == "__main__":
	main()
