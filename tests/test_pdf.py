"""
Tests for parsing/pdf.py and parsing/parser.py on generated PDFs.
"""

import tempfile
import unittest

import helpers
from doc_ingest.fetching.fetcher import RawDocument
from doc_ingest.parsing.parser import BaseParser
from doc_ingest.parsing.parser import ParsedDocument
from doc_ingest.parsing.parser import get_parser_class
from doc_ingest.parsing.pdf import PdfParser
from doc_ingest.settings import ParseSettings


class TestPDF(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name

	def tearDown(self):
		self.temporary_folder.cleanup()

	def make_raw_document(self, file_name, content):
		"""Writes content to a file and returns a RawDocument for it."""
		raw_path = helpers.write_file(self.root, file_name, content)
		return RawDocument("doc1", "pdf", raw_path, "source/" + file_name)

	def test_parses_pdf(self):
		"""A text PDF becomes a ParsedDocument with raw page text; headers are still there."""
		raw_document = self.make_raw_document("report.pdf", helpers.make_report_pdf("finance", 4))
		parsed_document = PdfParser.parse(raw_document)
		self.assertEqual(parsed_document.id, "doc1")
		self.assertEqual(parsed_document.type, "pdf")
		self.assertIn("talks about finance", parsed_document.raw_texts[0])
		self.assertIn("Quarterly Report", parsed_document.raw_texts[0])
		self.assertEqual(parsed_document.title, "finance report")
		self.assertEqual(parsed_document.source, "source/report.pdf")
		self.assertEqual(len(parsed_document.raw_texts), 4)

	def test_empty_page_keeps_its_place(self):
		"""An empty page stays in raw_texts, so the pages after it keep their positions."""
		pdf_bytes = helpers.make_pdf([["first words"], [], ["third words"]], {})
		parsed_document = PdfParser.parse(self.make_raw_document("a.pdf", pdf_bytes))
		self.assertEqual(len(parsed_document.raw_texts), 3)
		self.assertIn("first words", parsed_document.raw_texts[0])
		self.assertEqual(parsed_document.raw_texts[1].strip(), "")
		self.assertIn("third words", parsed_document.raw_texts[2])

	def test_rejects_non_pdf(self):
		"""A file that is not a PDF raises an error."""
		raw_document = self.make_raw_document("fake.pdf", b"this is not a pdf")
		with self.assertRaises(Exception):
			PdfParser.parse(raw_document)

	def test_parses_encrypted_pdf(self):
		"""An encrypted PDF that opens without a password is parsed, like in LangChain."""
		raw_document = self.make_raw_document("locked.pdf", helpers.make_encrypted_pdf())
		parsed_document = PdfParser.parse(raw_document)
		self.assertEqual(parsed_document.id, "doc1")
		self.assertEqual(len(parsed_document.raw_texts), 1)

	def test_parse_document_returns_parsed_document(self):
		"""parse_document returns a ParsedDocument and counts it."""
		raw_document = self.make_raw_document("a.pdf", helpers.make_pdf([["hello"]], {}))
		parser = BaseParser(ParseSettings(document_type="pdf", timeout_seconds=30))
		parsed_document = parser.parse_document(raw_document)
		self.assertIsInstance(parsed_document, ParsedDocument)
		self.assertEqual(parsed_document.id, "doc1")
		self.assertEqual(parser.summary.total_parsed, 1)
		self.assertEqual(parser.summary.parse_success, 1)

	def test_parse_document_returns_none_on_failure(self):
		"""On failure parse_document returns None; nothing is raised."""
		raw_document = self.make_raw_document("fake.pdf", b"this is not a pdf")
		parser = BaseParser(ParseSettings(document_type="pdf"))
		self.assertIsNone(parser.parse_document(raw_document))
		self.assertEqual(parser.summary.parse_failed, 1)

	def test_get_parser_class(self):
		"""The class comes from the document type; a type with no parser is refused."""
		self.assertIs(get_parser_class("pdf"), PdfParser)
		with self.assertRaises(ValueError):
			get_parser_class("docx")

	def test_unknown_type_gives_no_document(self):
		"""A type with no parser returns None; nothing is raised."""
		raw_path = helpers.write_file(self.root, "a.pdf", helpers.make_pdf([["hello"]], {}))
		parser = BaseParser(ParseSettings(document_type="docx"))
		self.assertIsNone(parser.parse_document(RawDocument("doc2", "docx", raw_path, raw_path)))

	def test_pdf_title(self):
		"""The title is read from the PDF."""
		pdf_bytes = helpers.make_pdf([["hello"]], {"Title": "My Title"})
		parsed_document = PdfParser.parse(self.make_raw_document("a.pdf", pdf_bytes))
		self.assertEqual(parsed_document.title, "My Title")


if __name__ == "__main__":
	unittest.main()
