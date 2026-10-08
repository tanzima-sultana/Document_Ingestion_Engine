"""
pdf.py

Implements Parser for PDF documents with two interchangeable libraries:
PyPdfParser (pypdf, the default) and PyPdfium2Parser (pypdfium2, an
optional install). Both follow the same rules (non-PDF and encrypted
files are skipped) and build the Document the same way
(build_pdf_document), so the output format never depends on which one
is used; only the extracted text can differ.
"""

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


class PyPdfParser(Parser):
	"""Parser for native text PDFs using pypdf (scanned PDFs need OCR and are not handled here)."""

	parser_name = "pypdf"

	def parse(self, raw_data: RawData) -> Document:
		"""
		Input: raw_data - the PDF's doc_id, doc_type, raw_path (its saved raw file) and source_path.
		Output: a Document with cleaned text and metadata; Document.id is raw_data.doc_id, not recomputed.
		What it does: opens the PDF once with pypdf, extracts the page texts and properties, and builds the Document. Raises ValueError for a non-PDF or encrypted file.
		"""
		raw_bytes = read_pdf_bytes(raw_data)

		reader = pypdf.PdfReader(io.BytesIO(raw_bytes))

		# Encrypted PDFs are skipped for now
		if reader.is_encrypted:
			raise ValueError("encrypted PDF")

		page_texts = self.extract_page_texts(reader)
		title, author, creation_datetime = self.read_pdf_properties(reader)

		document = build_pdf_document(raw_data, raw_bytes, page_texts, title, author, creation_datetime, self.parser_name)
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

	def read_pdf_properties(self, reader: pypdf.PdfReader) -> tuple:
		"""
		Input: reader - pypdf reader of the PDF.
		Output: (title, author, creation_datetime) as stored in the PDF; each can be None.
		A PDF without document information gives all three as None; a creation date that cannot be parsed gives only the date as None.
		The date is converted with parse_pdf_date, the same as in PyPdfium2Parser.
		"""
		pdf_information = reader.metadata
		if pdf_information is None:
			return None, None, None

		title = self.read_text_property(pdf_information, "/Title")
		author = self.read_text_property(pdf_information, "/Author")

		raw_creation_date = self.read_text_property(pdf_information, "/CreationDate")
		try:
			creation_datetime = parse_pdf_date(raw_creation_date)
		except ValueError as date_error:
			logger.warning("Could not parse PDF creation date: %s", date_error)
			creation_datetime = None

		return title, author, creation_datetime

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


class PyPdfium2Parser(Parser):
	"""Parser for native text PDFs using pypdfium2 (optional install: pip install doc-ingest[pdfium])."""

	parser_name = "pypdfium2"

	def parse(self, raw_data: RawData) -> Document:
		"""
		Input: raw_data - the PDF's doc_id, doc_type, raw_path (its saved raw file) and source_path.
		Output: a Document with cleaned text and metadata; Document.id is raw_data.doc_id, not recomputed.
		What it does: opens the PDF once with pypdfium2, extracts the page texts and properties, and builds the Document. Raises ValueError for a non-PDF or encrypted file, like PyPdfParser.
		"""
		# Imported here so pypdfium2 is only needed when this parser is chosen
		import pypdfium2
		import pypdfium2.raw as pdfium_c

		raw_bytes = read_pdf_bytes(raw_data)

		# A PDF that needs a password cannot be opened at all
		try:
			pdf_document = pypdfium2.PdfDocument(raw_bytes)
		except pypdfium2.PdfiumError as open_error:
			error_code = getattr(open_error, "err_code", None)
			if error_code == pdfium_c.FPDF_ERR_PASSWORD:
				raise ValueError("encrypted PDF")
			raise

		try:
			# Same rule as pypdf: skip every encrypted PDF, also those that open without a password.
			# The security handler revision is -1 only for a PDF without encryption.
			security_handler_revision = pdfium_c.FPDF_GetSecurityHandlerRevision(pdf_document.raw)
			if security_handler_revision != -1:
				raise ValueError("encrypted PDF")

			page_texts = self.extract_page_texts(pdf_document)
			title, author, creation_datetime = self.read_pdf_properties(pdf_document)
		finally:
			pdf_document.close()

		document = build_pdf_document(raw_data, raw_bytes, page_texts, title, author, creation_datetime, self.parser_name)
		return document

	def extract_page_texts(self, pdf_document) -> list[str]:
		"""
		Input: pdf_document - an open pypdfium2.PdfDocument. Output: the raw text of each page, in page order.
		A page whose text cannot be extracted is logged and given as "", so one bad page does not lose the document.
		"""
		page_texts = []
		for page_index in range(len(pdf_document)):
			try:
				page = pdf_document[page_index]
				text_page = page.get_textpage()
				page_text = text_page.get_text_bounded()
				text_page.close()
				page.close()
			except Exception as error:
				logger.warning("Could not extract page text: %s", describe_error(error))
				page_text = ""
			page_texts.append(page_text)
		return page_texts

	def read_pdf_properties(self, pdf_document) -> tuple:
		"""
		Input: pdf_document - an open pypdfium2.PdfDocument.
		Output: (title, author, creation_datetime) as stored in the PDF; each can be None.
		The creation date is raw PDF text; it is converted with parse_pdf_date, the same as in PyPdfParser.
		"""
		pdf_information = pdf_document.get_metadata_dict()

		title = pdf_information.get("Title")
		author = pdf_information.get("Author")

		raw_creation_date = pdf_information.get("CreationDate")
		try:
			creation_datetime = parse_pdf_date(raw_creation_date)
		except ValueError as date_error:
			logger.warning("Could not parse PDF creation date: %s", date_error)
			creation_datetime = None

		return title, author, creation_datetime


def read_pdf_bytes(raw_data: RawData) -> bytes:
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


def build_pdf_document(raw_data: RawData, raw_bytes: bytes, page_texts: list[str], title, author, creation_datetime, parser_name: str) -> Document:
	"""
	Input: raw_data and raw_bytes of the PDF; page_texts - raw text per page; title, author, creation_datetime - as read by the parser (each can be None); parser_name - the library used.
	Output: the Document.
	What it does: cleans the text and fills the metadata the same way for every PDF parser, so the output format never depends on the parser.
	"""
	doc_text = clean_text(page_texts)

	doc_metadata = extract_metadata(raw_data, raw_bytes)
	doc_metadata.title = clean_property_text(title)
	doc_metadata.author = clean_property_text(author)
	doc_metadata.creation_date = format_creation_date(creation_datetime)
	doc_metadata.page_count = len(page_texts)
	doc_metadata.parser = parser_name

	document = Document(
		id=raw_data.doc_id,
		type=DocumentType(raw_data.doc_type),
		text=doc_text,
		metadata=doc_metadata,
	)
	return document


def parse_pdf_date(date_text: str | None) -> datetime.datetime | None:
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
