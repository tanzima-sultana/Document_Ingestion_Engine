"""
Tests for dataset/raw_data.py: reading rows, per-document type, source path
and counts in a batch.
"""

import base64
import json
import os
import tempfile
import unittest

import helpers
from doc_ingest.dataset.config import get_dataset_config
from doc_ingest.dataset.raw_data import RawDataFetcher
from doc_ingest.settings import DownloadSettings


class TestRawDataFetcher(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name
		self.output_path = os.path.join(self.root, "out")

	def tearDown(self):
		self.temporary_folder.cleanup()

	def fetch_all(self, input_path):
		"""Fetches one batch of up to 100 rows and returns it."""
		config = get_dataset_config(input_path)
		fetcher = RawDataFetcher(input_path, self.output_path, config, DownloadSettings(download_workers=4))
		row_iterator = fetcher.get_iterator()
		return fetcher.fetch_raw_batch(row_iterator, 100)

	def test_mixed_folder(self):
		"""Each file gets its own type; unsupported files are not listed."""
		folder = os.path.join(self.root, "mixed")
		pdf_path = helpers.write_file(folder, "a.pdf", helpers.make_report_pdf("a", 1))
		helpers.write_file(folder, "b.md", b"# title")
		helpers.write_file(folder, "c.xyz", b"junk")
		batch = self.fetch_all(folder)

		self.assertEqual(batch.rows_read, 2)
		self.assertEqual(batch.downloaded, 2)
		self.assertTrue(batch.source_exhausted)

		types_by_source = {}
		for raw_data in batch.raw_items:
			types_by_source[os.path.basename(raw_data.source_path)] = raw_data.doc_type
			self.assertTrue(os.path.exists(raw_data.raw_path))
		self.assertEqual(types_by_source, {"a.pdf": "pdf", "b.md": "md"})
		self.assertEqual(batch.raw_items[0].source_path, pdf_path)

	def test_jsonl_with_mixed_encodings(self):
		"""Base64 and text records decode; a bad record counts as read but not downloaded."""
		pdf_bytes = helpers.make_report_pdf("a", 1)
		records = [
			{"text": base64.b64encode(pdf_bytes).decode("ascii")},
			{"text": "plain words in this record"},
			{"text": 42},
		]
		lines = ""
		for record in records:
			lines = lines + json.dumps(record) + "\n"
		jsonl_path = helpers.write_file(self.root, "docs.jsonl", lines.encode("utf-8"))
		batch = self.fetch_all(jsonl_path)

		self.assertEqual(batch.rows_read, 3)
		self.assertEqual(batch.downloaded, 2)
		self.assertEqual(batch.raw_items[0].doc_type, "pdf")
		self.assertEqual(batch.raw_items[1].doc_type, "txt")
		self.assertEqual(batch.raw_items[0].source_path, jsonl_path + "#0")
		self.assertEqual(batch.raw_items[1].source_path, jsonl_path + "#1")

	def test_doc_id_from_bytes(self):
		"""The same bytes give the same doc id."""
		folder = os.path.join(self.root, "copies")
		helpers.write_file(folder, "a.txt", b"same")
		helpers.write_file(folder, "b.txt", b"same")
		batch = self.fetch_all(folder)
		self.assertEqual(batch.raw_items[0].doc_id, batch.raw_items[1].doc_id)


if __name__ == "__main__":
	unittest.main()
