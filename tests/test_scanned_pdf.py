"""
Tests for parsing/scanned_pdf.py on generated PDFs: image-only pages are read with OCR,
and a PDF with a text layer is skipped.
"""

import io
import tempfile
import unittest

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

import helpers
from doc_ingest.fetching.fetcher import RawDocument
from doc_ingest.parsing.parser import BaseParser
from doc_ingest.parsing.parser import get_parser_class
from doc_ingest.parsing.scanned_pdf import ScannedPdfParser
from doc_ingest.settings import ParseSettings


def make_scanned_pdf(page_words: list[str]) -> bytes:
	"""
	Input: page_words - the text to draw on each page; "" makes a blank page.
	Output: the bytes of a PDF whose pages are only images (no text layer), one per entry.
	"""
	font = ImageFont.load_default(size=60)
	page_images = []
	for words in page_words:
		page_image = Image.new("RGB", (1240, 1754), "white")
		if words != "":
			drawing = ImageDraw.Draw(page_image)
			drawing.text((100, 200), words, fill="black", font=font)
		page_images.append(page_image)

	pdf_buffer = io.BytesIO()
	page_images[0].save(pdf_buffer, format="PDF", save_all=True, append_images=page_images[1:])
	return pdf_buffer.getvalue()


class TestScannedPDF(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name

	def tearDown(self):
		self.temporary_folder.cleanup()

	def make_raw_document(self, file_name, content):
		"""Writes content to a file and returns a scanned_pdf RawDocument for it."""
		raw_path = helpers.write_file(self.root, file_name, content)
		return RawDocument("doc1", "scanned_pdf", raw_path, "source/" + file_name)

	def test_reads_scanned_pages_with_ocr(self):
		"""Image-only pages become page text through OCR; a blank page keeps its place."""
		pdf_bytes = make_scanned_pdf(["Quarterly finance report", "", "Third page summary"])
		parsed_document = ScannedPdfParser.parse(self.make_raw_document("scan.pdf", pdf_bytes))

		self.assertEqual(parsed_document.id, "doc1")
		self.assertEqual(parsed_document.type, "scanned_pdf")
		self.assertEqual(parsed_document.source, "source/scan.pdf")
		self.assertEqual(len(parsed_document.raw_texts), 3)
		self.assertIn("finance", parsed_document.raw_texts[0].lower())
		self.assertEqual(parsed_document.raw_texts[1].strip(), "")
		self.assertIn("summary", parsed_document.raw_texts[2].lower())

	def test_rejects_pdf_with_text_layer(self):
		"""A PDF with a text layer is not a scanned PDF and raises an error."""
		raw_document = self.make_raw_document("report.pdf", helpers.make_report_pdf("finance", 2))
		with self.assertRaises(ValueError):
			ScannedPdfParser.parse(raw_document)

	def test_text_pdf_counted_as_parse_failed(self):
		"""Through BaseParser, a PDF with a text layer is skipped and counted as parse_failed."""
		base_parser = BaseParser(ParseSettings(document_type="scanned_pdf"))
		raw_document = self.make_raw_document("report.pdf", helpers.make_report_pdf("finance", 2))
		self.assertIsNone(base_parser.parse_document(raw_document))
		self.assertEqual(base_parser.summary.parse_failed, 1)

	def test_registered_for_scanned_pdf(self):
		"""scanned_pdf uses ScannedPdfParser."""
		self.assertIs(get_parser_class("scanned_pdf"), ScannedPdfParser)


if __name__ == "__main__":
	unittest.main()
