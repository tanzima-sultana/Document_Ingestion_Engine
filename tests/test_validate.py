"""
Tests for validate.py (local paths only, no network).
"""

import os
import tempfile
import unittest

from doc_ingest import validate


class TestValidateInputs(unittest.TestCase):

	def setUp(self):
		self.temporary_folder = tempfile.TemporaryDirectory()
		self.root = self.temporary_folder.name
		self.input_folder = os.path.join(self.root, "input")
		os.makedirs(self.input_folder)
		self.output_folder = os.path.join(self.root, "output")

	def tearDown(self):
		self.temporary_folder.cleanup()

	def test_valid_inputs_pass(self):
		"""Valid size and paths raise nothing."""
		validate.validate_inputs(5, self.input_folder, self.output_folder)

	def test_bad_size(self):
		"""Size must be a positive whole number, not a boolean."""
		with self.assertRaises(TypeError):
			validate.validate_inputs(True, self.input_folder, self.output_folder)
		with self.assertRaises(TypeError):
			validate.validate_inputs(2.5, self.input_folder, self.output_folder)
		with self.assertRaises(ValueError):
			validate.validate_inputs(0, self.input_folder, self.output_folder)

	def test_bad_input_path(self):
		"""Empty or missing local input paths fail."""
		with self.assertRaises(ValueError):
			validate.validate_inputs(5, "   ", self.output_folder)
		with self.assertRaises(ValueError):
			validate.validate_inputs(5, os.path.join(self.root, "missing"), self.output_folder)

	def test_output_is_a_file(self):
		"""An output path that is a file fails."""
		output_file = os.path.join(self.root, "out.txt")
		with open(output_file, "w") as file:
			file.write("x")
		with self.assertRaises(ValueError):
			validate.validate_inputs(5, self.input_folder, output_file)

	def test_output_inside_input(self):
		"""An output folder inside the input folder fails."""
		with self.assertRaises(ValueError):
			validate.validate_inputs(5, self.input_folder, os.path.join(self.input_folder, "out"))


if __name__ == "__main__":
	unittest.main()
