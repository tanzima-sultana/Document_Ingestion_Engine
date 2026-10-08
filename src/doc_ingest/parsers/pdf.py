"""
pdf.py

Implements Parser for PDF documents. Opens the document's raw bytes
with pypdf, extracts each page's text and cleans it (text_cleanup.py),
builds the generic metadata (metadata.py), fills in the PDF's title,
author and creation date from the same reader, and builds a Document.
"""

import io
import logging

import pypdf

from doc_ingest.parser import Parser
from doc_ingest.schema import Document
from doc_ingest.schema import DocumentType
from doc_ingest.schema import Metadata
from doc_ingest.raw_data import RawData
from doc_ingest.metadata import extract_metadata
from doc_ingest.metadata import clean_property_text
from doc_ingest.metadata import format_creation_date
from doc_ingest.text_cleanup import clean_text
from doc_ingest.error import describe_error

logger = logging.getLogger(__name__)


class PDFParser(Parser):
	"""Parser for native text PDFs (scanned PDFs need OCR and are not handled here)."""

	def parse(self, raw_data: RawData) -> Document:
		"""
		Input: raw_data - the PDF's doc_id, doc_type, raw_path (its saved raw file) and source_path.
		Output: a Document with cleaned text and metadata; Document.id is raw_data.doc_id, not recomputed.
		What it does: opens the PDF once with pypdf, extracts and cleans the page texts, and fills generic and PDF metadata. Raises ValueError for a non-PDF or encrypted file.
		"""
		raw_path = raw_data.raw_path
		with open(raw_path, "rb") as raw_file:
			raw_bytes = raw_file.read()

		# Skip anything that is not a PDF
		if b"%PDF" not in raw_bytes[:1024]:
			raise ValueError("not a PDF")

		reader = pypdf.PdfReader(io.BytesIO(raw_bytes))

		# Encrypted PDFs are skipped for now
		if reader.is_encrypted:
			raise ValueError("encrypted PDF")

		# Document id
		doc_id = raw_data.doc_id

		# Document type
		doc_type = DocumentType(raw_data.doc_type)

		# Text extraction and cleanup
		page_texts = self.extract_page_texts(reader)
		doc_text = clean_text(page_texts)

		# Metadata: generic fields, then the PDF's own properties
		doc_metadata = extract_metadata(raw_data, raw_bytes)
		self.fill_pdf_properties(doc_metadata, reader)
		doc_metadata.page_count = len(page_texts)

		document = Document(
			id=doc_id,
			type=doc_type,
			text=doc_text,
			metadata=doc_metadata,
		)
		return document

	def extract_page_texts(self, reader: pypdf.PdfReader) -> list[str]:
		"""
		Input: pypdf reader of a PDF. Output: the raw text of each page, in page order.
		A page whose text cannot be extracted is logged and given as "", so one bad page does not lose the document.
		"""
		page_texts = []
		for page in reader.pages:
			try:
				page_text = page.extract_text()
			except Exception as error:
				logger.warning("Could not extract page text: %s", describe_error(error))
				page_text = ""
			page_texts.append(page_text)
		return page_texts

	def fill_pdf_properties(self, metadata: Metadata, reader: pypdf.PdfReader) -> None:
		"""
		Input: metadata - the Metadata to fill in; reader - pypdf reader of the PDF.
		Output: none. Sets metadata.title, metadata.author and metadata.creation_date.
		A PDF without document information leaves all three as None; a creation date pypdf cannot parse leaves only the date as None.
		"""
		pdf_information = reader.metadata
		if pdf_information is None:
			return

		metadata.author = clean_property_text(pdf_information.author)
		metadata.title = clean_property_text(pdf_information.title)

		try:
			creation_datetime = pdf_information.creation_date
		except ValueError as date_error:
			logger.warning("Could not parse PDF creation date: %s", date_error)
			creation_datetime = None

		metadata.creation_date = format_creation_date(creation_datetime)
