"""
summary.py

Counts and prints the end-of-run summary of doc processing: documents
loaded, newly processed and skipped by reason, and document parse times.
"""

import dataclasses


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
	loaded_from_cache: int = 0
	processed: int = 0

	# Skipped, by reason
	download_failed: int = 0
	unsupported_type: int = 0
	prepare_failed: int = 0
	parse_error: int = 0
	no_text: int = 0
	keep_error: int = 0
	cache_missing: int = 0
	skipped: int = 0
	duplicate: int = 0

	# Timing
	total_seconds: float = 0.0
	download_seconds: float = 0.0
	parse_seconds: float = 0.0


def print_run_summary(summary: Summary) -> None:
	"""
	Input: the run's Summary. Output: none.
	Prints the run counts, documents skipped by reason, and timings.
	"""
	print(f"Requested {summary.requested_size} document(s), returned {summary.returned_size}.")
	print(f"Dataset ran out of rows: {summary.source_exhausted}")
	print(f"Batches: {summary.batches}")
	print(f"Raw rows {summary.rows} have been consumed")
	print(f"Raw data {summary.downloaded} have been downloaded")
	print(f"Documents {summary.loaded_from_cache} have been loaded from cache")
	print(f"Documents {summary.processed} have been successfully processed")
	print(f"Skipped {summary.download_failed} row(s) that failed to download/decode.")
	print(f"Skipped {summary.unsupported_type} document(s) with an unsupported type.")
	print(f"Skipped {summary.prepare_failed} row(s) that could not be prepared for parsing.")
	print(f"Skipped {summary.parse_error} document(s) that failed in parsing.")
	print(f"Skipped {summary.no_text} document(s) with no text.")
	print(f"Skipped {summary.keep_error} document(s) that failed in duplicate check or saving.")
	print(f"Skipped {summary.cache_missing} cached document(s) missing or damaged on disk.")
	print(f"Skipped {summary.skipped} document(s) in total.")
	print(f"Skipped {summary.duplicate} document(s) due to duplicate detection.")
	print(f"Total time: {summary.total_seconds:.1f}s (download {summary.download_seconds:.1f}s, parse {summary.parse_seconds:.1f}s)")
