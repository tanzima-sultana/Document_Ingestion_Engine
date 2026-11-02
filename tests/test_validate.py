"""
Tests for validate.py (local paths only, no network).
"""

import os
import tempfile
import unittest

import helpers
from doc_ingest import validate
from doc_ingest.error import IngestError
from doc_ingest.settings import Settings


class TestValidateLocal(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name
		self.input_folder = os.path.join(self.root, "input")
		helpers.write_file(self.input_folder, "a.pdf", b"%PDF-1.4")

	def tearDown(self):
		self.temporary_folder.cleanup()

	def validate_with_default_settings(self, path, size):
		"""Runs validate_local for PDFs with default settings."""
		validate.validate_local(path, size, "pdf", Settings())

	def validate_settings(self, settings):
		"""Runs validate_local with valid path, size and type and the given settings."""
		validate.validate_local(self.input_folder, 5, "pdf", settings)

	def test_valid_inputs_pass(self):
		"""Valid path, size and type raise nothing."""
		self.validate_with_default_settings(self.input_folder, 5)

	def test_bad_size(self):
		"""Size must be a positive whole number, not a boolean."""
		with self.assertRaises(TypeError):
			self.validate_with_default_settings(self.input_folder, True)
		with self.assertRaises(TypeError):
			self.validate_with_default_settings(self.input_folder, 2.5)
		with self.assertRaises(ValueError):
			self.validate_with_default_settings(self.input_folder, 0)

	def test_bad_path(self):
		"""Empty, missing, URL and Hugging Face name paths fail."""
		with self.assertRaises(ValueError):
			self.validate_with_default_settings("   ", 5)
		with self.assertRaises(ValueError):
			self.validate_with_default_settings(os.path.join(self.root, "missing"), 5)
		with self.assertRaises(IngestError):
			self.validate_with_default_settings("https://x.com/a.pdf", 5)
		with self.assertRaises(IngestError):
			self.validate_with_default_settings("owner/name", 5)
		with self.assertRaises(TypeError):
			self.validate_with_default_settings(None, 5)

	def test_path_without_documents(self):
		"""A folder or single file with nothing of the type fails; JSONL/JSON is checked when read."""
		folder = os.path.join(self.root, "no_pdfs")
		text_path = helpers.write_file(folder, "notes.txt", b"hello")
		with self.assertRaises(IngestError):
			self.validate_with_default_settings(folder, 5)
		with self.assertRaises(IngestError):
			self.validate_with_default_settings(text_path, 5)

		jsonl_path = helpers.write_file(folder, "docs.jsonl", b'{"text": "hello"}\n')
		self.validate_with_default_settings(folder, 5)
		self.validate_with_default_settings(jsonl_path, 5)

	def test_document_type(self):
		"""document_type must be text and have a parser."""
		with self.assertRaises(IngestError):
			validate.validate_local(self.input_folder, 5, "docx", Settings())
		with self.assertRaises(TypeError):
			validate.validate_local(self.input_folder, 5, None, Settings())

	def test_valid_settings_pass(self):
		"""Default settings, and the lowest allowed values, raise nothing."""
		self.validate_settings(Settings())
		self.validate_settings(Settings(dedup_threshold=1, timeout_seconds=1))

	def test_bad_whole_number_settings(self):
		"""The timeout must be a whole number of at least 1."""
		with self.assertRaises(IngestError):
			self.validate_settings(Settings(timeout_seconds=0))
		with self.assertRaises(TypeError):
			self.validate_settings(Settings(timeout_seconds=True))
		with self.assertRaises(TypeError):
			self.validate_settings(Settings(timeout_seconds=1.5))

	def test_bad_dedup_threshold(self):
		"""The threshold must be a number greater than 0 and at most 1."""
		with self.assertRaises(IngestError):
			self.validate_settings(Settings(dedup_threshold=0))
		with self.assertRaises(IngestError):
			self.validate_settings(Settings(dedup_threshold=1.5))
		with self.assertRaises(TypeError):
			self.validate_settings(Settings(dedup_threshold="0.9"))


if __name__ == "__main__":
	unittest.main()
