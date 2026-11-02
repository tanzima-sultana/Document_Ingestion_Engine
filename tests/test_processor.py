"""
Tests for processing/processor.py: from a ParsedDocument to the final Document.
"""

import unittest
import unittest.mock

from doc_ingest.parsing.parser import ParsedDocument
from doc_ingest.processing.processor import DocumentProcessor
from doc_ingest.settings import ProcessSettings


def make_parsed_document(doc_id: str, page_texts: list[str], title: str | None) -> ParsedDocument:
	"""Builds a ParsedDocument with the given raw page texts."""
	return ParsedDocument(doc_id, "pdf", "test.pdf", title, page_texts)


class TestDocumentProcessor(unittest.TestCase):

	def setUp(self):
		self.processor = DocumentProcessor(ProcessSettings())

	def test_cleans_pages_and_title(self):
		"""Headers go, an emptied page keeps its place, and the title is tidied."""
		parsed_document = make_parsed_document("a", ["Header\nOne", "Header", "Header\nThree", "Header\nFour"], "  My Title ")
		document = self.processor.process_document(parsed_document)

		page_texts = []
		page_numbers = []
		for page in document.pages:
			page_texts.append(page.text)
			page_numbers.append(page.number)
		self.assertEqual(page_texts, ["One", "", "Three", "Four"])
		self.assertEqual(page_numbers, [1, 2, 3, 4])
		self.assertEqual(document.title, "My Title")
		self.assertEqual(document.text, "One\n\nThree\n\nFour")
		self.assertEqual(self.processor.summary.total_processed, 1)
		self.assertEqual(self.processor.summary.cleanup_success, 1)
		self.assertEqual(self.processor.summary.pages, 4)

	def test_no_text_is_counted(self):
		"""A document with only whitespace is skipped as no_text."""
		self.assertIsNone(self.processor.process_document(make_parsed_document("a", ["   ", "\n"], None)))
		self.assertEqual(self.processor.summary.no_text, 1)

	def test_duplicate_is_counted(self):
		"""A second copy is dropped and counted as a duplicate."""
		self.assertIsNotNone(self.processor.process_document(make_parsed_document("a", ["same text"], None)))
		self.assertIsNone(self.processor.process_document(make_parsed_document("a", ["same text"], None)))
		self.assertEqual(self.processor.summary.duplicates, 1)

	def test_cleanup_failure_skips_one_document(self):
		"""A cleanup error skips that document instead of stopping the run."""
		with unittest.mock.patch("doc_ingest.processing.processor.clean_page_texts", side_effect=ValueError("bad")):
			with self.assertLogs("doc_ingest", level="WARNING"):
				self.assertIsNone(self.processor.process_document(make_parsed_document("a", ["text"], None)))
		self.assertEqual(self.processor.summary.cleanup_failed, 1)


if __name__ == "__main__":
	unittest.main()
