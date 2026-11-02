"""
fetching/local.py

Local datasets: a single document file, a folder of document files, or
JSONL/JSON files holding many documents as records. Finds and
describes them, and LocalFetcher reads their rows.
"""

import json
import logging
import os
from typing import Iterator

from doc_ingest.error import IngestError
from doc_ingest.error import describe_error
from doc_ingest.fetching.document_type import bytes_match_document_type
from doc_ingest.fetching.document_type import file_matches_document_type
from doc_ingest.fetching.document_type import get_extension_of_file
from doc_ingest.fetching.fetcher import BaseFetcher
from doc_ingest.fetching.fetcher import RawDocument
from doc_ingest.fetching.records import decode_content_value
from doc_ingest.fetching.records import find_content_field
from doc_ingest.fetching.records import get_content_encoding
from doc_ingest.settings import FetchSettings

logger = logging.getLogger(__name__)


# Extensions of files that hold many documents as records, with each
# document's content stored inside one field of the record.
RECORD_EXTENSIONS = [
	"jsonl",
	"json",
]


def is_record_dataset(path, document_type: str) -> bool:
	"""
	Input: path to a local file or folder; document_type - the type to keep.
	Output: True if the documents are records in JSONL/JSON files, otherwise False.
	What it does: a folder is only read as records if it has no files of document_type,
	so a stray JSON file next to PDFs does not change how the folder is read.
	"""
	if os.path.isfile(path):
		return get_extension_of_file(path) in RECORD_EXTENSIONS

	folder_has_records = False
	for file_path in list_dataset_files(path):
		if file_matches_document_type(file_path, document_type):
			return False
		if get_extension_of_file(file_path) in RECORD_EXTENSIONS:
			folder_has_records = True

	return folder_has_records


def list_record_files(path) -> list:
	"""
	Input: path to a local file or folder.
	Output: the file itself, or the folder's JSONL/JSON files in sorted order.
	"""
	if os.path.isfile(path):
		return [path]

	record_file_paths = []
	for file_path in list_dataset_files(path):
		if get_extension_of_file(file_path) in RECORD_EXTENSIONS:
			record_file_paths.append(file_path)

	return record_file_paths


def find_first_record(path) -> dict:
	"""
	Input: path to a local JSONL/JSON file, or a folder of them.
	Output: the first record that is a JSON object; records that are not valid are passed over.
	Raises IngestError if there is none.
	"""
	for record_file_path in list_record_files(path):
		for record in read_records(record_file_path):
			if isinstance(record, dict):
				return record

	raise IngestError(f"No records found in: {path}")


def read_records(record_file_path: str) -> Iterator:
	"""
	Input: record_file_path - a local JSONL/JSON file path.
	Output: an iterator of the records in the file, in order.
	What it does: for JSONL, reads one line at a time and parses it, so
		the whole file is never in memory. For JSON, loads the whole file
		(a JSON list cannot be read in parts) and yields the object, or
		each item of the list. The file's own extension decides which,
		since a folder can hold both.
		A JSONL line, or a whole JSON file, that is not valid UTF-8 JSON
		is logged and given as one None record, so it still counts as read.
	"""
	source_format = get_extension_of_file(record_file_path)

	with open(record_file_path, "rb") as record_stream:
		if source_format == "jsonl":
			for raw_line in record_stream:
				try:
					stripped_line = raw_line.decode("utf-8").strip()
					if stripped_line == "":
						continue
					record = json.loads(stripped_line)
				except ValueError as error:
					logger.warning("Skipping record in %s: not valid JSON: %s", record_file_path, describe_error(error))
					record = None
				yield record
			return

		try:
			loaded_json = json.loads(record_stream.read().decode("utf-8"))
		except ValueError as error:
			logger.warning("Skipping file %s: not valid JSON: %s", record_file_path, describe_error(error))
			loaded_json = None

	if isinstance(loaded_json, list):
		for record in loaded_json:
			yield record
		return

	yield loaded_json


def list_dataset_files(directory_path) -> list:
	"""
	Input: path to a dataset directory.
	Output: sorted list of file paths inside it, including subdirectories.
	What it does: walks the directory tree and collects every file, skipping
	hidden files and hidden folders (names starting with ".").
	"""
	file_paths = []
	for current_directory, sub_directory_names, file_names in os.walk(directory_path):
		visible_sub_directory_names = []
		for sub_directory_name in sub_directory_names:
			if not sub_directory_name.startswith("."):
				visible_sub_directory_names.append(sub_directory_name)
		sub_directory_names[:] = visible_sub_directory_names

		for file_name in file_names:
			if file_name.startswith("."):
				continue
			file_paths.append(os.path.join(current_directory, file_name))

	file_paths.sort()
	return file_paths


class LocalFetcher(BaseFetcher):
	"""
	Reads a local dataset's rows. Going through the rows is shared, in BaseFetcher.
	"""

	def __init__(self, path: str, storage_path: str, fetch_settings: FetchSettings):
		"""
		Input: path - local file or folder; storage_path - storage folder that raw/ is saved under;
			fetch_settings - the type to keep.
		Output: none.
		What it does: stores path and, for JSONL/JSON records, finds which field holds the document.
		"""
		self.path = path
		self.content_field = None
		if is_record_dataset(path, fetch_settings.document_type):
			self.content_field = find_content_field(find_first_record(path), path)

		super().__init__(storage_path, fetch_settings)

	def get_iterator(self) -> Iterator:
		"""
		Input: none.
		Output: an iterator of rows, in a fixed source order. A row is a
			record dict (JSONL/JSON) or a local file path.
		What it does: picks how to read the dataset:
			- JSONL/JSON dataset: reads records one by one.
			- Local file or folder: yields the document files.
		"""
		if self.content_field is not None:
			return self.iterate_records()

		return iter(self.list_document_files())

	def fetch_row(self, row, row_number: int) -> RawDocument | None:
		"""
		Input: row - a file path, or a record of a JSONL/JSON dataset; row_number - its position in the dataset.
		Output: its RawDocument, or None if it is skipped.
		"""
		if self.content_field is None:
			return self.fetch_file(row, row_number)

		return self.fetch_record(row, row_number)

	def fetch_file(self, file_path: str, row_number: int) -> RawDocument | None:
		"""
		Input: file_path - one local file; row_number - its position in the dataset.
		Output: a RawDocument for the file, or None if it is skipped.
		What it does: checks the extension, so a file of the wrong type is never read, then reads the bytes for the
			document id. The file itself is not copied: the parser reads the original.
		"""
		document_type = self.fetch_settings.document_type
		if not file_matches_document_type(file_path, document_type):
			logger.warning("Skipping row %s: not of type %s", row_number, document_type)
			self.summary.wrong_doc_type += 1
			return None

		try:
			with open(file_path, "rb") as document_file:
				raw_bytes = document_file.read()
		except OSError as error:
			logger.warning("Skipping row %s: could not be read: %s", row_number, describe_error(error))
			self.summary.fetch_failed += 1
			return None

		self.summary.fetch_success += 1
		return RawDocument(self.make_doc_id(raw_bytes), document_type, file_path, file_path)

	def fetch_record(self, record, row_number: int) -> RawDocument | None:
		"""
		Input: record - one record dict, or None if it was not valid JSON; row_number - its position in the dataset.
		Output: a RawDocument for the record, or None if it is skipped.
		What it does: decodes the content field, checks the bytes are of document_type and saves them to raw/.
			A record that cannot be decoded is logged and skipped. A "hf_file" link fails, because a local run does not use the network.
		"""
		if record is None:
			self.summary.fetch_failed += 1
			return None

		try:
			raw_value = record[self.content_field]
			raw_bytes = decode_content_value(raw_value, get_content_encoding(raw_value))
		except Exception as error:
			logger.warning("Skipping row %s: could not be decoded: %s", row_number, describe_error(error))
			self.summary.fetch_failed += 1
			return None

		self.summary.fetch_success += 1
		doc_id = self.make_doc_id(raw_bytes)
		document_type = self.fetch_settings.document_type

		if not bytes_match_document_type(raw_bytes, document_type):
			logger.warning("Skipping document %s: not of type %s", doc_id, document_type)
			self.summary.wrong_doc_type += 1
			return None

		# A failure to write here (e.g. disk full) stops the run, because every later record would fail too
		raw_path = self.save_raw_file(doc_id, raw_bytes)
		return RawDocument(doc_id, document_type, raw_path, f"{self.path}#{row_number}")

	def iterate_records(self) -> Iterator:
		"""
		Input: none.
		Output: an iterator of record dicts across all record files, in
			order.
		What it does: reads the records of each JSONL/JSON file one by one.
		"""
		for record_file_path in list_record_files(self.path):
			for record in read_records(record_file_path):
				yield record

	def list_document_files(self) -> list[str]:
		"""
		Input: none. Output: the file itself, or every file in the folder in sorted order, skipping hidden ones.
		Files of the wrong type are included, so they are counted (see fetch_file).
		"""
		if os.path.isfile(self.path):
			return [self.path]

		return list_dataset_files(self.path)
