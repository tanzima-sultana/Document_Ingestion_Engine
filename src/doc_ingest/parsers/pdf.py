"""
pdf.py

Implements Parser for PDF documents with two interchangeable libraries:
PyPdfParser (pypdf, the default) and PyPdfium2Parser (pypdfium2, an
optional install). Both subclass PdfParser, which runs the same parse
flow for every library (read bytes, open, page texts, properties, close,
build the Document), so the output format never depends on which one
is used; only the extracted text can differ. Each subclass only fills in
the library calls: opening (non-PDF and encrypted files are skipped),
closing, reading one page's text and reading the raw properties.
"""

import abc
import datetime
import io
import logging

import pypdf

from doc_ingest.parser import Parser
from doc_ingest.schema import Document
from doc_ingest.schema import DocumentType
from doc_ingest.raw_data import RawData
from doc_ingest.metadata import extract_metadata
from doc_ingest.metadata import clean_property_text
from doc_ingest.metadata import format_creation_date
from doc_ingest.text_cleanup import clean_text
from doc_ingest.error import describe_error

logger = logging.getLogger(__name__)


class PdfParser(Parser):
	"""
	Shared parse flow for native text PDFs (scanned PDFs need OCR and are not handled here).
	Subclasses set parser_name and fill in the library calls.
	"""

	parser_name = ""

	def parse(self, raw_data: RawData) -> Document:
		"""
		Input: raw_data - the PDF's doc_id, doc_type, raw_path (its saved raw file) and source_path.
		Output: a Document with cleaned text and metadata; Document.id is raw_data.doc_id, not recomputed.
		What it does: opens the PDF once, extracts the page texts and properties, closes it and builds the Document. Raises ValueError for a non-PDF or encrypted file.
		"""
		raw_bytes = self.read_pdf_bytes(raw_data)

		pdf = self.open_pdf(raw_bytes)
		try:
			page_texts = self.extract_page_texts(pdf)
			title, author, creation_datetime = self.read_pdf_properties(pdf)
		finally:
			self.close_pdf(pdf)

		document = self.build_pdf_document(raw_data, raw_bytes, page_texts, title, author, creation_datetime)
		return document

	def read_pdf_bytes(self, raw_data: RawData) -> bytes:
		"""
		Input: raw_data - the document, with raw_path pointing to its saved raw file.
		Output: the file's bytes.
		What it does: reads the raw file and raises ValueError if it does not look like a PDF.
		"""
		with open(raw_data.raw_path, "rb") as raw_file:
			raw_bytes = raw_file.read()

		# Skip anything that is not a PDF
		if b"%PDF" not in raw_bytes[:1024]:
			raise ValueError("not a PDF")

		return raw_bytes

	def extract_page_texts(self, pdf) -> list[str]:
		"""
		Input: pdf - the open PDF (from open_pdf). Output: the raw text of each page, in page order.
		A page whose text cannot be extracted is logged and given as "", so one bad page does not lose the document.
		"""
		page_texts = []
		page_count = self.get_page_count(pdf)
		for page_index in range(page_count):
			try:
				page_text = self.extract_page_text(pdf, page_index)
			except Exception as error:
				logger.warning("Could not extract page text: %s", describe_error(error))
				page_text = ""
			page_texts.append(page_text)
		return page_texts

	def read_pdf_properties(self, pdf) -> tuple:
		"""
		Input: pdf - the open PDF (from open_pdf).
		Output: (title, author, creation_datetime) as stored in the PDF; each can be None.
		A creation date that cannot be parsed is logged and given as None; the title and author are kept.
		"""
		title, author, raw_creation_date = self.read_raw_properties(pdf)

		try:
			creation_datetime = self.parse_pdf_date(raw_creation_date)
		except ValueError as date_error:
			logger.warning("Could not parse PDF creation date: %s", date_error)
			creation_datetime = None

		return title, author, creation_datetime

	def build_pdf_document(self, raw_data: RawData, raw_bytes: bytes, page_texts: list[str], title, author, creation_datetime) -> Document:
		"""
		Input: raw_data and raw_bytes of the PDF; page_texts - raw text per page; title, author, creation_datetime - as read from the PDF (each can be None).
		Output: the Document, with metadata.parser set to parser_name.
		What it does: cleans the text and fills the metadata the same way for every PDF parser, so the output format never depends on the parser.
		"""
		doc_text = clean_text(page_texts)

		doc_metadata = extract_metadata(raw_data, raw_bytes)
		doc_metadata.title = clean_property_text(title)
		doc_metadata.author = clean_property_text(author)
		doc_metadata.creation_date = format_creation_date(creation_datetime)
		doc_metadata.page_count = len(page_texts)
		doc_metadata.parser = self.parser_name

		document = Document(
			id=raw_data.doc_id,
			type=DocumentType(raw_data.doc_type),
			text=doc_text,
			metadata=doc_metadata,
		)
		return document

	def parse_pdf_date(self, date_text: str | None) -> datetime.datetime | None:
		"""
		Input: date_text - a PDF date such as "D:20240301101500+01'00'", or None/"".
		Output: the date as a datetime (with time zone when the text has one), or None if there is no date.
		What it does: follows the same steps as pypdf's own date parsing; both PDF parsers use it, so they give the same creation_date. Raises ValueError if the text is not a date.
		"""
		if date_text is None:
			return None
		if date_text == "":
			return None

		text = date_text
		if text[0].isdigit():
			text = "D:" + text

		# "Z" means UTC
		if text.endswith("Z") or text.endswith("z"):
			text = text + "0000"
		text = text.replace("z", "+")
		text = text.replace("Z", "+")
		text = text.replace("'", "")

		# A time zone given only as hours ("+01") gets "00" minutes added
		time_zone_sign_index = max(text.find("+"), text.find("-"))
		if time_zone_sign_index > 0 and time_zone_sign_index != len(text) - 5:
			text = text + "00"

		date_formats = [
			"D:%Y",
			"D:%Y%m",
			"D:%Y%m%d",
			"D:%Y%m%d%H",
			"D:%Y%m%d%H%M",
			"D:%Y%m%d%H%M%S",
			"D:%Y%m%d%H%M%S%z",
		]
		for date_format in date_formats:
			try:
				parsed_datetime = datetime.datetime.strptime(text, date_format)
			except ValueError:
				continue

			if text.endswith("+0000"):
				parsed_datetime = parsed_datetime.replace(tzinfo=datetime.timezone.utc)
			return parsed_datetime

		raise ValueError("Can not convert date: " + date_text)

	@abc.abstractmethod
	def open_pdf(self, raw_bytes: bytes):
		"""
		Input: raw_bytes - the PDF's bytes.
		Output: the open PDF, as the library's own object.
		What it does: opens the PDF with the library. Raises ValueError("encrypted PDF") for an encrypted PDF.
		"""
		raise NotImplementedError

	@abc.abstractmethod
	def close_pdf(self, pdf) -> None:
		"""
		Input: pdf - the open PDF (from open_pdf). Output: none.
		What it does: frees what the library holds for the open PDF.
		"""
		raise NotImplementedError

	@abc.abstractmethod
	def get_page_count(self, pdf) -> int:
		"""
		Input: pdf - the open PDF (from open_pdf). Output: its number of pages.
		"""
		raise NotImplementedError

	@abc.abstractmethod
	def extract_page_text(self, pdf, page_index: int) -> str:
		"""
		Input: pdf - the open PDF (from open_pdf); page_index - the page, from 0.
		Output: the page's raw text. Raises if the text cannot be extracted.
		"""
		raise NotImplementedError

	@abc.abstractmethod
	def read_raw_properties(self, pdf) -> tuple:
		"""
		Input: pdf - the open PDF (from open_pdf).
		Output: (title, author, raw_creation_date) as text stored in the PDF; each can be None.
		"""
		raise NotImplementedError


class PyPdfParser(PdfParser):
	"""Parser for native text PDFs using pypdf."""

	parser_name = "pypdf"

	def open_pdf(self, raw_bytes: bytes) -> pypdf.PdfReader:
		"""
		Input: raw_bytes - the PDF's bytes. Output: a pypdf reader of the PDF.
		Raises ValueError for an encrypted PDF.
		"""
		reader = pypdf.PdfReader(io.BytesIO(raw_bytes))

		# Encrypted PDFs are skipped for now
		if reader.is_encrypted:
			raise ValueError("encrypted PDF")

		return reader

	def close_pdf(self, reader: pypdf.PdfReader) -> None:
		"""
		Input: reader - pypdf reader of the PDF. Output: none.
		Nothing to free: the reader reads from bytes in memory.
		"""
		return None

	def get_page_count(self, reader: pypdf.PdfReader) -> int:
		"""
		Input: reader - pypdf reader of the PDF. Output: its number of pages.
		"""
		return len(reader.pages)

	def extract_page_text(self, reader: pypdf.PdfReader, page_index: int) -> str:
		"""
		Input: reader - pypdf reader of the PDF; page_index - the page, from 0.
		Output: the page's raw text.
		"""
		page = reader.pages[page_index]
		page_text = page.extract_text()
		return page_text

	def read_raw_properties(self, reader: pypdf.PdfReader) -> tuple:
		"""
		Input: reader - pypdf reader of the PDF.
		Output: (title, author, raw_creation_date) as text; each can be None.
		A PDF without document information gives all three as None.
		"""
		pdf_information = reader.metadata
		if pdf_information is None:
			return None, None, None

		title = self.read_text_property(pdf_information, "/Title")
		author = self.read_text_property(pdf_information, "/Author")
		raw_creation_date = self.read_text_property(pdf_information, "/CreationDate")
		return title, author, raw_creation_date

	def read_text_property(self, pdf_information: pypdf.DocumentInformation, property_key: str) -> str | None:
		"""
		Input: pdf_information - the PDF's document information; property_key - e.g. "/Author".
		Output: the property as text, or None if it is missing or not text.
		Some PDFs store a property as a reference to another object; it is followed here (pypdf's .author and .creation_date do not), so pypdf finds the same values as pypdfium2.
		"""
		property_value = pdf_information.get(property_key)
		if property_value is None:
			return None

		property_value = property_value.get_object()
		if isinstance(property_value, pypdf.generic.TextStringObject):
			return str(property_value)
		if isinstance(property_value, pypdf.generic.ByteStringObject):
			return str(property_value)
		return None


class PyPdfium2Parser(PdfParser):
	"""Parser for native text PDFs using pypdfium2 (optional install: pip install doc-ingest[pdfium])."""

	parser_name = "pypdfium2"

	def open_pdf(self, raw_bytes: bytes):
		"""
		Input: raw_bytes - the PDF's bytes. Output: an open pypdfium2.PdfDocument.
		Raises ValueError for an encrypted PDF, like PyPdfParser: both one that needs a password and one that opens without it.
		"""
		# Imported here so pypdfium2 is only needed when this parser is chosen
		import pypdfium2
		import pypdfium2.raw as pdfium_c

		# A PDF that needs a password cannot be opened at all
		try:
			pdf_document = pypdfium2.PdfDocument(raw_bytes)
		except pypdfium2.PdfiumError as open_error:
			error_code = getattr(open_error, "err_code", None)
			if error_code == pdfium_c.FPDF_ERR_PASSWORD:
				raise ValueError("encrypted PDF")
			raise

		# Same rule as pypdf: skip every encrypted PDF, also those that open without a password.
		# The security handler revision is -1 only for a PDF without encryption.
		security_handler_revision = pdfium_c.FPDF_GetSecurityHandlerRevision(pdf_document.raw)
		if security_handler_revision != -1:
			pdf_document.close()
			raise ValueError("encrypted PDF")

		return pdf_document

	def close_pdf(self, pdf_document) -> None:
		"""
		Input: pdf_document - an open pypdfium2.PdfDocument. Output: none.
		Closes it, freeing the memory pdfium holds for it.
		"""
		pdf_document.close()

	def get_page_count(self, pdf_document) -> int:
		"""
		Input: pdf_document - an open pypdfium2.PdfDocument. Output: its number of pages.
		"""
		return len(pdf_document)

	def extract_page_text(self, pdf_document, page_index: int) -> str:
		"""
		Input: pdf_document - an open pypdfium2.PdfDocument; page_index - the page, from 0.
		Output: the page's raw text.
		"""
		page = pdf_document[page_index]
		text_page = page.get_textpage()
		page_text = text_page.get_text_bounded()
		text_page.close()
		page.close()
		return page_text

	def read_raw_properties(self, pdf_document) -> tuple:
		"""
		Input: pdf_document - an open pypdfium2.PdfDocument.
		Output: (title, author, raw_creation_date) as text; each can be None.
		"""
		pdf_information = pdf_document.get_metadata_dict()

		title = pdf_information.get("Title")
		author = pdf_information.get("Author")
		raw_creation_date = pdf_information.get("CreationDate")
		return title, author, raw_creation_date
