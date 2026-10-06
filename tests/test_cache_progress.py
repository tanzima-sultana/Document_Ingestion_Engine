"""
Tests for cache.py and progress.py: save, load, missing and damaged files.
"""

import os
import tempfile
import unittest

from doc_ingest import cache
from doc_ingest import progress
from doc_ingest.schema import Document
from doc_ingest.schema import Metadata


class TestCache(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.output_path = self.temporary_folder.name

	def tearDown(self):
		self.temporary_folder.cleanup()

	def test_save_and_load(self):
		"""A saved document loads back the same."""
		metadata = Metadata(source="a.pdf", file_size_bytes=10, content_hash="h")
		document = Document(id="doc1", type="pdf", text="hello", metadata=metadata)
		cache.save_processed_document(self.output_path, "ds", document)
		self.assertEqual(cache.load_processed_document(self.output_path, "ds", "doc1"), document)

	def test_missing_is_none(self):
		"""A document never saved loads as None."""
		self.assertIsNone(cache.load_processed_document(self.output_path, "ds", "nope"))

	def test_damaged_is_none(self):
		"""A damaged cache file loads as None instead of raising."""
		damaged_path = cache.get_processed_document_path(self.output_path, "ds", "bad")
		os.makedirs(os.path.dirname(damaged_path), exist_ok=True)
		with open(damaged_path, "w", encoding="utf-8") as damaged_file:
			damaged_file.write("{not json")
		self.assertIsNone(cache.load_processed_document(self.output_path, "ds", "bad"))


class TestProgress(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.output_path = self.temporary_folder.name

	def tearDown(self):
		self.temporary_folder.cleanup()

	def test_empty_when_not_saved(self):
		"""No progress file gives an empty Progress."""
		loaded_progress = progress.load_progress(self.output_path, "ds")
		self.assertEqual(loaded_progress.raw_data_count, 0)
		self.assertEqual(loaded_progress.processed_doc_ids, [])

	def test_save_and_load(self):
		"""Saved progress loads back the same."""
		saved_progress = progress.make_progress("ds", 7, ["a", "b"], ["c"])
		progress.save_progress(self.output_path, "ds", saved_progress)
		self.assertEqual(progress.load_progress(self.output_path, "ds"), saved_progress)

	def test_wrong_dataset_raises(self):
		"""A progress file of another dataset raises ValueError."""
		other_progress = progress.make_progress("other", 1, [], [])
		progress.save_progress(self.output_path, "ds", other_progress)
		with self.assertRaises(ValueError):
			progress.load_progress(self.output_path, "ds")

	def test_damaged_raises(self):
		"""A damaged progress file raises ValueError."""
		progress_path = progress.get_progress_path(self.output_path, "ds")
		os.makedirs(os.path.dirname(progress_path), exist_ok=True)
		with open(progress_path, "w", encoding="utf-8") as progress_file:
			progress_file.write("{not json")
		with self.assertRaises(ValueError):
			progress.load_progress(self.output_path, "ds")


if __name__ == "__main__":
	unittest.main()
