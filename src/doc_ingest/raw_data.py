
import os
import re
import urllib.parse
import urllib.request
import base64
import concurrent.futures
import dataclasses
import hashlib
import json
from typing import Iterator

from doc_ingest.dataset_config import CONTAINER_EXTENSIONS
from doc_ingest.dataset_config import DatasetConfig
from doc_ingest.dataset_config import EXTENSION_TO_DOCUMENT_TYPE
from doc_ingest.dataset_config import HUGGING_FACE_SPLIT
from doc_ingest.dataset_config import URL_TIMEOUT_SECONDS
from doc_ingest.dataset_config import build_url_request
from doc_ingest.dataset_config import get_content_encoding
from doc_ingest.dataset_config import get_document_type_from_bytes
from doc_ingest.dataset_config import get_extension_of_file
from doc_ingest.dataset_config import get_url_document_extension
from doc_ingest.dataset_config import is_url
from doc_ingest.dataset_config import list_dataset_files

# Largest number of rows read in one batch, so a large request does not
# hold every document's bytes in memory at once. The caller asks again
# for the rest.
MAX_BATCH_ROWS = 256

@dataclasses.dataclass
class RawData:
	"""
	One decoded document saved to raw/, ready to be parsed.

	doc_id: id of the document, from RawDataFetcher.make_doc_id.
	doc_type: its document type from RawDataFetcher.get_document_type
		(e.g. "pdf"); decides which parser is used.
	raw_path: path of its saved raw file in raw/.
	source_path: where the document came from, from
		RawDataFetcher.get_source_path (e.g. "data/a.pdf",
		"https://x.com/a.pdf" or "owner/name#1234").
	"""
	doc_id: str
	doc_type: str
	raw_path: str
	source_path: str

@dataclasses.dataclass
class RawDataBatch:
	"""
	Result of RawDataFetcher.fetch_raw_batch.

	raw_items: a RawData for every row decoded and saved to raw/, in
		source row order.
	rows_read: source rows read for this batch, including rows that
		failed to decode or have an unsupported document type.
	source_exhausted: True if the source ran out of rows.
	"""
	raw_items: list[RawData]
	rows_read: int
	source_exhausted: bool

class RawDataFetcher:
	"""
	Reads a dataset's rows, decodes/downloads each document's bytes, finds
	its document type, and saves it to raw/ as a RawData.
	"""

	def __init__(self, input_path: str, output_path:str, dataset_config: DatasetConfig, download_workers: int):
		"""
		Input: input_path - the dataset path, URL or Hugging Face name;
			output_path - folder that raw/ is saved under; dataset_config -
			the dataset's DatasetConfig; download_workers - rows
			downloaded/decoded at the same time.
		Output: none.
		What it does: stores the inputs for the other methods. The next
			row number starts at 0 and is set by get_iterator.
		"""
		self.input_path = input_path
		self.output_path = output_path
		self.dataset_config = dataset_config
		self.download_workers = download_workers
		self.next_row_number = 0

	def get_iterator(self, raw_data_count: int) -> Iterator:
		"""
		Input: raw_data_count - number of source rows already read in
			earlier runs; these are skipped.
		Output: an iterator of rows, in a fixed source order. A row is a
			record dict (Hugging Face/JSONL/JSON), a document URL, or a local
			file path.
		What it does: picks how to read the dataset:
			- Hugging Face dataset: streams its rows.
			- JSONL/JSON dataset (local or URL): reads records one by one.
			- URL to one document: yields that one URL.
			- Local file or folder: yields the document files.
			Also sets next_row_number to raw_data_count, the position of
			the first row returned in the whole dataset.
		"""
		self.next_row_number = raw_data_count

		if self.dataset_config.path_type == "hf":
			return self.iterate_hugging_face_rows(raw_data_count)

		if self.dataset_config.content_field is not None:
			return self.iterate_container_records(raw_data_count)

		if self.dataset_config.path_type == "url":
			return self.iterate_single_url(raw_data_count)

		return self.iterate_local_files(raw_data_count)

	def iterate_hugging_face_rows(self, rows_to_skip: int) -> Iterator:
		"""
		Input: rows_to_skip - number of rows already read in earlier runs.
		Output: an iterator of row dicts, one per dataset row.
		What it does: opens the Hugging Face dataset in streaming mode, so
			rows are downloaded as they are read, and skips the rows read
			before.
		"""
		# Imported here so local and URL datasets do not pay the import cost.
		from datasets import load_dataset

		dataset = load_dataset(self.input_path, split=HUGGING_FACE_SPLIT, streaming=True)
		dataset = dataset.skip(rows_to_skip)

		for row in dataset:
			yield row

	def iterate_container_records(self, records_to_skip: int) -> Iterator:
		"""
		Input: records_to_skip - number of records already read in earlier
			runs.
		Output: an iterator of record dicts across all container files, in
			order.
		What it does: reads the records of each JSONL/JSON file (local
			files, or the one dataset URL) and skips the records read before.
			Skipped records still have to be read, because a JSONL/JSON file
			cannot be jumped into at a record number.
		"""
		records_seen = 0
		for container_source in self.list_container_sources():
			for record in self.read_container_records(container_source):
				if records_seen < records_to_skip:
					records_seen = records_seen + 1
					continue
				yield record
				records_seen = records_seen + 1

	def iterate_single_url(self, rows_to_skip: int) -> Iterator:
		"""
		Input: rows_to_skip - number of rows already read in earlier runs.
		Output: an iterator with the dataset URL, or nothing if it was
			already read.
		What it does: a URL to one document is a dataset of one row.
		"""
		if rows_to_skip == 0:
			yield self.input_path

	def iterate_local_files(self, files_to_skip: int) -> Iterator:
		"""
		Input: files_to_skip - number of files already read in earlier runs.
		Output: an iterator of document file paths.
		What it does: lists the dataset's document files in sorted order and
			skips the files read before.
		"""
		document_file_paths = self.list_local_document_files()
		for document_file_path in document_file_paths[files_to_skip:]:
			yield document_file_path

	def list_local_document_files(self) -> list[str]:
		"""
		Input: none (uses self.input_path and self.dataset_config).
		Output: sorted list of the dataset's file paths.
		What it does: for a single file, returns just that file. For a
			folder, walks it and its subfolders (skipping hidden files) and
			returns:
			- for a container dataset, every JSONL/JSON file;
			- otherwise, every file with a supported document extension, of
			  any type. This matches how get_dataset_size counts documents.
		"""
		if os.path.isfile(self.input_path):
			return [self.input_path]

		if self.dataset_config.content_field is not None:
			allowed_extensions = CONTAINER_EXTENSIONS
		else:
			allowed_extensions = EXTENSION_TO_DOCUMENT_TYPE

		document_file_paths = []
		for file_path in list_dataset_files(self.input_path):
			if get_extension_of_file(file_path) in allowed_extensions:
				document_file_paths.append(file_path)

		return document_file_paths

	def list_container_sources(self) -> list[str]:
		"""
		Input: none (uses self.input_path and self.dataset_config).
		Output: list of container sources: the dataset URL, or local
			JSONL/JSON file paths in sorted order.
		What it does: a URL dataset is one container file. A local dataset
			is one file or a folder of them.
		"""
		if self.dataset_config.path_type == "url":
			return [self.input_path]

		return self.list_local_document_files()

	def open_container_source(self, source: str):
		"""
		Input: source - a local file path or a URL.
		Output: an open binary stream (use with "with").
		What it does: opens a local file for reading, or starts a download
			of the URL. Both can be read line by line or all at once.
		"""
		if is_url(source):
			request = build_url_request(source, "GET", {})
			return urllib.request.urlopen(request, timeout=URL_TIMEOUT_SECONDS)

		return open(source, "rb")

	def read_container_records(self, source: str) -> Iterator:
		"""
		Input: source - a local JSONL/JSON file path or a URL to one.
		Output: an iterator of the records in the file, in order.
		What it does: for JSONL, reads one line at a time and parses it, so
			the whole file is never in memory. For JSON, loads the whole file
			(a JSON list cannot be read in parts) and yields the object, or
			each item of the list. A local file's own extension decides
			which, since a folder can hold both; a URL uses the dataset
			format.
		"""
		if is_url(source):
			source_format = self.dataset_config.format
		else:
			source_format = get_extension_of_file(source)

		with self.open_container_source(source) as container_stream:
			if source_format == "jsonl":
				for raw_line in container_stream:
					stripped_line = raw_line.decode("utf-8").strip()
					if stripped_line == "":
						continue
					yield json.loads(stripped_line)
				return

			loaded_json = json.loads(container_stream.read().decode("utf-8"))

		if isinstance(loaded_json, list):
			for record in loaded_json:
				yield record
			return

		yield loaded_json

	def make_doc_id(self, raw_bytes: bytes) -> str:
		"""
		Input: raw_bytes - one document's raw bytes.
		Output: the document id: the first 16 hex characters of the
			bytes' SHA-256 hash.
		What it does: hashes the bytes, so the same document always gets
			the same id.
		"""

		digest = hashlib.sha256(raw_bytes).hexdigest()[:16]
		return f"{digest}"

	def download_url_bytes(self, url: str) -> bytes:
		"""
		Input: url - direct download link of one document.
		Output: the downloaded bytes.
		What it does: downloads the whole document. Raises
			urllib.error.URLError (or a subclass) if the download fails, or
			if the server does not respond within URL_TIMEOUT_SECONDS.
		"""
		request = build_url_request(url, "GET", {})
		with urllib.request.urlopen(request, timeout=URL_TIMEOUT_SECONDS) as response:
			return response.read()

	def decode_raw_bytes(self, row) -> bytes | None:
		"""
		Input: row - one row from get_iterator.
		Output: the document's raw bytes, or None if they could not be read.
		What it does:
			- Record rows (JSONL/JSON/Hugging Face): reads the content field,
			  finds how this record's value is encoded (get_content_encoding)
			  and turns it into bytes accordingly.
			- URL dataset of one document: downloads it.
			- Local file: reads the file.
			Any failure is printed and the row is skipped (None).
		"""
		try:
			if self.dataset_config.content_field is not None:
				raw_value = row[self.dataset_config.content_field]
				content_encoding = get_content_encoding(raw_value)

				if content_encoding == "base64":
					raw_bytes = base64.b64decode(raw_value)
				elif content_encoding == "bytes":
					raw_bytes = raw_value
				elif content_encoding == "text":
					raw_bytes = raw_value.encode("utf-8")
				elif content_encoding == "url":
					raw_bytes = self.download_url_bytes(raw_value)
				else:
					raise ValueError(
						f"Unrecognized content_encoding '{content_encoding}'."
					)
			elif self.dataset_config.path_type == "url":
				raw_bytes = self.download_url_bytes(row)
			else:
				with open(row, "rb") as f:
					raw_bytes = f.read()
		except Exception as error:
			print(f"Skipping row: decode/download failed: {type(error).__name__}: {error}")
			return None

		return raw_bytes

	def get_document_type(self, row, raw_bytes: bytes) -> str | None:
		"""
		Input: row - one row from get_iterator; raw_bytes - that row's
			decoded bytes from decode_raw_bytes.
		Output: the document type used by the parser registry (e.g. "pdf",
			"docx", "html", "txt"), or None if the type is not supported.
		What it does: finds the type of this one document, since a dataset
			can hold documents of different types:
			- Record rows (JSONL/JSON/Hugging Face): if the content is a
			  link whose URL path has a supported extension, uses that
			  extension. Otherwise guesses the type from the leading bytes.
			- URL dataset of one document: uses the URL's extension.
			- Local file: uses the file's extension.
		"""
		if self.dataset_config.content_field is not None:
			raw_value = row[self.dataset_config.content_field]
			if get_content_encoding(raw_value) == "url":
				linked_url = raw_value
				parsed_linked_url = urllib.parse.urlparse(linked_url)
				unquoted_linked_url_path = urllib.parse.unquote(parsed_linked_url.path)
				linked_extension = get_extension_of_file(unquoted_linked_url_path)
				if linked_extension in EXTENSION_TO_DOCUMENT_TYPE:
					return EXTENSION_TO_DOCUMENT_TYPE[linked_extension]
			return get_document_type_from_bytes(raw_bytes)

		if self.dataset_config.path_type == "url":
			extension = get_url_document_extension(row)
		else:
			extension = get_extension_of_file(row)

		if extension in EXTENSION_TO_DOCUMENT_TYPE:
			return EXTENSION_TO_DOCUMENT_TYPE[extension]

		return None

	def get_source_path(self, row, row_number: int) -> str:
		"""
		Input: row - one row from get_iterator; row_number - the row's
			position in the whole dataset, counting from 0.
		Output: where the document came from, as text:
			- Local file: its file path.
			- URL dataset of one document: the URL.
			- Record whose content is a link: the link.
			- Any other record (JSONL/JSON/Hugging Face):
			  "<input_path>#<row_number>", e.g. "owner/name#1234".
		What it does: describes the row's origin so a document can be
			traced back to the input it was read from.
		"""
		if self.dataset_config.content_field is not None:
			raw_value = row[self.dataset_config.content_field]
			if get_content_encoding(raw_value) == "url":
				return raw_value
			return f"{self.input_path}#{row_number}"

		return row

	def save_raw_data(self, doc_id: str, raw_bytes: bytes, doc_type: str) -> str:
		"""
		Input: doc_id - id of the document; raw_bytes - its raw bytes;
			doc_type - its document type from get_document_type.
		Output: path of the saved raw file.
		What it does: writes the bytes to
			"<output_path>/<dataset name>/data/raw/<doc_id>.<doc_type>",
			creating the raw/ folder if needed. The document type is used as
			the extension rather than the dataset's extension, because a
			JSONL or Hugging Face dataset holds documents of another type
			(e.g. a PDF inside a JSONL record is saved as ".pdf").
		"""
		raw_file_name = f"{doc_id}.{doc_type}"
		raw_folder_path = f"{self.output_path}/{self.dataset_config.name}/data/raw/"
		raw_file_path = os.path.join(raw_folder_path, raw_file_name)

		os.makedirs(raw_folder_path, exist_ok=True)

		with open(raw_file_path, "wb") as f:
			f.write(raw_bytes)
		return raw_file_path


	def fetch_raw_batch(self, row_iterator: Iterator, rows_needed: int) -> RawDataBatch:
		"""
		Input: row_iterator - from get_iterator; rows_needed - number of
			documents still wanted.
		Output: a RawDataBatch with a RawData for each saved document of
			this batch.
		What it does: reads up to rows_needed rows, but never more than
			MAX_BATCH_ROWS, decodes/downloads them in parallel, finds each
			decoded document's type and source path, and saves it to
			raw/. Advances next_row_number by the rows read. Rows that fail to
			decode or have an unsupported type are counted in
			RawDataBatch.rows_read but not returned in raw_items.
		"""
		rows_to_read = rows_needed
		if rows_to_read > MAX_BATCH_ROWS:
			rows_to_read = MAX_BATCH_ROWS

		rows_to_decode = []
		rows_read = 0
		source_exhausted = False
		while len(rows_to_decode) < rows_to_read:
			try:
				row = next(row_iterator)
			except StopIteration:
				source_exhausted = True
				break
			rows_read += 1
			rows_to_decode.append(row)

		# executor.map returns results in the same order as rows_to_decode
		with concurrent.futures.ThreadPoolExecutor(max_workers=self.download_workers) as executor:
			decoded_results = list(executor.map(self.decode_raw_bytes, rows_to_decode))

		first_row_number = self.next_row_number
		self.next_row_number = self.next_row_number + rows_read

		raw_items = []
		for row_index in range(len(rows_to_decode)):
			row = rows_to_decode[row_index]
			row_number = first_row_number + row_index
			raw_bytes = decoded_results[row_index]
			if raw_bytes is None:
				continue
			doc_id = self.make_doc_id(raw_bytes)
			try:
				doc_type = self.get_document_type(row, raw_bytes)
			except Exception as error:
				print(f"Skipping document {doc_id}: document type could not be found: {type(error).__name__}: {error}")
				continue
			if doc_type is None:
				print(f"Skipping document {doc_id}: unsupported document type")
				continue
			source_path = self.get_source_path(row, row_number)
			raw_path = self.save_raw_data(doc_id, raw_bytes, doc_type)
			raw_items.append(RawData(doc_id, doc_type, raw_path, source_path))

		return RawDataBatch(raw_items, rows_read, source_exhausted)
