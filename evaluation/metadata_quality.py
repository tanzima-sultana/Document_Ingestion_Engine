"""
evaluation/metadata_quality.py

Metadata and page numbers: checks that each returned document's source file exists, that its page count
matches the file's real page count, that its page numbers run 1..n with no gaps, and that each page's text
best matches the reference text of the same page (the citation check). Title has no ground truth, so only
how often it is empty is reported.
"""

import json
import os
from collections import Counter

import pypdfium2

from text_accuracy import normalize_text


def read_real_page_count(source: str) -> int | None:
	"""
	Input: source - the path of a returned document's file.
	Output: the file's real page count, or None if the file is missing, cannot be read, or is of a type
	with no page counter here yet.
	What it does: a PDF is opened with pypdfium2 and its pages are counted.
	"""
	if not os.path.isfile(source):
		return None

	if not source.lower().endswith(".pdf"):
		return None

	try:
		pdf_document = pypdfium2.PdfDocument(source)
	except Exception:
		return None

	try:
		real_page_count = len(pdf_document)
	finally:
		pdf_document.close()

	return real_page_count


def score_word_overlap(first_text: str, second_text: str) -> float:
	"""
	Input: two page texts.
	Output: the word overlap F1 of the two texts, from 0 (no shared words) to 1 (the same words).
	What it does: normalizes both texts and counts the words found in both (each word as often as it
	appears in both), then combines the shares of each text that are shared.
	"""
	first_words = normalize_text(first_text).split()
	second_words = normalize_text(second_text).split()
	if len(first_words) == 0 or len(second_words) == 0:
		return 0.0

	first_word_counts = Counter(first_words)
	second_word_counts = Counter(second_words)
	shared_words = 0
	for word in first_word_counts:
		shared_words = shared_words + min(first_word_counts[word], second_word_counts[word])

	if shared_words == 0:
		return 0.0

	first_share = shared_words / len(first_words)
	second_share = shared_words / len(second_words)
	return 2 * first_share * second_share / (first_share + second_share)


def check_citations(output_pages: list[dict], reference_pages: dict) -> dict:
	"""
	Input: output_pages - one returned document's pages, each with "number" and "text";
	reference_pages - the same document's reference pages, page number -> text.
	Output: a dict of counts: pages_checked, pages_best_match_same_number, pages_best_match_other_number,
	pages_no_match and pages_empty.
	What it does: compares each page that has text with every reference page of the document. The page passes
	if the reference page with the same number is among the best matches. A page sharing no words with any
	reference page has no match. A page with no text is counted as empty and not checked.
	"""
	counts = {
		"pages_checked": 0,
		"pages_best_match_same_number": 0,
		"pages_best_match_other_number": 0,
		"pages_no_match": 0,
		"pages_empty": 0,
	}

	for output_page in output_pages:
		if normalize_text(output_page["text"]) == "":
			counts["pages_empty"] = counts["pages_empty"] + 1
			continue

		counts["pages_checked"] = counts["pages_checked"] + 1

		best_score = 0.0
		best_page_numbers = []
		for reference_page_number in reference_pages:
			overlap_score = score_word_overlap(output_page["text"], reference_pages[reference_page_number])
			if overlap_score > best_score:
				best_score = overlap_score
				best_page_numbers = [reference_page_number]
			elif overlap_score == best_score and overlap_score > 0:
				best_page_numbers.append(reference_page_number)

		if best_score == 0:
			counts["pages_no_match"] = counts["pages_no_match"] + 1
		elif output_page["number"] in best_page_numbers:
			counts["pages_best_match_same_number"] = counts["pages_best_match_same_number"] + 1
		else:
			counts["pages_best_match_other_number"] = counts["pages_best_match_other_number"] + 1

	return counts


def check_document(document_values: dict, reference_documents: dict) -> dict:
	"""
	Input: document_values - one returned document as saved in documents.jsonl;
	reference_documents - source -> {page number -> page text}.
	Output: a dict with the document's checks: source_exists, page_count, real_page_count, page_count_matches,
	page_numbers_in_order, has_title_field, title_empty, in_reference and the citation counts.
	page_count_matches is None when the real page count could not be read.
	"""
	source = document_values["source"]
	output_pages = document_values["pages"]

	real_page_count = read_real_page_count(source)
	page_count_matches = None
	if real_page_count is not None:
		page_count_matches = len(output_pages) == real_page_count

	page_numbers_in_order = True
	for page_position in range(len(output_pages)):
		if output_pages[page_position]["number"] != page_position + 1:
			page_numbers_in_order = False
			break

	has_title_field = "title" in document_values
	title_empty = True
	if has_title_field and document_values["title"] is not None and str(document_values["title"]).strip() != "":
		title_empty = False

	in_reference = source in reference_documents
	citation_counts = {
		"pages_checked": 0,
		"pages_best_match_same_number": 0,
		"pages_best_match_other_number": 0,
		"pages_no_match": 0,
		"pages_empty": 0,
	}
	if in_reference:
		citation_counts = check_citations(output_pages, reference_documents[source])

	document_result = {
		"source": source,
		"source_exists": os.path.isfile(source),
		"page_count": len(output_pages),
		"real_page_count": real_page_count,
		"page_count_matches": page_count_matches,
		"page_numbers_in_order": page_numbers_in_order,
		"has_title_field": has_title_field,
		"title_empty": title_empty,
		"in_reference": in_reference,
	}
	document_result.update(citation_counts)
	return document_result


def compute_rate(count: int, total: int) -> float | None:
	"""
	Input: count and total.
	Output: count / total rounded to 4 places, or None if total is 0.
	"""
	if total == 0:
		return None
	return round(count / total, 4)


def evaluate_metadata_quality(documents_path: str, reference_documents: dict) -> dict:
	"""
	Input: documents_path - the engine's documents.jsonl; reference_documents - source -> {page number -> page text}.
	Output: a dict with "total" (counts and rates over all returned documents) and "documents" (each document's checks).
	What it does: checks every document the engine returned.
	"""
	total_counts = {
		"documents": 0,
		"sources_exist": 0,
		"sources_missing": 0,
		"page_counts_checked": 0,
		"page_counts_match": 0,
		"page_counts_differ": 0,
		"page_counts_not_checked": 0,
		"page_numbers_in_order": 0,
		"page_numbers_not_in_order": 0,
		"documents_without_title_field": 0,
		"titles_empty": 0,
		"documents_in_reference": 0,
		"pages_checked": 0,
		"pages_best_match_same_number": 0,
		"pages_best_match_other_number": 0,
		"pages_no_match": 0,
		"pages_empty": 0,
	}
	document_results = []

	with open(documents_path, encoding="utf-8") as documents_file:
		for line in documents_file:
			if line.strip() == "":
				continue
			document_values = json.loads(line)
			document_result = check_document(document_values, reference_documents)
			document_results.append(document_result)

			total_counts["documents"] = total_counts["documents"] + 1

			if document_result["source_exists"]:
				total_counts["sources_exist"] = total_counts["sources_exist"] + 1
			else:
				total_counts["sources_missing"] = total_counts["sources_missing"] + 1

			if document_result["page_count_matches"] is None:
				total_counts["page_counts_not_checked"] = total_counts["page_counts_not_checked"] + 1
			else:
				total_counts["page_counts_checked"] = total_counts["page_counts_checked"] + 1
				if document_result["page_count_matches"]:
					total_counts["page_counts_match"] = total_counts["page_counts_match"] + 1
				else:
					total_counts["page_counts_differ"] = total_counts["page_counts_differ"] + 1

			if document_result["page_numbers_in_order"]:
				total_counts["page_numbers_in_order"] = total_counts["page_numbers_in_order"] + 1
			else:
				total_counts["page_numbers_not_in_order"] = total_counts["page_numbers_not_in_order"] + 1

			if not document_result["has_title_field"]:
				total_counts["documents_without_title_field"] = total_counts["documents_without_title_field"] + 1
			if document_result["title_empty"]:
				total_counts["titles_empty"] = total_counts["titles_empty"] + 1

			if document_result["in_reference"]:
				total_counts["documents_in_reference"] = total_counts["documents_in_reference"] + 1

			for count_name in ["pages_checked", "pages_best_match_same_number", "pages_best_match_other_number", "pages_no_match", "pages_empty"]:
				total_counts[count_name] = total_counts[count_name] + document_result[count_name]

	total_result = dict(total_counts)
	total_result["source_exists_rate"] = compute_rate(total_counts["sources_exist"], total_counts["documents"])
	total_result["page_count_match_rate"] = compute_rate(total_counts["page_counts_match"], total_counts["page_counts_checked"])
	total_result["page_numbers_in_order_rate"] = compute_rate(total_counts["page_numbers_in_order"], total_counts["documents"])
	total_result["citation_accuracy"] = compute_rate(total_counts["pages_best_match_same_number"], total_counts["pages_checked"])
	total_result["title_empty_rate"] = compute_rate(total_counts["titles_empty"], total_counts["documents"])

	return {"total": total_result, "documents": document_results}
