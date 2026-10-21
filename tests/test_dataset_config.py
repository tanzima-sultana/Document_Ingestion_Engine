"""
Tests for dataset/config.py, dataset/hf.py and dataset/document_type.py: input path
kinds, dataset format/name/size, content field and encoding, and Hugging Face helpers.
"""

import base64
import json
import os
import tempfile
import unittest

import helpers
from doc_ingest.dataset import config as dataset_config
from doc_ingest.dataset import hf as dataset_hf
from doc_ingest.dataset import document_type


class TestPathKinds(unittest.TestCase):

	def test_is_url(self):
		"""A URL needs http/https and a host."""
		self.assertTrue(dataset_hf.is_url("https://x.com/a.pdf"))
		self.assertFalse(dataset_hf.is_url("https://"))
		self.assertFalse(dataset_hf.is_url("data/a.pdf"))

	def test_hugging_face_name_shape(self):
		"""Only "owner/name" counts as a Hugging Face name."""
		self.assertTrue(dataset_hf.has_hugging_face_name_shape("owner/name"))
		self.assertFalse(dataset_hf.has_hugging_face_name_shape("imdb"))
		self.assertFalse(dataset_hf.has_hugging_face_name_shape("a/b/c"))

	def test_hugging_face_page_url_to_name(self):
		"""A dataset page URL becomes "owner/name"; file links stay URLs."""
		get_name = dataset_hf.get_hugging_face_dataset_name_from_url
		self.assertEqual(get_name("https://huggingface.co/datasets/owner/name"), "owner/name")
		self.assertEqual(get_name("https://huggingface.co/datasets/owner/name/tree/main"), "owner/name")
		self.assertIsNone(get_name("https://huggingface.co/datasets/owner/name/resolve/main/a.jsonl"))
		self.assertIsNone(get_name("https://example.com/datasets/owner/name"))

	def test_hugging_face_file_url(self):
		"""An hf:// file path becomes a resolve download URL."""
		url = dataset_hf.get_hugging_face_file_url("hf://datasets/owner/name@abc123/dir/my file.pdf")
		self.assertEqual(url, "https://huggingface.co/datasets/owner/name/resolve/abc123/dir/my%20file.pdf")

	def test_unwrap_file_values(self):
		"""File dicts become bytes or their hf:// path; zip entries stay as they are."""
		row = {
			"embedded": {"bytes": b"%PDF-1.4", "path": "a.pdf"},
			"linked": {"bytes": None, "path": "hf://datasets/owner/name@rev/a.pdf"},
			"zipped": {"bytes": None, "path": "zip://a.docx::hf://datasets/owner/name@rev/b.zip"},
			"label": 3,
		}
		dataset_hf.unwrap_file_values(row)
		self.assertEqual(row["embedded"], b"%PDF-1.4")
		self.assertEqual(row["linked"], "hf://datasets/owner/name@rev/a.pdf")
		self.assertIsInstance(row["zipped"], dict)
		self.assertEqual(row["label"], 3)


class TestContent(unittest.TestCase):

	def test_content_encoding(self):
		"""Each kind of content value gets the right encoding."""
		encoded_pdf = base64.b64encode(b"%PDF-1.4 some pdf body here").decode("ascii")
		self.assertEqual(dataset_config.get_content_encoding(b"raw"), "bytes")
		self.assertEqual(dataset_config.get_content_encoding("hf://datasets/owner/name@rev/a.pdf"), "hf_file")
		self.assertEqual(dataset_config.get_content_encoding(encoded_pdf), "base64")
		self.assertEqual(dataset_config.get_content_encoding("plain words here"), "text")

	def test_content_encoding_rejects_other_values(self):
		"""A zip entry, a number or a web link cannot be used as content."""
		with self.assertRaises(ValueError):
			dataset_config.get_content_encoding({"path": "zip://a::hf://b", "bytes": None})
		with self.assertRaises(ValueError):
			dataset_config.get_content_encoding(42)
		with self.assertRaises(ValueError):
			dataset_config.get_content_encoding("https://x.com/a.pdf")

	def test_document_type_from_bytes(self):
		"""Leading bytes decide the document type."""
		self.assertEqual(document_type.get_document_type_from_bytes(b"%PDF-1.4"), "pdf")
		self.assertEqual(document_type.get_document_type_from_bytes(b"<html><body>x</body></html>"), "html")
		self.assertEqual(document_type.get_document_type_from_bytes(b"just text"), "txt")


class TestDatasetConfig(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name

	def tearDown(self):
		self.temporary_folder.cleanup()

	def test_mixed_folder(self):
		"""A folder of mixed documents has format "folder" and counts supported files only."""
		folder = os.path.join(self.root, "mixed")
		helpers.write_file(folder, "a.pdf", helpers.make_report_pdf("a", 1))
		helpers.write_file(folder, "b.txt", b"hello")
		helpers.write_file(folder, "c.xyz", b"junk")
		config = dataset_config.get_dataset_config(folder)
		self.assertEqual(config.format, "folder")
		self.assertEqual(config.path_type, "local")
		self.assertIsNone(config.content_field)
		self.assertEqual(config.size, 2)

	def test_jsonl_file(self):
		"""A JSONL file is a container; its content field is found."""
		records = [{"id": 1, "text": "hello world"}, {"id": 2, "text": "second"}]
		lines = ""
		for record in records:
			lines = lines + json.dumps(record) + "\n"
		jsonl_path = helpers.write_file(self.root, "docs.jsonl", lines.encode("utf-8"))
		config = dataset_config.get_dataset_config(jsonl_path)
		self.assertEqual(config.format, "jsonl")
		self.assertEqual(config.content_field, "text")
		self.assertEqual(config.size, -1)

	def test_single_pdf_file(self):
		"""A single PDF file has its extension as format and size 1."""
		pdf_path = helpers.write_file(self.root, "one.pdf", helpers.make_report_pdf("a", 1))
		config = dataset_config.get_dataset_config(pdf_path)
		self.assertEqual(config.format, "pdf")
		self.assertEqual(config.size, 1)

	def test_dataset_name_is_unique_per_path(self):
		"""Same folder name in two places gives two names; a trailing slash does not."""
		first_folder = os.path.join(self.root, "one", "data")
		second_folder = os.path.join(self.root, "two", "data")
		helpers.write_file(first_folder, "a.txt", b"x")
		helpers.write_file(second_folder, "a.txt", b"x")
		first_name = dataset_config.get_dataset_name(first_folder)
		second_name = dataset_config.get_dataset_name(second_folder)
		self.assertNotEqual(first_name, second_name)
		self.assertTrue(first_name.startswith("data_"))
		self.assertEqual(dataset_config.get_dataset_name(first_folder + "/"), first_name)


if __name__ == "__main__":
	unittest.main()
