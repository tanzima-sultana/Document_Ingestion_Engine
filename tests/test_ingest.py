"""
End-to-end tests for ingest_documents on a local folder of generated PDFs.
"""

import json
import os
import tempfile
import unittest
import unittest.mock

import helpers
from doc_ingest.dataset_config import get_dataset_name
from doc_ingest.ingest import ingest_documents


class TestIngestDocuments(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name
		self.input_folder = os.path.join(self.root, "pdfs")
		self.output_path = os.path.join(self.root, "out")

		report = helpers.make_report_pdf("finance", 4)
		helpers.write_file(self.input_folder, "a_report.pdf", report)
		helpers.write_file(self.input_folder, "b_report_copy.pdf", report)
		helpers.write_file(self.input_folder, "c_weather.pdf", helpers.make_report_pdf("weather", 3))
		helpers.write_file(self.input_folder, "d_memo.pdf", helpers.make_pdf([["Short memo", "Meeting moved to Friday."]], {}))
		helpers.write_file(self.input_folder, "e_blank.pdf", helpers.make_pdf([[]], {}))
		helpers.write_file(self.input_folder, "f_broken.pdf", b"%PDF-1.4\nnot really a pdf")
		helpers.write_file(self.input_folder, "g_locked.pdf", helpers.make_encrypted_pdf())

	def tearDown(self):
		self.temporary_folder.cleanup()

	def run_ingest(self, size):
		"""Runs ingest_documents quietly; returns (documents, logged output)."""
		with self.assertLogs("doc_ingest", level="INFO") as captured_logs:
			with unittest.mock.patch("doc_ingest.cache.get_storage_path", return_value=self.output_path):
				ingest_result = ingest_documents(size, self.input_folder, download_workers=2, parse_workers=2)
		logged_output = "\n".join(captured_logs.output)
		return ingest_result.documents, logged_output

	def read_progress(self):
		"""Reads the dataset's progress.json."""
		dataset_name = get_dataset_name(self.input_folder)
		progress_path = os.path.join(self.output_path, dataset_name, "progress.json")
		with open(progress_path, encoding="utf-8") as progress_file:
			return json.load(progress_file)

	def test_full_run(self):
		"""Good PDFs are kept; copy, blank, broken and encrypted ones are not."""
		documents, printed_output = self.run_ingest(20)

		sources = []
		for document in documents:
			sources.append(os.path.basename(document.metadata.source))
		sources.sort()
		self.assertEqual(sources, ["a_report.pdf", "c_weather.pdf", "d_memo.pdf"])

		saved_progress = self.read_progress()
		self.assertEqual(saved_progress["raw_data_count"], 7)
		self.assertEqual(len(saved_progress["processed_doc_ids"]), 3)
		self.assertEqual(len(saved_progress["skipped_doc_ids"]), 3)

		self.assertIn("Requested 20 document(s), returned 3.", printed_output)
		self.assertIn("Skipped 2 document(s) that failed in parsing.", printed_output)
		self.assertIn("Skipped 1 document(s) with no text.", printed_output)
		self.assertIn("Skipped 1 document(s) due to duplicate detection.", printed_output)

	def test_resume_from_cache(self):
		"""A second, smaller run loads documents from the cache."""
		self.run_ingest(20)
		documents, printed_output = self.run_ingest(2)
		self.assertEqual(len(documents), 2)
		self.assertIn("Documents 2 have been loaded from cache", printed_output)
		self.assertIn("Batches: 0", printed_output)

	def test_resume_continues_after_read_rows(self):
		"""A run that stops early continues from where it stopped."""
		first_documents, first_output = self.run_ingest(1)
		self.assertEqual(len(first_documents), 1)

		second_documents, second_output = self.run_ingest(20)
		self.assertEqual(len(second_documents), 3)
		self.assertIn("Documents 1 have been loaded from cache", second_output)
		self.assertEqual(self.read_progress()["raw_data_count"], 7)


if __name__ == "__main__":
	unittest.main()
