"""
parsing/pdf.py

Implements BaseParser for PDF documents with LangChain's PyPDFium2Parser
(pypdfium2). Non-PDF files are skipped; encrypted and broken files are
handled the way LangChain handles them.
"""

from langchain_community.document_loaders.parsers.pdf import PyPDFium2Parser
from langchain_core.documents.base import Blob

from doc_ingest.parsing.parser import BaseParser
from doc_ingest.parsing.parser import ParsedDocument
from doc_ingest.fetching.fetcher import RawDocument


class PdfParser(BaseParser):
	"""
	Parser for native text PDFs, using LangChain's PyPDFium2Parser (scanned PDFs need OCR and are not handled here).
	"""

	@classmethod
	def parse(cls, raw_document: RawDocument) -> ParsedDocument:
		"""
		Input: raw_document - the PDF's id, type, raw_path (the file to read) and source.
		Output: a ParsedDocument with the raw text of each page; its id is raw_document.id, not recomputed.
		What it does: reads the PDF's pages once with LangChain and takes the page texts and title. LangChain raises an error for a file that is not a PDF. A page with no text is kept, so later page numbers stay correct.
		"""
		pages = cls.read_pdf_pages(raw_document.raw_path)
		page_texts = cls.extract_page_texts(pages)
		title = cls.read_pdf_title(pages)

		return ParsedDocument(raw_document.id, raw_document.type, raw_document.source, title, page_texts)

	@classmethod
	def read_pdf_pages(cls, raw_path: str) -> list:
		"""
		Input: raw_path - the path of the PDF. Output: the PDF's pages as LangChain Documents, one per page.
		"""
		langchain_parser = PyPDFium2Parser()
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
