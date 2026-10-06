"""
Tests for dedup.py: exact and near duplicate detection.
"""

import unittest

from doc_ingest.dedup import Deduplicator
from doc_ingest.schema import Document
from doc_ingest.schema import Metadata


def make_document(doc_id: str, text: str, content_hash: str) -> Document:
	"""Builds a minimal Document for dedup tests."""
	metadata = Metadata(source="test", file_size_bytes=1, content_hash=content_hash)
	return Document(id=doc_id, type="pdf", text=text, metadata=metadata)


def make_paragraphs(word: str) -> list[str]:
	"""Returns 40 lines of text about word."""
	lines = []
	for line_number in range(40):
		lines.append(f"Paragraph {line_number} discusses {word} results in detail for the quarter.")
	return lines


class TestDeduplicator(unittest.TestCase):

	def test_new_document_is_kept(self):
		"""A first document is new and gets a MinHash signature."""
		deduplicator = Deduplicator()
		document = make_document("a", "\n".join(make_paragraphs("finance")), "hash-a")
		self.assertTrue(deduplicator.add_if_new(document))
		self.assertIsNotNone(document.metadata.minhash_signature)

	def test_exact_duplicate(self):
		"""Same content hash is a duplicate."""
		deduplicator = Deduplicator()
		deduplicator.add_if_new(make_document("a", "one text here", "same-hash"))
		self.assertFalse(deduplicator.add_if_new(make_document("b", "other text", "same-hash")))

	def test_near_duplicate(self):
		"""One changed line out of 40 is a near duplicate."""
		deduplicator = Deduplicator()
		lines = make_paragraphs("finance")
		deduplicator.add_if_new(make_document("a", "\n".join(lines), "hash-a"))
		lines[5] = "This paragraph was rewritten completely by the editor."
		self.assertFalse(deduplicator.add_if_new(make_document("b", "\n".join(lines), "hash-b")))

	def test_different_document_is_kept(self):
		"""Different text is not a duplicate."""
		deduplicator = Deduplicator()
		deduplicator.add_if_new(make_document("a", "\n".join(make_paragraphs("finance")), "hash-a"))
		self.assertTrue(deduplicator.add_if_new(make_document("b", "\n".join(make_paragraphs("weather")), "hash-b")))

	def test_cached_documents_count(self):
		"""Documents added with add() are checked against later ones."""
		deduplicator = Deduplicator()
		deduplicator.add(make_document("a", "\n".join(make_paragraphs("finance")), "hash-a"))
		self.assertFalse(deduplicator.add_if_new(make_document("b", "\n".join(make_paragraphs("finance")), "hash-b")))

	def test_short_text_without_shingles(self):
		"""Text shorter than one shingle is kept without a signature."""
		deduplicator = Deduplicator()
		document = make_document("a", "too short", "hash-a")
		self.assertTrue(deduplicator.add_if_new(document))
		self.assertIsNone(document.metadata.minhash_signature)


if __name__ == "__main__":
	unittest.main()
