"""
parsing/scanned_pdf.py

Implements BaseParser for scanned PDFs with LangChain's PyPDFium2Parser (pypdfium2),
with each page's images read by OCR (LangChain's RapidOCRBlobParser). A PDF that has
a text layer is not a scanned PDF and is skipped.
"""

from langchain_community.document_loaders.parsers.images import RapidOCRBlobParser
from langchain_community.document_loaders.parsers.pdf import PyPDFium2Parser
from langchain_core.documents.base import Blob

from doc_ingest.parsing.parser import BaseParser
from doc_ingest.parsing.parser import ParsedDocument
from doc_ingest.fetching.fetcher import RawDocument


class ScannedPdfParser(BaseParser):
	"""
	Parser for scanned PDFs (pages that are images, with no text layer), using LangChain's PyPDFium2Parser with OCR.
	"""

	@classmethod
	def parse(cls, raw_document: RawDocument) -> ParsedDocument:
		"""
		Input: raw_document - the PDF's id, type, raw_path (the file to read) and source.
		Output: a ParsedDocument with the OCR text of each page; its id is raw_document.id, not recomputed.
		What it does: reads the PDF's text layer first. If any page has text, it is not a scanned PDF and an
			error is raised, so it is skipped. Otherwise it reads the pages again with OCR and takes the page texts
			and title. A page with no text is kept, so later page numbers stay correct.
		"""
		text_layer_pages = cls.read_text_layer_pages(raw_document.raw_path)
		if cls.has_text_layer(text_layer_pages):
			raise ValueError("has a text layer, not a scanned PDF")

		ocr_pages = cls.read_ocr_pages(raw_document.raw_path)
		page_texts = cls.extract_page_texts(ocr_pages)
		title = cls.read_pdf_title(ocr_pages)

		return ParsedDocument(raw_document.id, raw_document.type, raw_document.source, title, page_texts)

	@classmethod
	def read_text_layer_pages(cls, raw_path: str) -> list:
		"""
		Input: raw_path - the path of the PDF. Output: the PDF's pages as LangChain Documents, with only the text layer (no OCR).
		"""
		langchain_parser = PyPDFium2Parser()
		pages = langchain_parser.parse(Blob.from_path(raw_path))
		return pages

	@classmethod
	def has_text_layer(cls, pages: list) -> bool:
		"""
		Input: pages - the LangChain page Documents read without OCR.
		Output: True if any page has text other than whitespace, otherwise False.
		"""
		for page in pages:
			if page.page_content.strip() != "":
				return True
		return False

	@classmethod
	def read_ocr_pages(cls, raw_path: str) -> list:
		"""
		Input: raw_path - the path of the PDF.
		Output: the PDF's pages as LangChain Documents, one per page, with the OCR text of the page's images as its text.
		"""
		langchain_parser = PyPDFium2Parser(
			extract_images=True,
			images_parser=RapidOCRBlobParser(),
			images_inner_format="text",
		)
		pages = langchain_parser.parse(Blob.from_path(raw_path))
		return pages

	@classmethod
	def extract_page_texts(cls, pages: list) -> list[str]:
		"""
		Input: pages - the LangChain page Documents. Output: the raw text of each page, in page order.
		"""
		page_texts = []
		for page in pages:
			page_texts.append(page.page_content)
		return page_texts

	@classmethod
	def read_pdf_title(cls, pages: list) -> str | None:
		"""
		Input: pages - the LangChain page Documents.
		Output: the title stored in the PDF, or None. LangChain puts the PDF's properties into every page's metadata, so the first page's are used.
		"""
		if len(pages) == 0:
			return None

		return pages[0].metadata.get("title")
