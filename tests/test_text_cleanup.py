"""
Tests for text_cleanup.py, on plain page strings so no PDF is needed.
"""

import unittest

from doc_ingest.text_cleanup import clean_text


class TestCleanText(unittest.TestCase):

	def test_removes_header_and_footer(self):
		"""A running header and a "Page n of m" footer are removed."""
		page_texts = []
		for page_number in range(1, 5):
			page_texts.append(f"ACME Report\nBody of page {page_number}.\nPage {page_number} of 4")
		cleaned_text = clean_text(page_texts)
		self.assertNotIn("ACME Report", cleaned_text)
		self.assertNotIn("Page 1 of 4", cleaned_text)
		self.assertIn("Body of page 1.", cleaned_text)
		self.assertIn("Body of page 4.", cleaned_text)

	def test_short_documents_keep_repeated_lines(self):
		"""Documents under 3 pages are not checked for headers/footers."""
		cleaned_text = clean_text(["Title\nOne", "Title\nTwo"])
		self.assertEqual(cleaned_text.count("Title"), 2)

	def test_collapses_whitespace_and_blank_lines(self):
		"""Spaces, tabs and repeated blank lines are collapsed."""
		cleaned_text = clean_text(["a   b\t\tc  d\n\n\n\nnext"])
		self.assertEqual(cleaned_text, "a b c d\n\nnext")

	def test_removes_icon_characters(self):
		"""Private-use icon characters are removed."""
		cleaned_text = clean_text([" +84 123  mail"])
		self.assertEqual(cleaned_text, "+84 123 mail")

	def test_joins_pages_with_blank_line(self):
		"""Pages are joined with one blank line; empty pages are dropped."""
		cleaned_text = clean_text(["first", "", "second"])
		self.assertEqual(cleaned_text, "first\n\nsecond")


if __name__ == "__main__":
	unittest.main()
