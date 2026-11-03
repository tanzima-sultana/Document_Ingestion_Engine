"""
summary.py

The end-of-run summary, so every run (any document type) reports the same
fields in the same groups: run, settings, and one group per phase.
"""

import dataclasses
import logging

from doc_ingest.settings import Settings

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Summary:
	# Run
	document_type: str | None = None
	path: str | None = None
	documents_requested: int = 0
	documents_returned: int = 0
	source_exhausted: bool = False
	total_seconds: float = 0.0

	# What the caller set
	settings: Settings | None = None

	# Fetching
	total_fetched: int = 0
	fetch_success: int = 0
	fetch_failed: int = 0
	wrong_doc_type: int = 0

	# Parsing
	total_parsed: int = 0
	parse_success: int = 0
	parse_failed: int = 0

	# Processing
	total_processed: int = 0
	cleanup_success: int = 0
	cleanup_failed: int = 0
	empty_documents: int = 0
	duplicates: int = 0
	dedup_failed: int = 0
	skipped: int = 0
	total_pages: int = 0
	blank_pages: int = 0
	total_characters: int = 0

	def set_fetch_summary(self, fetch_summary) -> None:
		"""
		Input: the fetcher's FetchSummary. Output: None. Copies them.
		"""
		self.total_fetched = fetch_summary.total_fetched
		self.fetch_success = fetch_summary.fetch_success
		self.fetch_failed = fetch_summary.fetch_failed
		self.wrong_doc_type = fetch_summary.wrong_doc_type

	def set_parse_summary(self, parse_summary) -> None:
		"""
		Input: the parser's ParseSummary. Output: None. Copies them.
		"""
		self.total_parsed = parse_summary.total_parsed
		self.parse_success = parse_summary.parse_success
		self.parse_failed = parse_summary.parse_failed

	def set_process_summary(self, process_summary) -> None:
		"""
		Input: the processor's ProcessSummary. Output: None. Copies them.
		"""
		self.total_processed = process_summary.total_processed
		self.cleanup_success = process_summary.cleanup_success
		self.cleanup_failed = process_summary.cleanup_failed
		self.empty_documents = process_summary.empty_documents
		self.duplicates = process_summary.duplicates
		self.dedup_failed = process_summary.dedup_failed
		self.skipped = self.cleanup_failed + self.empty_documents + self.dedup_failed + self.duplicates
		self.total_pages = process_summary.total_pages
		self.blank_pages = process_summary.blank_pages
		self.total_characters = process_summary.total_characters

	def to_dict(self) -> dict:
		"""
		Input: none. Output: the summary as a dict of groups, ready to print or save as JSON.
		"""
		settings_values = {}
		if self.settings is not None:
			settings_values = dataclasses.asdict(self.settings)

		return {
			"run": {
				"document_type": self.document_type,
				"path": self.path,
				"documents_requested": self.documents_requested,
				"documents_returned": self.documents_returned,
				"source_exhausted": self.source_exhausted,
				"total_seconds": round(self.total_seconds, 3),
			},
			"settings": settings_values,
			"fetching": {
				"total_fetched": self.total_fetched,
				"fetch_success": self.fetch_success,
				"fetch_failed": self.fetch_failed,
				"wrong_doc_type": self.wrong_doc_type,
			},
			"parsing": {
				"total_parsed": self.total_parsed,
				"parse_success": self.parse_success,
				"parse_failed": self.parse_failed,
			},
			"processing": {
				"total_processed": self.total_processed,
				"cleanup_success": self.cleanup_success,
				"cleanup_failed": self.cleanup_failed,
				"empty_documents": self.empty_documents,
				"duplicates": self.duplicates,
				"dedup_failed": self.dedup_failed,
				"skipped": self.skipped,
			},
			"pages": {
				"total_pages": self.total_pages,
				"blank_pages": self.blank_pages,
				"total_characters": self.total_characters,
			},
		}

	def print_run_summary(self) -> None:
		"""
		Input: none. Output: none.
		Logs (INFO) every group of to_dict, one "name: value" line per field,
		then the same lines the LangChain benchmark prints, to compare the two.
		"""
		logger.info("Run summary")
		for group_name, group_values in self.to_dict().items():
			logger.info("  %s:", group_name)
			for field_name, field_value in group_values.items():
				logger.info("    %s: %s", field_name, field_value)

		logger.info("Compare with LangChain")
		logger.info("  documents_requested : %s", self.documents_requested)
		logger.info("  documents_returned  : %s", self.documents_returned)
		logger.info("  total_pages         : %s", self.total_pages)
		logger.info("  blank_pages         : %s", self.blank_pages)
		logger.info("  total_characters    : %s", self.total_characters)
