"""
Tests for validate.py (local paths only, no network).
"""

import os
import tempfile
import unittest

from doc_ingest import validate
from doc_ingest.error import IngestError
from doc_ingest.settings import DownloadSettings
from doc_ingest.settings import ProcessSettings
from doc_ingest.settings import ParserSettings


class TestValidateInputs(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name
		self.input_folder = os.path.join(self.root, "input")
		os.makedirs(self.input_folder)

	def tearDown(self):
		self.temporary_folder.cleanup()

	def validate_with_default_settings(self, size, input_path):
		"""Runs validate_inputs with default download and process settings."""
		validate.validate_inputs(size, input_path, DownloadSettings(), ProcessSettings(), ParserSettings())

	def validate_settings(self, download_settings, process_settings):
		"""Runs validate_inputs with valid size and input path and the given settings."""
		validate.validate_inputs(5, self.input_folder, download_settings, process_settings, ParserSettings())

	def test_valid_inputs_pass(self):
		"""Valid size and input path raise nothing."""
		self.validate_with_default_settings(5, self.input_folder)

	def test_bad_size(self):
		"""Size must be a positive whole number, not a boolean."""
		with self.assertRaises(TypeError):
			self.validate_with_default_settings(True, self.input_folder)
		with self.assertRaises(TypeError):
			self.validate_with_default_settings(2.5, self.input_folder)
		with self.assertRaises(ValueError):
			self.validate_with_default_settings(0, self.input_folder)

	def test_bad_input_path(self):
		"""Empty or missing local input paths fail."""
		with self.assertRaises(ValueError):
			self.validate_with_default_settings(5, "   ")
		with self.assertRaises(ValueError):
			self.validate_with_default_settings(5, os.path.join(self.root, "missing"))

	def test_valid_settings_pass(self):
		"""Default settings, and parse_workers left as None, raise nothing."""
		self.validate_settings(DownloadSettings(), ProcessSettings(parse_workers=None))
		self.validate_settings(DownloadSettings(download_workers=1, max_batch_rows=1), ProcessSettings(parse_workers=1, dedup_threshold=1))

	def test_bad_whole_number_settings(self):
		"""Worker counts, batch size and timeout must be whole numbers of at least 1."""
		with self.assertRaises(IngestError):
			self.validate_settings(DownloadSettings(download_workers=0), ProcessSettings())
		with self.assertRaises(IngestError):
			self.validate_settings(DownloadSettings(max_batch_rows=0), ProcessSettings())
		with self.assertRaises(IngestError):
			self.validate_settings(DownloadSettings(), ProcessSettings(parse_workers=0))
		with self.assertRaises(IngestError):
			validate.validate_inputs(5, self.input_folder, DownloadSettings(), ProcessSettings(), ParserSettings(parse_timeout_seconds=0))
		with self.assertRaises(TypeError):
			self.validate_settings(DownloadSettings(download_workers=True), ProcessSettings())
		with self.assertRaises(TypeError):
			validate.validate_inputs(5, self.input_folder, DownloadSettings(), ProcessSettings(), ParserSettings(parse_timeout_seconds=1.5))

	def test_bad_hugging_face_split(self):
		"""The split must be non-empty text."""
		with self.assertRaises(IngestError):
			self.validate_settings(DownloadSettings(hugging_face_split="  "), ProcessSettings())
		with self.assertRaises(TypeError):
			self.validate_settings(DownloadSettings(hugging_face_split=None), ProcessSettings())

	def test_bad_dedup_threshold(self):
		"""The threshold must be a number greater than 0 and at most 1."""
		with self.assertRaises(IngestError):
			self.validate_settings(DownloadSettings(), ProcessSettings(dedup_threshold=0))
		with self.assertRaises(IngestError):
			self.validate_settings(DownloadSettings(), ProcessSettings(dedup_threshold=1.5))
		with self.assertRaises(TypeError):
			self.validate_settings(DownloadSettings(), ProcessSettings(dedup_threshold="0.9"))

	def test_pdf_parser(self):
		"""pdf_parser must be text and one of the known PDF parsers."""
		validate.validate_inputs(5, self.input_folder, DownloadSettings(), ProcessSettings(), ParserSettings(pdf_parser="pypdf"))
		with self.assertRaises(IngestError):
			validate.validate_inputs(5, self.input_folder, DownloadSettings(), ProcessSettings(), ParserSettings(pdf_parser="pymupdf"))
		with self.assertRaises(TypeError):
			validate.validate_inputs(5, self.input_folder, DownloadSettings(), ProcessSettings(), ParserSettings(pdf_parser=None))


if __name__ == "__main__":
	unittest.main()
