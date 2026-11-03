"""
processing/processor.py

The third phase: turns a ParsedDocument into the final Document. Cleans the
text and title, skips documents with no text and removes duplicates.
"""

import dataclasses
import logging

from doc_ingest.error import describe_error
from doc_ingest.parsing.parser import ParsedDocument
from doc_ingest.processing.dedup import Deduplicator
from doc_ingest.processing.text_cleanup import clean_page_texts
from doc_ingest.processing.text_cleanup import clean_property_text
from doc_ingest.schema import Document
from doc_ingest.schema import DocumentType
from doc_ingest.schema import Page
from doc_ingest.settings import ProcessSettings

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ProcessSummary:
	"""
	Counts of what processing did: documents processed, dropped and returned,
	and the pages and characters of the returned documents.
	"""
	total_processed: int = 0
	cleanup_success: int = 0
	cleanup_failed: int = 0
	empty_documents: int = 0
	duplicates: int = 0
	dedup_failed: int = 0
	total_pages: int = 0
	blank_pages: int = 0
	total_characters: int = 0


class DocumentProcessor:
	"""
	Processes parsed documents one at a time. Holds the run's duplicate
	checker, so each document is checked against all the kept ones.
	"""

	def __init__(self, process_settings: ProcessSettings):
		"""
		Input: process_settings - the near-duplicate threshold.
		Output: none.
		"""
		self.deduplicator = Deduplicator(threshold=process_settings.dedup_threshold)
		self.summary = ProcessSummary()

	def process_document(self, parsed_document: ParsedDocument) -> Document | None:
		"""
		Input: parsed_document - from the parser.
		Output: the final Document, or None if it is skipped.
		What it does: builds the cleaned Document, then skips it if it has no text or is a duplicate.
		"""
		self.summary.total_processed += 1

		try:
			document = self.build_document(parsed_document)
		except Exception as error:
			logger.warning("Skipping document %s: cleanup failed: %s", parsed_document.id, describe_error(error))
			self.summary.cleanup_failed += 1
			return None

		self.summary.cleanup_success += 1

		# No text, e.g. a scanned PDF
		if document.text == "":
			logger.warning("Skipping document %s: no text", document.id)
			self.summary.empty_documents += 1
			return None

		try:
			document_is_new = self.deduplicator.add_if_new(document)
		except Exception as error:
			logger.warning("Skipping document %s: duplicate check failed: %s", document.id, describe_error(error))
			self.summary.dedup_failed += 1
			return None

		if not document_is_new:
			self.summary.duplicates += 1
			return None

		self.summary.total_pages += len(document.pages)
		for page in document.pages:
			if page.text == "":
				self.summary.blank_pages += 1
			self.summary.total_characters += len(page.text)

		return document

	def build_document(self, parsed_document: ParsedDocument) -> Document:
		"""
		Input: parsed_document - with the raw text of each page.
		Output: the Document, with cleaned pages numbered from 1 and a tidied title. A page left with no text keeps its place.
		"""
		cleaned_page_texts = clean_page_texts(parsed_document.raw_texts)

		pages = []
		for page_index in range(len(cleaned_page_texts)):
			pages.append(Page(number=page_index + 1, text=cleaned_page_texts[page_index]))

		return Document(
			id=parsed_document.id,
			type=DocumentType(parsed_document.type),
			source=parsed_document.source,
			title=clean_property_text(parsed_document.title),
			pages=pages,
		)
