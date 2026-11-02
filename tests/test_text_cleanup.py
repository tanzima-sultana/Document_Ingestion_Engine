"""
Tests for processing/text_cleanup.py, on plain page strings so no PDF is needed.
"""

import unittest

from doc_ingest.processing.text_cleanup import clean_page_texts
from doc_ingest.processing.text_cleanup import clean_property_text
from doc_ingest.error import fix_broken_characters


class TestCleanPageTexts(unittest.TestCase):

	def test_removes_header_and_footer(self):
		"""A running header and a "Page n of m" footer are removed from every page."""
		page_texts = []
		for page_number in range(1, 5):
			page_texts.append(f"ACME Report\nBody of page {page_number}.\nPage {page_number} of 4")
		cleaned_pages = clean_page_texts(page_texts)
		self.assertEqual(cleaned_pages, ["Body of page 1.", "Body of page 2.", "Body of page 3.", "Body of page 4."])

	def test_short_documents_keep_repeated_lines(self):
		"""Documents under 3 pages are not checked for headers/footers."""
		cleaned_pages = clean_page_texts(["Title\nOne", "Title\nTwo"])
		self.assertEqual(cleaned_pages, ["Title\nOne", "Title\nTwo"])

	def test_collapses_whitespace_and_blank_lines(self):
		"""Spaces, tabs and repeated blank lines are collapsed."""
		cleaned_pages = clean_page_texts(["a   b\t\tc  d\n\n\n\nnext"])
		self.assertEqual(cleaned_pages, ["a b c d\n\nnext"])

	def test_removes_icon_characters(self):
		"""Private-use icon characters are removed."""
		cleaned_pages = clean_page_texts(["\ue001 +84 123 \ue002 mail"])
		self.assertEqual(cleaned_pages, ["+84 123 mail"])

	def test_keeps_page_positions(self):
		"""An empty page stays as "", so the pages after it keep their positions."""
		cleaned_pages = clean_page_texts(["first", "", "third"])
		self.assertEqual(cleaned_pages, ["first", "", "third"])

	def test_page_left_empty_by_cleanup_stays(self):
		"""A page holding only a header becomes "" instead of being dropped."""
		page_texts = ["Header\nOne", "Header", "Header\nThree", "Header\nFour"]
		cleaned_pages = clean_page_texts(page_texts)
		self.assertEqual(cleaned_pages, ["One", "", "Three", "Four"])


class TestCleanPropertyText(unittest.TestCase):

	def test_clean_property_text(self):
		"""Spaces and null characters are stripped; a blank value is missing."""
		self.assertEqual(clean_property_text(" My Title\x00 "), "My Title")
		self.assertIsNone(clean_property_text("   "))
		self.assertIsNone(clean_property_text(None))


class TestFixBrokenCharacters(unittest.TestCase):

	def test_fix_broken_characters(self):
		"""A split character is joined back; a lone half is replaced."""
		self.assertEqual(fix_broken_characters("\ud835\udc00"), "\U0001d400")
		self.assertEqual(fix_broken_characters("a\ud835b"), "a\ufffdb")


if __name__ == "__main__":
	unittest.main()
