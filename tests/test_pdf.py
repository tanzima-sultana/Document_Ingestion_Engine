"""
Tests for parsers/pdf.py, parser.py and metadata.py on generated PDFs.
"""

import hashlib
import tempfile
import unittest

import helpers
from doc_ingest.metadata import extract_metadata
from doc_ingest.parser import parse_document
from doc_ingest.parsers.pdf import PDFParser
from doc_ingest.raw_data import RawData
from doc_ingest.schema import DocumentType


class TestPDF(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name

	def tearDown(self):
		self.temporary_folder.cleanup()

	def make_raw_data(self, file_name, content):
		"""Writes content to a file and returns a RawData for it."""
		raw_path = helpers.write_file(self.root, file_name, content)
		return RawData("doc1", "pdf", raw_path, "source/" + file_name)

	def test_parses_pdf(self):
		"""A text PDF becomes a Document with cleaned text and metadata."""
		raw_data = self.make_raw_data("report.pdf", helpers.make_report_pdf("finance", 4))
		document = PDFParser().parse(raw_data)
		self.assertEqual(document.id, "doc1")
		self.assertEqual(document.type, DocumentType.PDF)
		self.assertIn("talks about finance", document.text)
		self.assertNotIn("Quarterly Report", document.text)
		self.assertEqual(document.metadata.title, "finance report")
		self.assertEqual(document.metadata.author, "Tester")
		self.assertEqual(document.metadata.source, "source/report.pdf")

	def test_rejects_non_pdf(self):
		"""A file that is not a PDF raises ValueError."""
		raw_data = self.make_raw_data("fake.pdf", b"this is not a pdf")
		with self.assertRaises(ValueError):
			PDFParser().parse(raw_data)

	def test_rejects_encrypted_pdf(self):
		"""An encrypted PDF raises ValueError."""
		raw_data = self.make_raw_data("locked.pdf", helpers.make_encrypted_pdf())
		with self.assertRaises(ValueError):
			PDFParser().parse(raw_data)

	def test_parse_document_returns_none_on_failure(self):
		"""parse_document returns (doc_id, None) instead of raising."""
		raw_data = self.make_raw_data("fake.pdf", b"this is not a pdf")
		doc_id, document = parse_document(raw_data)
		self.assertEqual(doc_id, "doc1")
		self.assertIsNone(document)

	def test_parse_document_unknown_type(self):
		"""A type with no parser returns None."""
		raw_path = helpers.write_file(self.root, "a.docx", b"PK")
		doc_id, document = parse_document(RawData("doc2", "docx", raw_path, "a.docx"))
		self.assertIsNone(document)


class TestMetadata(unittest.TestCase):

	def test_pdf_metadata(self):
		"""Size, hash, title, author and date are filled in."""
		pdf_bytes = helpers.make_pdf([["hello"]], {"Title": " My Title ", "Author": "Jane", "CreationDate": "D:20240301101500+00'00'"})
		raw_data = RawData("doc1", "pdf", "raw/doc1.pdf", "data/a.pdf")
		metadata = extract_metadata(raw_data, pdf_bytes)
		self.assertEqual(metadata.source, "data/a.pdf")
		self.assertEqual(metadata.file_size_bytes, len(pdf_bytes))
		self.assertEqual(metadata.content_hash, hashlib.sha256(pdf_bytes).hexdigest())
		self.assertEqual(metadata.title, "My Title")
		self.assertEqual(metadata.author, "Jane")
		self.assertEqual(metadata.creation_date, "2024-03-01T10:15:00+00:00")
		self.assertIsNone(metadata.minhash_signature)

	def test_bad_date_is_none(self):
		"""A date pypdf cannot parse becomes None; the rest is kept."""
		pdf_bytes = helpers.make_pdf([["hello"]], {"Author": "Bob", "CreationDate": "garbage"})
		metadata = extract_metadata(RawData("doc1", "pdf", "raw/doc1.pdf", "a.pdf"), pdf_bytes)
		self.assertEqual(metadata.author, "Bob")
		self.assertIsNone(metadata.creation_date)

	def test_non_pdf_has_no_properties(self):
		"""Types without a property reader keep title/author/date as None."""
		metadata = extract_metadata(RawData("doc1", "txt", "raw/doc1.txt", "a.txt"), b"hello")
		self.assertEqual(metadata.file_size_bytes, 5)
		self.assertIsNone(metadata.title)


if __name__ == "__main__":
	unittest.main()
