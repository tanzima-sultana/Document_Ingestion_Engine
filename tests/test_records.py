"""
Tests for fetching/records.py, fetching/document_type.py and fetching/huggingface.py:
content encoding, type checks and Hugging Face helpers.
"""

import base64
import unittest

from doc_ingest.fetching import huggingface as dataset_hf
from doc_ingest.fetching import document_type
from doc_ingest.fetching import records


class TestPathKinds(unittest.TestCase):

	def test_is_url(self):
		"""A URL needs http/https and a host."""
		self.assertTrue(records.is_url("https://x.com/a.pdf"))
		self.assertFalse(records.is_url("https://"))
		self.assertFalse(records.is_url("data/a.pdf"))

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
		self.assertEqual(records.get_content_encoding(b"raw"), "bytes")
		self.assertEqual(records.get_content_encoding("hf://datasets/owner/name@rev/a.pdf"), "hf_file")
		self.assertEqual(records.get_content_encoding(encoded_pdf), "base64")
		self.assertEqual(records.get_content_encoding("plain words here"), "text")

	def test_content_encoding_rejects_other_values(self):
		"""A zip entry, a number or a web link cannot be used as content."""
		with self.assertRaises(ValueError):
			records.get_content_encoding({"path": "zip://a::hf://b", "bytes": None})
		with self.assertRaises(ValueError):
			records.get_content_encoding(42)
		with self.assertRaises(ValueError):
			records.get_content_encoding("https://x.com/a.pdf")

	def test_decode_content_value(self):
		"""Each encoding gives the document's bytes; an "hf_file" link has no bytes to decode."""
		encoded_text = base64.b64encode(b"hello").decode("ascii")
		self.assertEqual(records.decode_content_value(encoded_text, "base64"), b"hello")
		self.assertEqual(records.decode_content_value(b"hello", "bytes"), b"hello")
		self.assertEqual(records.decode_content_value("hello", "text"), b"hello")
		with self.assertRaises(ValueError):
			records.decode_content_value("hf://datasets/owner/name@rev/a.pdf", "hf_file")

	def test_file_matches_document_type(self):
		"""The extension decides; upper case is fine and no extension does not match."""
		self.assertTrue(document_type.file_matches_document_type("a.PDF", "pdf"))
		self.assertFalse(document_type.file_matches_document_type("a.txt", "pdf"))
		self.assertFalse(document_type.file_matches_document_type("a", "pdf"))

	def test_bytes_match_document_type(self):
		"""A PDF header near the start matches, with or without bytes before it."""
		self.assertTrue(document_type.bytes_match_document_type(b"%PDF-1.4", "pdf"))
		self.assertTrue(document_type.bytes_match_document_type(b"\n\n%PDF-1.4", "pdf"))
		self.assertFalse(document_type.bytes_match_document_type(b"x" * 2000 + b"%PDF", "pdf"))
		self.assertFalse(document_type.bytes_match_document_type(b"just text", "pdf"))
		with self.assertRaises(ValueError):
			document_type.bytes_match_document_type(b"PK", "docx")


if __name__ == "__main__":
	unittest.main()
