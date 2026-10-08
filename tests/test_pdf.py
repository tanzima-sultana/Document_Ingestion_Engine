"""
Tests for parsers/pdf.py, parser.py and metadata.py on generated PDFs.
"""

import hashlib
import importlib.util
import tempfile
import unittest

import helpers
from doc_ingest.metadata import extract_metadata
from doc_ingest.parser import parse_document
from doc_ingest.parsers.pdf import PyPdfParser
from doc_ingest.parsers.pdf import PyPdfium2Parser
from doc_ingest.parsers.pdf import parse_pdf_date
from doc_ingest.settings import ParserSettings
from doc_ingest.raw_data import RawData
from doc_ingest.schema import DocumentType


class FakePage:
	def __init__(self, text):
		self.text = text

	def extract_text(self):
		"""Returns the page text, or raises it if it is an error."""
		if isinstance(self.text, Exception):
			raise self.text
		return self.text


class FakeReader:
	def __init__(self, page_texts):
		self.pages = []
		for page_text in page_texts:
			self.pages.append(FakePage(page_text))


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
		document = PyPdfParser().parse(raw_data)
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
			PyPdfParser().parse(raw_data)

	def test_rejects_encrypted_pdf(self):
		"""An encrypted PDF raises ValueError."""
		raw_data = self.make_raw_data("locked.pdf", helpers.make_encrypted_pdf())
		with self.assertRaises(ValueError):
			PyPdfParser().parse(raw_data)

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

	def test_pdf_properties(self):
		"""Title, author and creation date are read from the PDF."""
		pdf_bytes = helpers.make_pdf([["hello"]], {"Title": " My Title ", "Author": "Jane", "CreationDate": "D:20240301101500+00'00'"})
		document = PyPdfParser().parse(self.make_raw_data("a.pdf", pdf_bytes))
		self.assertEqual(document.metadata.title, "My Title")
		self.assertEqual(document.metadata.author, "Jane")
		self.assertEqual(document.metadata.creation_date, "2024-03-01T10:15:00+00:00")

	def test_bad_date_is_none(self):
		"""A date pypdf cannot parse becomes None; the rest is kept."""
		pdf_bytes = helpers.make_pdf([["hello"]], {"Author": "Bob", "CreationDate": "garbage"})
		with self.assertLogs("doc_ingest", level="WARNING"):
			document = PyPdfParser().parse(self.make_raw_data("a.pdf", pdf_bytes))
		self.assertEqual(document.metadata.author, "Bob")
		self.assertIsNone(document.metadata.creation_date)

	def test_bad_page_does_not_lose_document(self):
		"""A page that fails to extract is given as an empty page."""
		with self.assertLogs("doc_ingest", level="WARNING"):
			page_texts = PyPdfParser().extract_page_texts(FakeReader(["good page", ValueError("broken")]))
		self.assertEqual(page_texts, ["good page", ""])


PYPDFIUM2_IS_INSTALLED = importlib.util.find_spec("pypdfium2") is not None


@unittest.skipUnless(PYPDFIUM2_IS_INSTALLED, "pypdfium2 is not installed")
class TestPyPdfium2(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name

	def tearDown(self):
		self.temporary_folder.cleanup()

	def make_raw_data(self, file_name, content):
		"""Writes content to a file and returns a RawData for it."""
		raw_path = helpers.write_file(self.root, file_name, content)
		return RawData("doc1", "pdf", raw_path, "source/" + file_name)

	def test_same_metadata_as_pypdf(self):
		"""Both parsers give the same metadata (apart from the parser name) and the same cleaned text."""
		pdf_bytes = helpers.make_pdf([["hello"]], {"Title": " My Title ", "Author": "Jane", "CreationDate": "D:20240301101500+00'00'"})
		raw_data = self.make_raw_data("a.pdf", pdf_bytes)
		pypdf_document = PyPdfParser().parse(raw_data)
		pypdfium2_document = PyPdfium2Parser().parse(raw_data)

		self.assertEqual(pypdf_document.metadata.parser, "pypdf")
		self.assertEqual(pypdfium2_document.metadata.parser, "pypdfium2")
		pypdf_metadata = pypdf_document.metadata.model_dump(exclude={"parser"})
		pypdfium2_metadata = pypdfium2_document.metadata.model_dump(exclude={"parser"})
		self.assertEqual(pypdf_metadata, pypdfium2_metadata)
		self.assertEqual(pypdf_document.text, pypdfium2_document.text)

	def test_parses_report(self):
		"""A multi-page report is parsed and cleaned like with pypdf."""
		raw_data = self.make_raw_data("report.pdf", helpers.make_report_pdf("finance", 4))
		document = PyPdfium2Parser().parse(raw_data)
		self.assertEqual(document.id, "doc1")
		self.assertEqual(document.type, DocumentType.PDF)
		self.assertIn("talks about finance", document.text)
		self.assertNotIn("Quarterly Report", document.text)
		self.assertEqual(document.metadata.page_count, 4)

	def test_rejects_non_pdf(self):
		"""A file that is not a PDF raises ValueError."""
		raw_data = self.make_raw_data("fake.pdf", b"this is not a pdf")
		with self.assertRaises(ValueError):
			PyPdfium2Parser().parse(raw_data)

	def test_rejects_encrypted_pdf(self):
		"""An encrypted PDF raises ValueError, even one that opens without a password."""
		raw_data = self.make_raw_data("locked.pdf", helpers.make_encrypted_pdf())
		with self.assertRaisesRegex(ValueError, "encrypted PDF"):
			PyPdfium2Parser().parse(raw_data)

	def test_bad_date_is_none(self):
		"""A date that cannot be parsed becomes None; the rest is kept."""
		pdf_bytes = helpers.make_pdf([["hello"]], {"Author": "Bob", "CreationDate": "garbage"})
		with self.assertLogs("doc_ingest", level="WARNING"):
			document = PyPdfium2Parser().parse(self.make_raw_data("a.pdf", pdf_bytes))
		self.assertEqual(document.metadata.author, "Bob")
		self.assertIsNone(document.metadata.creation_date)

	def test_parse_document_uses_chosen_parser(self):
		"""parse_document uses the PDF parser chosen in ParserSettings."""
		raw_data = self.make_raw_data("a.pdf", helpers.make_pdf([["hello"]], {}))
		doc_id, document = parse_document(raw_data, parser_settings=ParserSettings(pdf_parser="pypdfium2"))
		self.assertEqual(document.metadata.parser, "pypdfium2")


class TestParsePdfDate(unittest.TestCase):

	def test_date_formats(self):
		"""PDF dates become the same datetimes pypdf gives."""
		self.assertEqual(parse_pdf_date("D:20240301101500+00'00'").isoformat(), "2024-03-01T10:15:00+00:00")
		self.assertEqual(parse_pdf_date("D:20200129160534Z").isoformat(), "2020-01-29T16:05:34+00:00")
		self.assertEqual(parse_pdf_date("D:20240301101500+05'30'").isoformat(), "2024-03-01T10:15:00+05:30")
		self.assertEqual(parse_pdf_date("D:20240301").isoformat(), "2024-03-01T00:00:00")
		self.assertIsNone(parse_pdf_date(""))
		self.assertIsNone(parse_pdf_date(None))
		with self.assertRaises(ValueError):
			parse_pdf_date("garbage")


class TestMetadata(unittest.TestCase):

	def test_generic_metadata(self):
		"""Source, size and hash are set; properties are left for the parser."""
		pdf_bytes = helpers.make_pdf([["hello"]], {"Title": "My Title", "Author": "Jane"})
		raw_data = RawData("doc1", "pdf", "raw/doc1.pdf", "data/a.pdf")
		metadata = extract_metadata(raw_data, pdf_bytes)
		self.assertEqual(metadata.source, "data/a.pdf")
		self.assertEqual(metadata.file_size_bytes, len(pdf_bytes))
		self.assertEqual(metadata.content_hash, hashlib.sha256(pdf_bytes).hexdigest())
		self.assertIsNone(metadata.title)
		self.assertIsNone(metadata.author)
		self.assertIsNone(metadata.creation_date)
		self.assertIsNone(metadata.minhash_signature)


if __name__ == "__main__":
	unittest.main()
