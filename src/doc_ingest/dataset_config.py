"""
dataset_config.py

Builds a DatasetConfig for an input path by putting together what the
dataset modules find: dataset_local.py for local files and folders,
dataset_hf.py for Hugging Face datasets. Also holds the record handling
both share: which field holds the document, and how it is encoded.
"""

import base64
import binascii
import dataclasses
import hashlib
import os

from doc_ingest.dataset_hf import HUGGING_FACE_FILE_PREFIX
from doc_ingest.dataset_hf import HUGGING_FACE_FORMAT
from doc_ingest.dataset_hf import get_hugging_face_row_count
from doc_ingest.dataset_hf import is_hugging_face_dataset
from doc_ingest.dataset_hf import is_url
from doc_ingest.dataset_hf import read_first_hugging_face_record
from doc_ingest.dataset_local import CONTAINER_EXTENSIONS
from doc_ingest.dataset_local import get_local_dataset_format
from doc_ingest.dataset_local import get_local_dataset_size
from doc_ingest.dataset_local import read_first_local_record
from doc_ingest.settings import DEFAULT_HUGGING_FACE_SPLIT


# Field names checked, in order, when looking for the field that holds
# the document content inside a container record.
CONTENT_FIELD_CANDIDATES = [
	"content",
	"text",
	"body",
	"data",
	"bytes",
	"raw",
	"document",
	"pdf",
]

# Shortest string that is considered when guessing whether a value is base64.
MINIMUM_BASE64_LENGTH = 16


@dataclasses.dataclass
class DatasetConfig:
	name: str
	path: str
	path_type: str
	format: str
	content_field: str | None
	size: int


def get_dataset_config(path, hugging_face_split: str = DEFAULT_HUGGING_FACE_SPLIT) -> DatasetConfig:
	"""
	Input: path to a dataset (a single file, a directory of files, or a Hugging Face
	dataset name); hugging_face_split - the split read from a Hugging Face dataset.
	Output: a DatasetConfig describing the dataset.
	What it does: inspects the path and collects the dataset name, whether it
	is a local path or Hugging Face dataset, the dataset format (see
	get_dataset_format), (for container datasets such as JSONL) which field
	holds the content, and the number of documents in the dataset. The
	document type and the content encoding are not part of the config,
	because they can differ from one document to the next; they are found
	per document when the raw data is read (see raw_data.py). The format is
	found once here and passed to the helpers that need it, instead of
	each helper working it out again.
	"""
	name = get_dataset_name(path, hugging_face_split)
	path_type = get_dataset_path_type(path)
	dataset_format = get_dataset_format(path)
	content_field = get_content_field(path, dataset_format, hugging_face_split)
	size = get_dataset_size(path, dataset_format, hugging_face_split)

	return DatasetConfig(name, path, path_type, dataset_format, content_field, size)


def get_dataset_size(path, dataset_format: str, hugging_face_split: str) -> int:
	"""
	Input: path to a dataset file or directory, or a Hugging Face dataset name; dataset_format - from get_dataset_format;
	hugging_face_split - the split counted for a Hugging Face dataset.
	Output: the number of documents in the dataset, or -1 if it is unknown.
	What it does: counts documents only when that is possible without reading the whole dataset:
	the row count a Hugging Face dataset publishes (see get_hugging_face_row_count), or the local
	count (see get_local_dataset_size).
	"""
	if dataset_format == HUGGING_FACE_FORMAT:
		return get_hugging_face_row_count(path, hugging_face_split)

	return get_local_dataset_size(path, dataset_format)


def get_dataset_name(path, hugging_face_split: str = DEFAULT_HUGGING_FACE_SPLIT) -> str:
	"""
	Input: path to a dataset file or directory, or a Hugging Face dataset name; hugging_face_split - the split read.
	Output: the dataset name, e.g. "reports_1a2b3c4d".
	What it does: last part of the path without extension, plus a short hash
	of the full path or dataset name, so two inputs never share progress and cache.
	A Hugging Face split other than the default is added too, so two splits never share them either.
	"""
	if is_hugging_face_dataset(path):
		name_parts = path.split("/")
		readable_name = name_parts[-1]
		full_path = path
		# The default split keeps the name it had before splits could be chosen
		if hugging_face_split != DEFAULT_HUGGING_FACE_SPLIT:
			readable_name = readable_name + "_" + hugging_face_split
			full_path = path + "@" + hugging_face_split
	else:
		full_path = os.path.abspath(path)
		base_name = os.path.basename(full_path)
		if os.path.isdir(full_path):
			readable_name = base_name
		else:
			readable_name, _extension = os.path.splitext(base_name)

	path_hash = hashlib.sha256(full_path.encode("utf-8")).hexdigest()
	return f"{readable_name}_{path_hash[:8]}"


def get_dataset_path_type(path) -> str:
	"""
	Input: path to a dataset: a local file/directory, or a Hugging Face
	dataset name.
	Output: "local" or "hf".
	What it does: returns "local" if the path exists on disk, and "hf" if it
	looks like a Hugging Face dataset name (e.g. "owner/name"). Raises
	FileNotFoundError if it is neither.
	"""
	if os.path.exists(path):
		return "local"

	if is_hugging_face_dataset(path):
		return "hf"

	raise FileNotFoundError(f"Dataset path does not exist: {path}")


def get_dataset_format(path) -> str:
	"""
	Input: path to a dataset file or directory, or a Hugging Face dataset name.
	Output: HUGGING_FACE_FORMAT ("hf") for a Hugging Face dataset, otherwise the local format
	(see get_local_dataset_format): "jsonl"/"json", FOLDER_FORMAT ("folder"), or a file extension.
	"""
	if is_hugging_face_dataset(path):
		return HUGGING_FACE_FORMAT

	return get_local_dataset_format(path)


def get_content_field(path, dataset_format: str, hugging_face_split: str) -> str | None:
	"""
	Input: path to a dataset file or directory, or a Hugging Face dataset name; dataset_format - from get_dataset_format;
	hugging_face_split - the split whose first record is read for a Hugging Face dataset.
	Output: name of the record field holding the document content, or None.
	What it does: only applies to container datasets (JSONL/JSON/Hugging
	Face). Reads the first record and returns the first field from
	CONTENT_FIELD_CANDIDATES whose value is a string or bytes. Returns None
	for normal document files. Raises ValueError if a container record has
	no usable content field.
	"""
	if not is_container_format(dataset_format):
		return None

	first_record = read_first_container_record(path, hugging_face_split)
	for candidate_field in CONTENT_FIELD_CANDIDATES:
		if candidate_field not in first_record:
			continue
		candidate_value = first_record[candidate_field]
		if isinstance(candidate_value, str):
			return candidate_field
		if isinstance(candidate_value, bytes):
			return candidate_field

	raise ValueError(
		f"No content field found in first record of dataset: {path}. "
		f"Looked for: {CONTENT_FIELD_CANDIDATES}"
	)


def get_content_encoding(content_value) -> str:
	"""
	Input: the value of the content field of one container record.
	Output: one of:
		"bytes"   - the value already holds raw bytes (Hugging Face binary column)
		"hf_file" - the value is an "hf://datasets/..." path of a Hugging Face
		            file to download (see unwrap_file_values)
		"base64"  - the value holds base64-encoded bytes
		"text"    - the value is the document as plain text
	What it does: checks which of the above the value is, in that order.
	It is called for every record, because records of one dataset can be
	encoded differently. Raises ValueError if the value is neither a string
	nor bytes, or is a web link: only Hugging Face file links are downloaded.
	"""
	if isinstance(content_value, bytes):
		return "bytes"

	# A Hugging Face file that is not a single downloadable file (e.g. inside a zip)
	if isinstance(content_value, dict) and "path" in content_value:
		raise ValueError(f"file cannot be downloaded: {content_value['path']}")

	if not isinstance(content_value, str):
		raise ValueError(f"Content value is not a string or bytes: {type(content_value).__name__}")

	if content_value.startswith(HUGGING_FACE_FILE_PREFIX):
		return "hf_file"

	if is_url(content_value):
		raise ValueError(f"web links in records are not supported, only Hugging Face files: {content_value}")

	if looks_like_base64(content_value):
		return "base64"

	return "text"


def looks_like_base64(value) -> bool:
	"""
	Input: a string value.
	Output: True if the string looks like base64-encoded data, otherwise False.
	What it does: rejects short strings, strings with whitespace, and strings
	whose length is not a multiple of 4. Then tries a strict base64 decode.
	Plain sentences fail these checks because they contain spaces.
	"""
	if len(value) < MINIMUM_BASE64_LENGTH:
		return False

	if len(value) % 4 != 0:
		return False

	for character in value:
		if character.isspace():
			return False

	try:
		base64.b64decode(value, validate=True)
	except (binascii.Error, ValueError):
		return False

	return True


def read_first_container_record(path, hugging_face_split: str) -> dict:
	"""
	Input: path to a local container dataset (JSONL/JSON), or a Hugging Face dataset name; hugging_face_split - its split.
	Output: the first record as a dict.
	What it does: reads it with read_first_hugging_face_record or read_first_local_record.
	"""
	if is_hugging_face_dataset(path):
		return read_first_hugging_face_record(path, hugging_face_split)

	return read_first_local_record(path)


def is_container_format(dataset_format: str) -> bool:
	"""
	Input: a dataset format, from get_dataset_format.
	Output: True if the dataset stores many documents as records (Hugging
	Face dataset, JSONL or JSON), otherwise False.
	What it does: Hugging Face datasets are always record-based. Otherwise
	checks the format against CONTAINER_EXTENSIONS.
	"""
	if dataset_format == HUGGING_FACE_FORMAT:
		return True

	return dataset_format in CONTAINER_EXTENSIONS
