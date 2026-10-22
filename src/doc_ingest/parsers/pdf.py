"""
pdf.py

Implements Parser for PDF documents with two interchangeable LangChain
parsers: PyPdfParser (LangChain's PyPDFParser, pypdf, the default) and
PyPdfium2Parser (LangChain's PyPDFium2Parser, pypdfium2, an optional
install). Both subclass PdfParser, which runs the same parse flow for
every library (read bytes, read the pages with LangChain, page texts,
properties, build the Document), so the output format never depends on
which one is used; only the extracted text can differ. Each subclass only
chooses the LangChain parser. Non-PDF files are skipped; encrypted and
broken files are handled the way LangChain handles them.
"""

import abc
import datetime
import logging

from langchain_community.document_loaders.parsers.pdf import PyPDFParser
from langchain_community.document_loaders.parsers.pdf import PyPDFium2Parser
from langchain_core.documents.base import Blob

from doc_ingest.parsers.base import Parser
from doc_ingest.schema import Document
from doc_ingest.schema import DocumentType
from doc_ingest.dataset.raw_data import RawData
from doc_ingest.processing.metadata import extract_metadata
from doc_ingest.processing.metadata import clean_property_text
from doc_ingest.processing.metadata import format_creation_date
from doc_ingest.processing.text_cleanup import clean_text
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
		What it does: reads the PDF's pages once with LangChain, takes the page texts and properties and builds the Document. Raises ValueError for a non-PDF file.
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
		Input: pdf - the PDF's pages (from open_pdf). Output: the raw text of each page, in page order.
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
		Input: pdf - the PDF's pages (from open_pdf).
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
		Input: date_text - a date as LangChain gives it ("2024-03-01T10:15:00+01:00"), a PDF date such as "D:20240301101500+01'00'", or None/"".
		Output: the date as a datetime (with time zone when the text has one), or None if there is no date.
		What it does: LangChain turns a PDF date it can read into ISO 8601 text and leaves other dates as stored, so ISO is tried first, then the same steps as pypdf's own date parsing. Raises ValueError if the text is not a date.
		"""
		if date_text is None:
			return None
		if date_text == "":
			return None

		try:
			return datetime.datetime.fromisoformat(date_text)
		except ValueError:
			pass

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

	def close_pdf(self, pages: list) -> None:
		"""
		Input: pages - the LangChain page Documents (from open_pdf). Output: none.
		Nothing to free: LangChain closes the PDF itself after reading it.
		"""
		return None

	def get_page_count(self, pages: list) -> int:
		"""
		Input: pages - the LangChain page Documents (from open_pdf). Output: the number of pages.
		"""
		return len(pages)

	def extract_page_text(self, pages: list, page_index: int) -> str:
		"""
		Input: pages - the LangChain page Documents (from open_pdf); page_index - the page, from 0.
		Output: the page's raw text.
		"""
		return pages[page_index].page_content

	def read_raw_properties(self, pages: list) -> tuple:
		"""
		Input: pages - the LangChain page Documents (from open_pdf).
		Output: (title, author, raw_creation_date) as text; each can be None.
		LangChain puts the PDF's properties into every page's metadata, so the first page's are used.
		"""
		if len(pages) == 0:
			return None, None, None

		page_metadata = pages[0].metadata
		title = page_metadata.get("title")
		author = page_metadata.get("author")
		raw_creation_date = page_metadata.get("creationdate")
		return title, author, raw_creation_date

	@abc.abstractmethod
	def open_pdf(self, raw_bytes: bytes) -> list:
		"""
		Input: raw_bytes - the PDF's bytes.
		Output: the PDF's pages as LangChain Documents, one per page, read by the subclass's LangChain parser.
		"""
		raise NotImplementedError


class PyPdfParser(PdfParser):
	"""Parser for native text PDFs using LangChain's PyPDFParser (pypdf)."""

	parser_name = "pypdf"

	def open_pdf(self, raw_bytes: bytes) -> list:
		"""
		Input: raw_bytes - the PDF's bytes. Output: the PDF's pages as LangChain Documents.
		"""
		langchain_parser = PyPDFParser()
		pages = langchain_parser.parse(Blob.from_data(raw_bytes))
		return pages


class PyPdfium2Parser(PdfParser):
	"""Parser for native text PDFs using LangChain's PyPDFium2Parser (pypdfium2, optional install: pip install doc-ingest[pdfium])."""

	parser_name = "pypdfium2"

	def open_pdf(self, raw_bytes: bytes) -> list:
		"""
		Input: raw_bytes - the PDF's bytes. Output: the PDF's pages as LangChain Documents.
		"""
		langchain_parser = PyPDFium2Parser()
		pages = langchain_parser.parse(Blob.from_data(raw_bytes))
		return pages
