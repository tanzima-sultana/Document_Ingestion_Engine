"""
Tests for summary.py: groups and saving as JSON.
"""

import json
import unittest

from doc_ingest.settings import Settings
from doc_ingest.summary import Summary


class TestSummary(unittest.TestCase):

	def test_groups(self):
		"""Counts, settings and the total time are in their groups."""
		summary = Summary()
		summary.settings = Settings(timeout_seconds=30)
		summary.total_parsed = 4
		summary.total_seconds = 2.5

		summary_dict = summary.to_dict()
		self.assertEqual(summary_dict["parsing"]["total_parsed"], 4)
		self.assertEqual(summary_dict["settings"]["timeout_seconds"], 30)
		self.assertEqual(summary_dict["run"]["total_seconds"], 2.5)
		self.assertNotIn("rates", summary_dict)
		self.assertNotIn("time", summary_dict)

	def test_empty_summary(self):
		"""An empty summary can still be saved as JSON."""
		json.dumps(Summary().to_dict())


if __name__ == "__main__":
	unittest.main()
