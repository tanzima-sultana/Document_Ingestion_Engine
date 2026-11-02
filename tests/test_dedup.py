"""
Tests for processing/dedup.py: exact and near duplicate detection.
"""

import unittest

from doc_ingest.processing.dedup import Deduplicator
from doc_ingest.schema import Document
from doc_ingest.schema import Page


def make_document(doc_id: str, text: str) -> Document:
	"""Builds a minimal one-page Document for dedup tests."""
	return Document(id=doc_id, type="pdf", source="test", pages=[Page(number=1, text=text)])


def make_paragraphs(word: str) -> list[str]:
	"""Returns 40 lines of text about word."""
	lines = []
	for line_number in range(40):
		lines.append(f"Paragraph {line_number} discusses {word} results in detail for the quarter.")
	return lines


class TestDeduplicator(unittest.TestCase):

	def test_new_document_is_kept(self):
		"""A first document is new."""
		deduplicator = Deduplicator()
		self.assertTrue(deduplicator.add_if_new(make_document("a", "\n".join(make_paragraphs("finance")))))

	def test_exact_duplicate(self):
		"""The same id means the same raw bytes, so it is a duplicate."""
		deduplicator = Deduplicator()
		deduplicator.add_if_new(make_document("same-id", "one text here"))
		self.assertFalse(deduplicator.add_if_new(make_document("same-id", "other text")))

	def test_near_duplicate(self):
		"""One changed line out of 40 is a near duplicate."""
		deduplicator = Deduplicator()
		lines = make_paragraphs("finance")
		deduplicator.add_if_new(make_document("a", "\n".join(lines)))
		lines[5] = "This paragraph was rewritten completely by the editor."
		self.assertFalse(deduplicator.add_if_new(make_document("b", "\n".join(lines))))

	def test_different_document_is_kept(self):
		"""Different text is not a duplicate."""
		deduplicator = Deduplicator()
		deduplicator.add_if_new(make_document("a", "\n".join(make_paragraphs("finance"))))
		self.assertTrue(deduplicator.add_if_new(make_document("b", "\n".join(make_paragraphs("weather")))))

	def test_short_text_without_shingles(self):
		"""Text shorter than one shingle is kept, and only exact copies of it are duplicates."""
		deduplicator = Deduplicator()
		self.assertTrue(deduplicator.add_if_new(make_document("a", "too short")))
		self.assertTrue(deduplicator.add_if_new(make_document("b", "too short")))
		self.assertFalse(deduplicator.add_if_new(make_document("a", "too short")))


if __name__ == "__main__":
	unittest.main()
