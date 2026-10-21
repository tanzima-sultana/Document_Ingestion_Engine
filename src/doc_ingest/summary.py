"""
summary.py

The end-of-run summary shared by doc_ingest and the benchmarks, so every
run (any tool, any document type) reports the same fields in the same
groups: run, settings, counts, skipped by reason, content, time and rates.
Rates are worked out from the counts and times, never stored.
"""

import dataclasses
import logging
import math
import statistics

from doc_ingest.settings import DownloadSettings
from doc_ingest.settings import ProcessSettings
from doc_ingest.settings import ParserSettings

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Summary:
	# Run
	tool: str = "doc_ingest"
	doc_types: list[str] = dataclasses.field(default_factory=list)
	dataset: str | None = None
	requested_size: int = 0
	source_exhausted: bool = False
	batches: int = 0

	# Settings (None: the tool does not have that setting group)
	download_settings: DownloadSettings | None = None
	process_settings: ProcessSettings | None = None
	parser_settings: ParserSettings | None = None

	# Counts
	files_read: int = 0
	downloaded: int = 0
	documents_returned: int = 0
	skipped: int = 0
	duplicates: int = 0

	# Skipped, by reason
	download_failed: int = 0
	unsupported_type: int = 0
	prepare_failed: int = 0
	parse_failed: int = 0
	no_text: int = 0
	duplicate_check_failed: int = 0

	# Content of every parsed document (kept, empty or duplicate)
	pages: int = 0
	characters: int = 0

	# Time. document_parse_seconds holds one parse time per parsed document,
	# measured inside its parse worker, so it does not depend on the worker count.
	total_seconds: float = 0.0
	download_seconds: float = 0.0
	parse_seconds: float = 0.0
	document_parse_seconds: list[float] = dataclasses.field(default_factory=list)


def divide_or_none(numerator: float, denominator: float, scale: float) -> float | None:
	"""
	Input: numerator, denominator and a scale (e.g. 1000 for milliseconds).
	Output: numerator / denominator * scale, rounded to 2 decimals, or None when the denominator is 0.
	"""
	if denominator == 0:
		return None
	return round(numerator / denominator * scale, 2)


def percentile_or_none(values: list[float], percent: float) -> float | None:
	"""
	Input: values and a percent (e.g. 95). Output: the nearest-rank percentile of values, or None if values is empty.
	"""
	if len(values) == 0:
		return None
	sorted_values = sorted(values)
	rank = math.ceil(percent / 100 * len(sorted_values))
	return sorted_values[rank - 1]


def settings_to_dict(settings) -> dict | None:
	"""
	Input: a settings dataclass (DownloadSettings, ProcessSettings or ParserSettings) or None.
	Output: its fields as a dict, or None.
	"""
	if settings is None:
		return None
	return dataclasses.asdict(settings)


def summary_to_dict(summary: Summary) -> dict:
	"""
	Input: a Summary. Output: the summary as a dict of groups, ready to print or save as JSON.
	What it does: copies the fields into their groups and works out the rates (None when there is nothing to divide by).
	"""
	documents_parsed = len(summary.document_parse_seconds)
	worker_parse_seconds = sum(summary.document_parse_seconds)

	worker_median_ms_per_document = None
	if documents_parsed > 0:
		worker_median_ms_per_document = round(statistics.median(summary.document_parse_seconds) * 1000, 2)

	worker_p95_ms_per_document = None
	worker_p95_seconds = percentile_or_none(summary.document_parse_seconds, 95)
	if worker_p95_seconds is not None:
		worker_p95_ms_per_document = round(worker_p95_seconds * 1000, 2)

	summary_dict = {
		"run": {
			"tool": summary.tool,
			"doc_types": summary.doc_types,
			"dataset": summary.dataset,
			"requested_size": summary.requested_size,
			"source_exhausted": summary.source_exhausted,
			"batches": summary.batches,
		},
		"settings": {
			"download_settings": settings_to_dict(summary.download_settings),
			"process_settings": settings_to_dict(summary.process_settings),
			"parser_settings": settings_to_dict(summary.parser_settings),
		},
		"counts": {
			"files_read": summary.files_read,
			"downloaded": summary.downloaded,
			"documents_parsed": documents_parsed,
			"documents_returned": summary.documents_returned,
			"skipped": summary.skipped,
			"duplicates": summary.duplicates,
		},
		"skipped_by_reason": {
			"download_failed": summary.download_failed,
			"unsupported_type": summary.unsupported_type,
			"prepare_failed": summary.prepare_failed,
			"parse_failed": summary.parse_failed,
			"no_text": summary.no_text,
			"duplicate_check_failed": summary.duplicate_check_failed,
		},
		"content": {
			"pages": summary.pages,
			"characters": summary.characters,
		},
		"time": {
			"total_seconds": round(summary.total_seconds, 3),
			"download_seconds": round(summary.download_seconds, 3),
			"parse_seconds": round(summary.parse_seconds, 3),
			"worker_parse_seconds": round(worker_parse_seconds, 3),
		},
		# Throughput uses parse_seconds (wall clock, all workers together).
		# worker_* uses each document's own parse time, as if parsed by one worker.
		"rates": {
			"documents_per_second": divide_or_none(documents_parsed, summary.parse_seconds, 1),
			"ms_per_document": divide_or_none(summary.parse_seconds, documents_parsed, 1000),
			"pages_per_second": divide_or_none(summary.pages, summary.parse_seconds, 1),
			"ms_per_page": divide_or_none(summary.parse_seconds, summary.pages, 1000),
			"worker_ms_per_page": divide_or_none(worker_parse_seconds, summary.pages, 1000),
			"worker_median_ms_per_document": worker_median_ms_per_document,
			"worker_p95_ms_per_document": worker_p95_ms_per_document,
		},
	}
	return summary_dict


def print_run_summary(summary: Summary) -> None:
	"""
	Input: the run's Summary. Output: none.
	Logs (INFO) every group of summary_to_dict, one "name: value" line per field.
	"""
	summary_dict = summary_to_dict(summary)

	logger.info("Run summary")
	for group_name, group_values in summary_dict.items():
		logger.info("  %s:", group_name)
		for field_name, field_value in group_values.items():
			# Settings groups are dicts themselves: one line per setting
			if isinstance(field_value, dict):
				logger.info("    %s:", field_name)
				for setting_name, setting_value in field_value.items():
					logger.info("      %s: %s", setting_name, setting_value)
				continue
			logger.info("    %s: %s", field_name, field_value)
