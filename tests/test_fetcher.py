"""
Tests for fetching/fetcher.py and fetching/local.py: reading rows one at a time,
the document type check, source path and counts.
"""

import base64
import json
import os
import tempfile
import unittest

import helpers
from doc_ingest.error import IngestError
from doc_ingest.fetching.local import LocalFetcher
from doc_ingest.settings import FetchSettings


class TestLocalFetcher(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name
		self.output_path = os.path.join(self.root, "out")

	def tearDown(self):
		self.temporary_folder.cleanup()

	def make_fetcher(self, input_path):
		"""Returns a LocalFetcher for PDFs."""
		return LocalFetcher(input_path, self.output_path, FetchSettings(document_type="pdf"))

	def test_mixed_folder(self):
		"""Only PDFs are kept; every other file is counted as wrong_doc_type and not read."""
		folder = os.path.join(self.root, "mixed")
		pdf_path = helpers.write_file(folder, "a.pdf", helpers.make_report_pdf("a", 1))
		helpers.write_file(folder, "b.md", b"# title")
		helpers.write_file(folder, "c.xyz", b"junk")
		fetcher = self.make_fetcher(folder)
		raw_documents = list(fetcher.fetch_documents())

		self.assertEqual(len(raw_documents), 1)
		self.assertEqual(raw_documents[0].type, "pdf")
		self.assertEqual(raw_documents[0].source, pdf_path)
		self.assertEqual(fetcher.summary.total_fetched, 3)
		self.assertEqual(fetcher.summary.fetch_success, 1)
		self.assertEqual(fetcher.summary.wrong_doc_type, 2)
		self.assertEqual(fetcher.summary.fetch_failed, 0)

	def test_local_file_is_not_copied(self):
		"""A local file is parsed from its original path; nothing is saved to the storage folder."""
		folder = os.path.join(self.root, "originals")
		pdf_path = helpers.write_file(folder, "a.pdf", helpers.make_report_pdf("a", 1))
		raw_documents = list(self.make_fetcher(folder).fetch_documents())
		self.assertEqual(raw_documents[0].raw_path, pdf_path)
		self.assertFalse(os.path.exists(self.output_path))

	def test_fake_pdf_reaches_the_parser(self):
		"""A file with the right extension is not checked further here; the parser rejects it."""
		folder = os.path.join(self.root, "fake")
		helpers.write_file(folder, "fake.pdf", b"not really a pdf")
		fetcher = self.make_fetcher(folder)
		self.assertEqual(len(list(fetcher.fetch_documents())), 1)
		self.assertEqual(fetcher.summary.wrong_doc_type, 0)

	def test_documents_come_one_at_a_time(self):
		"""Rows are only read when the next document is asked for."""
		folder = os.path.join(self.root, "lazy")
		for file_index in range(3):
			helpers.write_file(folder, f"{file_index}.pdf", helpers.make_report_pdf(str(file_index), 1))
		fetcher = self.make_fetcher(folder)
		documents = fetcher.fetch_documents()
		first_document = next(documents)
		self.assertTrue(first_document.source.endswith("0.pdf"))
		self.assertEqual(fetcher.summary.total_fetched, 1)

	def test_jsonl_records(self):
		"""A PDF record is kept; text is wrong_doc_type; bad and linked records are fetch_failed."""
		pdf_bytes = helpers.make_report_pdf("a", 1)
		records = [
			{"text": base64.b64encode(pdf_bytes).decode("ascii")},
			{"text": "plain words in this record"},
			{"text": 42},
			{"text": "hf://datasets/owner/name@rev/a.pdf"},
		]
		lines = ""
		for record in records:
			lines = lines + json.dumps(record) + "\n"
		jsonl_path = helpers.write_file(self.root, "docs.jsonl", lines.encode("utf-8"))
		fetcher = self.make_fetcher(jsonl_path)
		raw_documents = list(fetcher.fetch_documents())

		self.assertEqual(fetcher.summary.total_fetched, 4)
		self.assertEqual(fetcher.summary.fetch_success, 2)
		self.assertEqual(fetcher.summary.wrong_doc_type, 1)
		self.assertEqual(fetcher.summary.fetch_failed, 2)
		self.assertEqual(len(raw_documents), 1)
		self.assertEqual(raw_documents[0].source, jsonl_path + "#0")
		self.assertTrue(raw_documents[0].raw_path.startswith(self.output_path))
		self.assertTrue(os.path.exists(raw_documents[0].raw_path))

	def test_source_path_keeps_row_number(self):
		"""A record's source uses its position in the dataset."""
		encoded_pdf = base64.b64encode(helpers.make_report_pdf("a", 1)).decode("ascii")
		lines = json.dumps({"text": "first words of the file"}) + "\n" + json.dumps({"text": encoded_pdf}) + "\n"
		jsonl_path = helpers.write_file(self.root, "docs.jsonl", lines.encode("utf-8"))
		raw_documents = list(self.make_fetcher(jsonl_path).fetch_documents())
		self.assertEqual(raw_documents[0].source, jsonl_path + "#1")

	def test_bad_json_line_is_counted(self):
		"""A line that is not JSON is skipped and counted; the next record is still read."""
		encoded_pdf = base64.b64encode(helpers.make_report_pdf("a", 1)).decode("ascii")
		lines = json.dumps({"text": encoded_pdf}) + "\n" + "not json\n" + json.dumps({"text": encoded_pdf}) + "\n"
		jsonl_path = helpers.write_file(self.root, "docs.jsonl", lines.encode("utf-8"))
		fetcher = self.make_fetcher(jsonl_path)
		self.assertEqual(len(list(fetcher.fetch_documents())), 2)
		self.assertEqual(fetcher.summary.fetch_failed, 1)

	def test_bad_first_json_line_does_not_stop_the_run(self):
		"""A bad first line is passed over when finding the content field, then counted as fetch_failed."""
		encoded_pdf = base64.b64encode(helpers.make_report_pdf("a", 1)).decode("ascii")
		lines = "not json\n" + json.dumps({"text": encoded_pdf}) + "\n"
		jsonl_path = helpers.write_file(self.root, "docs.jsonl", lines.encode("utf-8"))
		fetcher = self.make_fetcher(jsonl_path)

		self.assertEqual(fetcher.content_field, "text")
		self.assertEqual(len(list(fetcher.fetch_documents())), 1)
		self.assertEqual(fetcher.summary.fetch_failed, 1)

	def test_unusable_record_files_give_a_clear_error(self):
		"""No usable record, no content field, or broken JSON stops with an IngestError."""
		bad_lines_path = helpers.write_file(self.root, "bad.jsonl", b"not json\nalso not json\n")
		no_field_path = helpers.write_file(self.root, "no_field.jsonl", b'{"id": 1}\n')
		broken_json_path = helpers.write_file(self.root, "broken.json", b"{not json")
		empty_list_path = helpers.write_file(self.root, "empty.json", b"[]")

		for bad_path in [bad_lines_path, no_field_path, broken_json_path, empty_list_path]:
			with self.assertRaises(IngestError):
				self.make_fetcher(bad_path)

	def test_finds_how_a_dataset_is_stored(self):
		"""Document files have no content field; JSONL has one, and a folder of only JSONL is read as records."""
		folder = os.path.join(self.root, "files")
		helpers.write_file(folder, "a.pdf", b"%PDF")
		self.assertIsNone(self.make_fetcher(folder).content_field)

		lines = json.dumps({"id": 1, "text": "hello world"}) + "\n"
		records_folder = os.path.join(self.root, "records")
		jsonl_path = helpers.write_file(records_folder, "docs.jsonl", lines.encode("utf-8"))
		self.assertEqual(self.make_fetcher(jsonl_path).content_field, "text")
		self.assertEqual(self.make_fetcher(records_folder).content_field, "text")

	def test_stray_json_file_does_not_change_a_pdf_folder(self):
		"""A JSON file next to PDFs is counted as wrong_doc_type, and the PDFs are read."""
		folder = os.path.join(self.root, "stray")
		helpers.write_file(folder, "a.pdf", helpers.make_report_pdf("a", 1))
		helpers.write_file(os.path.join(folder, "logs"), "summary.json", b'{"run": {"size": 1}}')
		fetcher = self.make_fetcher(folder)
		self.assertEqual(len(list(fetcher.fetch_documents())), 1)
		self.assertEqual(fetcher.summary.wrong_doc_type, 1)

	def test_doc_id_from_bytes(self):
		"""The same bytes give the same doc id."""
		folder = os.path.join(self.root, "copies")
		helpers.write_file(folder, "a.pdf", b"%PDF same")
		helpers.write_file(folder, "b.pdf", b"%PDF same")
		raw_documents = list(self.make_fetcher(folder).fetch_documents())
		self.assertEqual(raw_documents[0].id, raw_documents[1].id)


if __name__ == "__main__":
	unittest.main()
