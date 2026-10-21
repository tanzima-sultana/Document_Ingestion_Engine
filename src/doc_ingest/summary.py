"""
summary.py

Counts and logs the end-of-run summary of doc processing: documents
processed and skipped by reason, and document parse times.
"""

import logging
import dataclasses

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Summary:
	# Run
	requested_size: int = 0
	returned_size: int = 0
	source_exhausted: bool = False
	batches: int = 0

	# Rows and documents
	rows: int = 0
	downloaded: int = 0
	processed: int = 0

	# Skipped, by reason
	download_failed: int = 0
	unsupported_type: int = 0
	prepare_failed: int = 0
	parse_error: int = 0
	no_text: int = 0
	keep_error: int = 0
	skipped: int = 0
	duplicate: int = 0

	# Pages of every parsed document (kept, empty or duplicate), for pages/second
	pages_parsed: int = 0

	# Timing
	total_seconds: float = 0.0
	download_seconds: float = 0.0
	parse_seconds: float = 0.0


def print_run_summary(summary: Summary) -> None:
	"""
	Input: the run's Summary. Output: none.
	Logs (INFO) the run counts, documents skipped by reason, and timings.
	"""
	logger.info("Requested %s document(s), returned %s.", summary.requested_size, summary.returned_size)
	logger.info("Dataset ran out of rows: %s", summary.source_exhausted)
	logger.info("Batches: %s", summary.batches)
	logger.info("Raw rows %s have been consumed", summary.rows)
	logger.info("Raw data %s have been downloaded", summary.downloaded)
	logger.info("Documents %s have been successfully processed", summary.processed)
	logger.info("Skipped %s row(s) that failed to download/decode.", summary.download_failed)
	logger.info("Skipped %s document(s) with an unsupported type.", summary.unsupported_type)
	logger.info("Skipped %s row(s) that could not be prepared for parsing.", summary.prepare_failed)
	logger.info("Skipped %s document(s) that failed in parsing.", summary.parse_error)
	logger.info("Skipped %s document(s) with no text.", summary.no_text)
	logger.info("Skipped %s document(s) that failed in duplicate check.", summary.keep_error)
	logger.info("Skipped %s document(s) in total.", summary.skipped)
	logger.info("Skipped %s document(s) due to duplicate detection.", summary.duplicate)
	logger.info("Total time: %.1fs (download %.1fs, parse %.1fs)", summary.total_seconds, summary.download_seconds, summary.parse_seconds)

	pages_per_second = 0.0
	if summary.parse_seconds > 0:
		pages_per_second = summary.pages_parsed / summary.parse_seconds
	logger.info("Pages parsed: %s (%.1f pages/second of parse time)", summary.pages_parsed, pages_per_second)
