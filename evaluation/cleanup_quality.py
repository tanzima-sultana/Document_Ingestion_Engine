"""
evaluation/cleanup_quality.py

Cleanup quality: boilerplate removed and content wrongly removed.
Boilerplate lines are found in the reference text with a rule of its own, not the engine's rule.
Each engine is scored only on the pages of the documents it returned.
"""

import re
from collections import Counter

from text_accuracy import normalize_text


# How many non-empty lines at the top and at the bottom of a page can be boilerplate
EDGE_LINE_COUNT = 3

# An edge line is boilerplate if it repeats on this fraction of a document's pages
BOILERPLATE_MIN_PAGE_FRACTION = 0.5

# Documents with fewer pages are not checked for repeated lines
BOILERPLATE_MIN_PAGE_COUNT = 3

DIGITS_PATTERN = re.compile(r"\d+")
# A normalized line that is only a page number, e.g. "12", "page 3", "3 of 10", "page 3 of 10"
PAGE_NUMBER_PATTERN = re.compile(r"^(page )?\d+( of \d+)?$")


def split_page_lines(page_text: str) -> list[str]:
	"""
	Input: page_text - one page's text.
	Output: the page's lines, normalized (normalize_text), with empty lines left out.
	"""
	normalized_lines = []
	for line in page_text.splitlines():
		normalized_line = normalize_text(line)
		if normalized_line != "":
			normalized_lines.append(normalized_line)
	return normalized_lines


def find_edge_lines(page_lines: list[str]) -> list[str]:
	"""
	Input: page_lines - the normalized lines of one page.
	Output: the first and last EDGE_LINE_COUNT lines; on a short page, every line once.
	"""
	if len(page_lines) <= 2 * EDGE_LINE_COUNT:
		return list(page_lines)

	edge_lines = []
	for line in page_lines[:EDGE_LINE_COUNT]:
		edge_lines.append(line)
	for line in page_lines[-EDGE_LINE_COUNT:]:
		edge_lines.append(line)
	return edge_lines


def make_line_key(line: str) -> str:
	"""
	Input: line - one normalized line.
	Output: the line with every run of digits as "#", so "page 3" and "page 4" have the same key.
	"""
	return DIGITS_PATTERN.sub("#", line)


def find_repeated_keys(document_pages_lines: list[list[str]]) -> set[str]:
	"""
	Input: document_pages_lines - the normalized lines of each page of one reference document.
	Output: the keys of edge lines that repeat on at least BOILERPLATE_MIN_PAGE_FRACTION of its pages.
	A document with fewer than BOILERPLATE_MIN_PAGE_COUNT pages has none.
	"""
	repeated_keys = set()
	page_count = len(document_pages_lines)
	if page_count < BOILERPLATE_MIN_PAGE_COUNT:
		return repeated_keys

	key_page_counts = {}
	for page_lines in document_pages_lines:
		page_keys = set()
		for line in find_edge_lines(page_lines):
			page_keys.add(make_line_key(line))
		for key in page_keys:
			if key not in key_page_counts:
				key_page_counts[key] = 0
			key_page_counts[key] = key_page_counts[key] + 1

	for key, key_page_count in key_page_counts.items():
		if key_page_count >= page_count * BOILERPLATE_MIN_PAGE_FRACTION:
			repeated_keys.add(key)

	return repeated_keys


def split_boilerplate(page_lines: list[str], repeated_keys: set[str]) -> tuple[list[str], list[str]]:
	"""
	Input: page_lines - the normalized lines of one reference page; repeated_keys - from find_repeated_keys.
	Output: (boilerplate_lines, content_lines).
	What it does: an edge line is boilerplate if its key repeats across the document or it is only a page number.
	Every other line is content.
	"""
	edge_line_positions = set()
	if len(page_lines) <= 2 * EDGE_LINE_COUNT:
		for position in range(len(page_lines)):
			edge_line_positions.add(position)
	else:
		for position in range(EDGE_LINE_COUNT):
			edge_line_positions.add(position)
		for position in range(len(page_lines) - EDGE_LINE_COUNT, len(page_lines)):
			edge_line_positions.add(position)

	boilerplate_lines = []
	content_lines = []
	for position in range(len(page_lines)):
		line = page_lines[position]
		is_boilerplate = False
		if position in edge_line_positions:
			if make_line_key(line) in repeated_keys:
				is_boilerplate = True
			if PAGE_NUMBER_PATTERN.match(line):
				is_boilerplate = True

		if is_boilerplate:
			boilerplate_lines.append(line)
		else:
			content_lines.append(line)

	return boilerplate_lines, content_lines


def is_line_kept(boilerplate_line: str, output_lines: list[str]) -> bool:
	"""
	Input: boilerplate_line - one normalized reference line; output_lines - the normalized lines of the engine's page.
	Output: True if the engine's page still has the line.
	What it does: a page number line must be a whole output line, so "12" does not match "figure 12".
	Any other line may also sit inside a longer output line, as whole words.
	"""
	for output_line in output_lines:
		if output_line == boilerplate_line:
			return True

	if PAGE_NUMBER_PATTERN.match(boilerplate_line):
		return False

	for output_line in output_lines:
		if (" " + boilerplate_line + " ") in (" " + output_line + " "):
			return True

	return False


def count_page(boilerplate_lines: list[str], content_lines: list[str], output_text: str) -> dict:
	"""
	Input: the boilerplate and content lines of one reference page, and the engine's text of the page.
	Output: a dict of counts for the page: boilerplate_lines, boilerplate_lines_removed,
	content_words and content_words_missing.
	What it does: counts the boilerplate lines the engine's page no longer has, and the content
	words it is missing (each word as often as it appears in the reference).
	"""
	output_lines = split_page_lines(output_text)

	boilerplate_lines_removed = 0
	for boilerplate_line in boilerplate_lines:
		if not is_line_kept(boilerplate_line, output_lines):
			boilerplate_lines_removed = boilerplate_lines_removed + 1

	content_words = []
	for content_line in content_lines:
		for word in content_line.split():
			content_words.append(word)

	output_words = []
	for output_line in output_lines:
		for word in output_line.split():
			output_words.append(word)

	content_word_counts = Counter(content_words)
	output_word_counts = Counter(output_words)
	content_words_found = 0
	for word in content_word_counts:
		content_words_found = content_words_found + min(content_word_counts[word], output_word_counts[word])

	return {
		"boilerplate_lines": len(boilerplate_lines),
		"boilerplate_lines_removed": boilerplate_lines_removed,
		"content_words": len(content_words),
		"content_words_missing": len(content_words) - content_words_found,
	}


def compute_scores(counts: dict) -> dict:
	"""
	Input: counts - the counts from count_page, or their sums over many pages.
	Output: a dict of boilerplate_removed and content_wrongly_removed (shares from 0 to 1), rounded to 4 places.
	A score that would divide by zero is None.
	"""
	boilerplate_removed = None
	if counts["boilerplate_lines"] > 0:
		boilerplate_removed = round(counts["boilerplate_lines_removed"] / counts["boilerplate_lines"], 4)

	content_wrongly_removed = None
	if counts["content_words"] > 0:
		content_wrongly_removed = round(counts["content_words_missing"] / counts["content_words"], 4)

	return {
		"boilerplate_removed": boilerplate_removed,
		"content_wrongly_removed": content_wrongly_removed,
	}


def evaluate_cleanup_quality(matched_pages: list[dict]) -> dict:
	"""
	Input: matched_pages - the pairs from evaluation.match_pages.
	Output: a dict with "total" (counts and scores summed over all scored pages) and "pages"
	(source, number, counts and scores of each scored page).
	What it does: finds the boilerplate lines of each reference document, then scores every
	page of a document the engine returned.
	"""
	pages_lines_by_source = {}
	for matched_page in matched_pages:
		source = matched_page["source"]
		if source not in pages_lines_by_source:
			pages_lines_by_source[source] = []
		pages_lines_by_source[source].append(split_page_lines(matched_page["reference_text"]))

	repeated_keys_by_source = {}
	for source in pages_lines_by_source:
		repeated_keys_by_source[source] = find_repeated_keys(pages_lines_by_source[source])

	total_counts = {
		"boilerplate_lines": 0,
		"boilerplate_lines_removed": 0,
		"content_words": 0,
		"content_words_missing": 0,
	}
	page_results = []
	scored_pages = 0

	for matched_page in matched_pages:
		if not matched_page["document_returned"]:
			continue

		reference_lines = split_page_lines(matched_page["reference_text"])
		repeated_keys = repeated_keys_by_source[matched_page["source"]]
		boilerplate_lines, content_lines = split_boilerplate(reference_lines, repeated_keys)

		page_counts = count_page(boilerplate_lines, content_lines, matched_page["output_text"])
		for count_name in total_counts:
			total_counts[count_name] = total_counts[count_name] + page_counts[count_name]

		page_result = {"source": matched_page["source"], "number": matched_page["number"]}
		page_result.update(page_counts)
		page_result.update(compute_scores(page_counts))
		page_results.append(page_result)
		scored_pages = scored_pages + 1

	total_result = {"scored_pages": scored_pages}
	total_result.update(total_counts)
	total_result.update(compute_scores(total_counts))

	return {"total": total_result, "pages": page_results}
