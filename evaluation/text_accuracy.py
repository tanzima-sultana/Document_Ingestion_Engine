"""
evaluation/text_accuracy.py

Text accuracy: word recall, precision and F1, and word and character error rates (WER, CER).
Each engine is scored only on the pages of the documents it returned.
"""

from collections import Counter

from rapidfuzz.distance import Levenshtein


def normalize_text(text: str) -> str:
	"""
	Input: text - one page's text.
	Output: the text in lowercase, with punctuation turned into spaces and whitespace collapsed to single spaces.
	"""
	lowercase_text = text.lower()

	kept_characters = []
	for character in lowercase_text:
		if character.isalnum():
			kept_characters.append(character)
		else:
			kept_characters.append(" ")

	words = "".join(kept_characters).split()
	return " ".join(words)


def count_page(reference_text: str, output_text: str) -> dict:
	"""
	Input: reference_text and output_text - the reference and the engine's text of one page.
	Output: a dict of counts for the page: reference_words, output_words, matched_words,
	word_edits, reference_characters and character_edits.
	What it does: normalizes both texts, counts the words found in both (each word as often as
	it appears in both), and the word and character edit distances.
	"""
	normalized_reference = normalize_text(reference_text)
	normalized_output = normalize_text(output_text)

	reference_words = normalized_reference.split()
	output_words = normalized_output.split()

	reference_word_counts = Counter(reference_words)
	output_word_counts = Counter(output_words)
	matched_words = 0
	for word in reference_word_counts:
		matched_words = matched_words + min(reference_word_counts[word], output_word_counts[word])

	return {
		"reference_words": len(reference_words),
		"output_words": len(output_words),
		"matched_words": matched_words,
		"word_edits": Levenshtein.distance(reference_words, output_words),
		"reference_characters": len(normalized_reference),
		"character_edits": Levenshtein.distance(normalized_reference, normalized_output),
	}


def compute_scores(counts: dict) -> dict:
	"""
	Input: counts - the counts from count_page, or their sums over many pages.
	Output: a dict of recall, precision, f1, wer and cer, rounded to 4 places.
	A score that would divide by zero is None.
	"""
	recall = None
	if counts["reference_words"] > 0:
		recall = counts["matched_words"] / counts["reference_words"]

	precision = None
	if counts["output_words"] > 0:
		precision = counts["matched_words"] / counts["output_words"]

	f1 = None
	if recall is not None and precision is not None and recall + precision > 0:
		f1 = 2 * recall * precision / (recall + precision)

	wer = None
	if counts["reference_words"] > 0:
		wer = counts["word_edits"] / counts["reference_words"]

	cer = None
	if counts["reference_characters"] > 0:
		cer = counts["character_edits"] / counts["reference_characters"]

	scores = {}
	for name, value in [("recall", recall), ("precision", precision), ("f1", f1), ("wer", wer), ("cer", cer)]:
		if value is None:
			scores[name] = None
		else:
			scores[name] = round(value, 4)
	return scores


def evaluate_text_accuracy(matched_pages: list[dict]) -> dict:
	"""
	Input: matched_pages - the pairs from evaluation.match_pages.
	Output: a dict with "total" (counts and scores summed over all scored pages) and "pages"
	(source, number, counts and scores of each scored page).
	What it does: scores every page of a document the engine returned.
	"""
	total_counts = {
		"reference_words": 0,
		"output_words": 0,
		"matched_words": 0,
		"word_edits": 0,
		"reference_characters": 0,
		"character_edits": 0,
	}
	page_results = []
	scored_pages = 0

	for matched_page in matched_pages:
		if not matched_page["document_returned"]:
			continue

		page_counts = count_page(matched_page["reference_text"], matched_page["output_text"])
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
