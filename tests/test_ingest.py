"""
End-to-end tests for ingest_documents on a local folder of generated PDFs.
"""

import os
import tempfile
import unittest

import helpers
from doc_ingest.error import IngestError
from doc_ingest.ingest import ingest_documents
from doc_ingest.settings import DownloadSettings
from doc_ingest.settings import ProcessSettings


class TestIngestDocuments(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name
		self.input_folder = os.path.join(self.root, "pdfs")

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
			ingest_result = ingest_documents(
				size,
				self.input_folder,
				download_settings=DownloadSettings(download_workers=2),
				process_settings=ProcessSettings(parse_workers=2),
			)
		logged_output = "\n".join(captured_logs.output)
		return ingest_result.documents, logged_output

	def test_full_run(self):
		"""Good PDFs are kept; copy, blank, broken and encrypted ones are not (the encrypted test PDF opens like in LangChain, but has no text)."""
		documents, printed_output = self.run_ingest(20)

		sources = []
		for document in documents:
			sources.append(os.path.basename(document.metadata.source))
		sources.sort()
		self.assertEqual(sources, ["a_report.pdf", "c_weather.pdf", "d_memo.pdf"])

		self.assertIn("requested_size: 20", printed_output)
		self.assertIn("documents_returned: 3", printed_output)
		self.assertIn("parse_failed: 1", printed_output)
		self.assertIn("no_text: 2", printed_output)
		self.assertIn("duplicates: 1", printed_output)

	def list_temporary_ingest_folders(self):
		"""Returns the names of doc_ingest's temporary folders in the system temp folder."""
		folder_names = []
		for entry_name in os.listdir(tempfile.gettempdir()):
			if entry_name.startswith("doc_ingest_"):
				folder_names.append(entry_name)
		return folder_names

	def test_temporary_folder_removed_after_run(self):
		"""A run leaves nothing on disk, so a second run starts over and returns the same documents."""
		temporary_folders_before = self.list_temporary_ingest_folders()

		documents, printed_output = self.run_ingest(20)
		self.assertEqual(len(documents), 3)
		self.assertEqual(self.list_temporary_ingest_folders(), temporary_folders_before)

		second_documents, second_output = self.run_ingest(20)
		self.assertEqual(len(second_documents), 3)
		self.assertIn("duplicates: 1", second_output)
		self.assertEqual(self.list_temporary_ingest_folders(), temporary_folders_before)

	def test_temporary_folder_removed_after_failed_run(self):
		"""A run that fails validation also removes its temporary folder."""
		temporary_folders_before = self.list_temporary_ingest_folders()

		with self.assertRaises(IngestError):
			ingest_documents(0, self.input_folder)
		self.assertEqual(self.list_temporary_ingest_folders(), temporary_folders_before)


if __name__ == "__main__":
	unittest.main()
