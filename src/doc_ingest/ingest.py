"""
ingest.py

Runs the three phases, one document at a time: fetching, parsing and processing.
"""

import dataclasses
import logging
import tempfile
import time

from doc_ingest import validate
from doc_ingest.fetching.fetcher import BaseFetcher
from doc_ingest.fetching.local import LocalFetcher
from doc_ingest.parsing.parser import BaseParser
from doc_ingest.processing.processor import DocumentProcessor
from doc_ingest.schema import Document
from doc_ingest.settings import FetchSettings
from doc_ingest.settings import ParseSettings
from doc_ingest.settings import ProcessSettings
from doc_ingest.settings import Settings
from doc_ingest.summary import Summary

logger = logging.getLogger(__name__)

# A progress line is logged each time this many more documents are kept
PROGRESS_INTERVAL = 100


@dataclasses.dataclass
class IngestResult:
	"""
	What ingest_documents returns: the collected Documents and the run's Summary.
	"""
	documents: list[Document]
	summary: Summary


class IngestEngine:
	"""
	One ingest run for one source.
	"""

	def __init__(self, path: str, size: int, document_type: str, fetcher_class: type[BaseFetcher], settings: Settings):
		"""
		Input: path, size and document_type (already validated); fetcher_class - the BaseFetcher subclass for this source;
			settings - the caller's Settings.
		Output: none. Stores the inputs for run.
		"""
		self.path = path
		self.size = size
		self.document_type = document_type
		self.fetcher_class = fetcher_class
		self.settings = settings

	def run(self) -> IngestResult:
		"""
		Input: none (uses the inputs stored by __init__).
		Output: an IngestResult with up to size Documents and the run's Summary.
		What it does: fetches, parses and processes one document at a time until size is reached or the source runs out.
		"""
		run_start = time.perf_counter()

		# The caller sets one Settings; each phase has its own settings
		fetch_settings = FetchSettings(document_type=self.document_type)
		parse_settings = ParseSettings(document_type=self.document_type, timeout_seconds=self.settings.timeout_seconds)
		process_settings = ProcessSettings(dedup_threshold=self.settings.dedup_threshold)

		parser = BaseParser(parse_settings)
		processor = DocumentProcessor(process_settings)

		summary = Summary(document_type=self.document_type, requested_size=self.size, path=self.path, settings=self.settings)
		documents = []

		# A document that is not in a file of its own goes to this folder, which is removed when the run ends, also if it fails
		with tempfile.TemporaryDirectory(prefix="doc_ingest_") as storage_path:
			fetcher = self.fetcher_class(self.path, storage_path, fetch_settings)

			for raw_document in fetcher.fetch_documents():
				parsed_document = parser.parse_document(raw_document)
				if parsed_document is None:
					continue

				document = processor.process_document(parsed_document)

				if document is None:
					continue

				documents.append(document)

				if len(documents) % PROGRESS_INTERVAL == 0:
					logger.info("Kept %s of %s document(s).", len(documents), self.size)

				if len(documents) == self.size:
					break

		summary.set_fetch_summary(fetcher.summary)
		summary.set_parse_summary(parser.summary)
		summary.set_process_summary(processor.summary)
		summary.documents_returned = len(documents)
		summary.source_exhausted = len(documents) < self.size
		summary.total_seconds = time.perf_counter() - run_start
		summary.print_run_summary()

		return IngestResult(documents=documents, summary=summary)


def ingest_documents(path: str, size: int, document_type: str, *, settings: Settings | None = None) -> IngestResult:
	"""
	Input: path - local file or folder; size - max documents to return; document_type - the type to keep (e.g. "pdf"); settings - optional (None: all defaults).
	Output: an IngestResult: .documents (up to size Documents) and .summary (the run's Summary).
	What it does: checks the inputs, then runs the engine on a local source. Documents of another type are discarded.
	"""
	# None, not Settings(), as the default: a default object would be shared by every call
	if settings is None:
		settings = Settings()

	# Validate before any work is done
	validate.validate_local(path, size, document_type, settings)

	ingest_engine = IngestEngine(path, size, document_type, LocalFetcher, settings)
	return ingest_engine.run()
