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
	requested_size: int = 0
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
	no_text: int = 0
	duplicates: int = 0
	duplicate_check_failed: int = 0
	pages: int = 0
	characters: int = 0

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
		self.no_text = process_summary.no_text
		self.duplicates = process_summary.duplicates
		self.duplicate_check_failed = process_summary.duplicate_check_failed
		self.pages = process_summary.pages
		self.characters = process_summary.characters

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
				"requested_size": self.requested_size,
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
				"no_text": self.no_text,
				"duplicates": self.duplicates,
				"duplicate_check_failed": self.duplicate_check_failed,
				"pages": self.pages,
				"characters": self.characters,
			},
		}

	def print_run_summary(self) -> None:
		"""
		Input: none. Output: none.
		Logs (INFO) every group of to_dict, one "name: value" line per field.
		"""
		logger.info("Run summary")
		for group_name, group_values in self.to_dict().items():
			logger.info("  %s:", group_name)
			for field_name, field_value in group_values.items():
				logger.info("    %s: %s", field_name, field_value)
