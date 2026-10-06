"""
text_cleanup.py

Cleans a document's text: strips repeated headers/footers and collapses
repeated whitespace and blank lines.
"""

import re

import pypdf


# A first/last line is a header/footer if it repeats on this fraction of pages
HEADER_FOOTER_MIN_PAGE_FRACTION = 0.5

# Documents with fewer pages are not checked for headers/footers
HEADER_FOOTER_MIN_PAGE_COUNT = 3

WHITESPACE_PATTERN = re.compile(r"\s+")
DIGITS_PATTERN = re.compile(r"\d+")


def extract_clean_text(reader: pypdf.PdfReader) -> str:
	"""
	Input: pypdf reader of a PDF. Output: its cleaned text.
	Collapses whitespace in each line, removes header/footer lines and
	repeated blank lines, and joins the pages with one blank line.
	"""
	pages_lines = []
	for page in reader.pages:
		try:
			page_text = page.extract_text()
		except Exception as error:
			print(f"Could not extract page text: {type(error).__name__}: {error}")
			page_text = ""

		page_lines = []
		for line in page_text.splitlines():
			line = WHITESPACE_PATTERN.sub(" ", line)
			page_lines.append(line.strip())
		pages_lines.append(page_lines)

	header_footer_keys = find_header_footer_keys(pages_lines)

	page_texts = []
	for page_lines in pages_lines:
		kept_lines = []
		for line in page_lines:
			line_key = DIGITS_PATTERN.sub("#", line.lower())
			if line_key in header_footer_keys:
				continue
			# Keep at most one blank line in a row
			if line == "" and len(kept_lines) > 0 and kept_lines[-1] == "":
				continue
			kept_lines.append(line)

		page_text = "\n".join(kept_lines)
		page_text = page_text.strip()
		if page_text != "":
			page_texts.append(page_text)

	return "\n\n".join(page_texts)


def find_header_footer_keys(pages_lines: list[list[str]]) -> set[str]:
	"""
	Input: lines of each page. Output: keys of the header/footer lines.
	A key is a line lowercased with digits as "#", so "Page 3" matches
	"Page 4". A first/last line repeating on enough pages is a header/footer.
	"""
	header_footer_keys = set()
	page_count = len(pages_lines)
	if page_count < HEADER_FOOTER_MIN_PAGE_COUNT:
		return header_footer_keys

	key_page_counts = {}
	for page_lines in pages_lines:
		non_empty_lines = []
		for line in page_lines:
			if line != "":
				non_empty_lines.append(line)
		if len(non_empty_lines) == 0:
			continue

		page_keys = set()
		page_keys.add(DIGITS_PATTERN.sub("#", non_empty_lines[0].lower()))
		page_keys.add(DIGITS_PATTERN.sub("#", non_empty_lines[-1].lower()))
		for key in page_keys:
			if key not in key_page_counts:
				key_page_counts[key] = 0
			key_page_counts[key] = key_page_counts[key] + 1

	for key, key_page_count in key_page_counts.items():
		if key_page_count >= page_count * HEADER_FOOTER_MIN_PAGE_FRACTION:
			header_footer_keys.add(key)

	return header_footer_keys
