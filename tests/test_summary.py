"""
Tests for summary.py: groups, rates worked out from counts and times, and None when there is nothing to divide by.
"""

import json
import unittest

from doc_ingest.settings import DownloadSettings
from doc_ingest.summary import Summary
from doc_ingest.summary import summary_to_dict


class TestSummary(unittest.TestCase):

	def test_rates(self):
		"""Rates come from the counts and times; worker rates from each document's own parse time."""
		summary = Summary()
		summary.download_settings = DownloadSettings(download_workers=4)
		summary.pages = 10
		summary.parse_seconds = 2.0
		summary.document_parse_seconds = [1.0, 2.0, 3.0, 4.0]

		summary_dict = summary_to_dict(summary)
		self.assertEqual(summary_dict["counts"]["documents_parsed"], 4)
		self.assertEqual(summary_dict["settings"]["download_settings"]["download_workers"], 4)
		self.assertIsNone(summary_dict["settings"]["parser_settings"])
		self.assertEqual(summary_dict["rates"]["documents_per_second"], 2.0)
		self.assertEqual(summary_dict["rates"]["ms_per_page"], 200.0)
		self.assertEqual(summary_dict["rates"]["worker_ms_per_page"], 1000.0)
		self.assertEqual(summary_dict["rates"]["worker_median_ms_per_document"], 2500.0)
		self.assertEqual(summary_dict["rates"]["worker_p95_ms_per_document"], 4000.0)

	def test_empty_summary(self):
		"""With nothing parsed, every rate is None and the dict can still be saved as JSON."""
		summary_dict = summary_to_dict(Summary())
		for rate_value in summary_dict["rates"].values():
			self.assertIsNone(rate_value)
		json.dumps(summary_dict)


if __name__ == "__main__":
	unittest.main()
