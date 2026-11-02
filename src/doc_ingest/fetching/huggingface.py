"""
fetching/huggingface.py

Hugging Face datasets: recognizing a dataset name or dataset page URL,
reading the first row and the row count, and turning hf:// file paths into
download requests.
"""

import logging
import os
import re
import urllib.parse
import urllib.request
from typing import Iterator

from doc_ingest.error import describe_error
from doc_ingest.fetching.records import HUGGING_FACE_FILE_PREFIX
from doc_ingest.fetching.records import is_url

logger = logging.getLogger(__name__)


# Seconds to wait for a document link to respond before giving up.
URL_TIMEOUT_SECONDS = 30

# User-Agent sent when downloading a document link. Some servers reject Python's default one.
URL_USER_AGENT = "DocIngestEngine/1.0"

# Shape of a Hugging Face dataset name: "owner/name", made of letters,
# digits, ".", "_" and "-". Bare names without an owner are not accepted,
# so a mistyped local folder name is not mistaken for a dataset.
HUGGING_FACE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")

# Host of the Hugging Face website. A dataset page URL on it,
# "https://huggingface.co/datasets/<owner>/<name>", is read as the
# dataset "<owner>/<name>" rather than as a web page.
HUGGING_FACE_HOST = "huggingface.co"

# Parts of a Hugging Face dataset page URL that may follow
# "/datasets/<owner>/<name>" and still mean the whole dataset.
HUGGING_FACE_DATASET_PAGE_SUFFIXES = [
	"tree",
	"viewer",
]


def is_hugging_face_dataset(path) -> bool:
	"""
	Input: a dataset path string.
	Output: True if the path is a Hugging Face dataset name, otherwise False.
	What it does: a path is treated as a Hugging Face dataset name when it
	does not exist on disk and has the shape "owner/name". Whether the
	dataset really exists on the Hub is only found out when it is opened.
	"""
	if os.path.exists(path):
		return False

	return has_hugging_face_name_shape(path)


def has_hugging_face_name_shape(path) -> bool:
	"""
	Input: any input path string.
	Output: True if the string has the shape of a Hugging Face dataset
	name, "owner/name" (e.g. "superdoc-dev/docx-corpus"), otherwise False.
	What it does: matches the string against HUGGING_FACE_NAME_PATTERN. It
	only checks the shape; it does not check whether a local path with the
	same name exists, or whether the dataset exists on the Hub.
	"""
	name_match = HUGGING_FACE_NAME_PATTERN.fullmatch(path)
	return name_match is not None


def get_hugging_face_dataset_name_from_url(url) -> str | None:
	"""
	Input: any input path string.
	Output: the dataset name "owner/name" if the string is a Hugging Face
	dataset page URL, otherwise None.
	What it does: accepts URLs on HUGGING_FACE_HOST whose path is
	"/datasets/<owner>/<name>", optionally followed by one of
	HUGGING_FACE_DATASET_PAGE_SUFFIXES (e.g. ".../tree/main"). Links to a
	single file inside a dataset (e.g. ".../resolve/main/data.jsonl") are
	not converted, because they download that one file.
	"""
	if not is_url(url):
		return None

	parsed_url = urllib.parse.urlparse(url)
	host_name = parsed_url.netloc.lower()
	if host_name != HUGGING_FACE_HOST:
		if host_name != "www." + HUGGING_FACE_HOST:
			return None

	path_parts = []
	for path_part in parsed_url.path.split("/"):
		if path_part != "":
			path_parts.append(path_part)

	if len(path_parts) < 3:
		return None

	if path_parts[0] != "datasets":
		return None

	if len(path_parts) > 3:
		if path_parts[3] not in HUGGING_FACE_DATASET_PAGE_SUFFIXES:
			return None

	dataset_name = path_parts[1] + "/" + path_parts[2]
	if not has_hugging_face_name_shape(dataset_name):
		return None

	return dataset_name


def normalize_input_path(input_path) -> str:
	"""
	Input: the --input_path value.
	Output: the input path to use from now on.
	What it does: if the input path is a Hugging Face dataset page URL
	(see get_hugging_face_dataset_name_from_url), returns the dataset name
	"owner/name" instead and prints a note, so the dataset is streamed
	rather than its web page being downloaded as one HTML document. Any
	other input path is returned unchanged.
	"""
	dataset_name = get_hugging_face_dataset_name_from_url(input_path)
	if dataset_name is None:
		return input_path

	logger.info("Note: input_path %r is a Hugging Face dataset page. Using dataset %r.", input_path, dataset_name)
	return dataset_name


def read_first_hugging_face_record(dataset_name, hugging_face_split: str) -> dict:
	"""
	Input: a Hugging Face dataset name (e.g. "owner/name") and the split to read.
	Output: the first row of that split as a dict.
	What it does: opens the dataset in streaming mode, so only the first row
	is downloaded, not the whole dataset. Raises ValueError if the split
	has no rows.
	"""
	# Imported here so local datasets do not pay the import cost.
	from datasets import load_dataset

	streamed_dataset = load_dataset(dataset_name, split=hugging_face_split, streaming=True)
	# Keep file columns (e.g. Pdf) as raw bytes instead of opening them
	streamed_dataset = streamed_dataset.decode(False)
	first_record = None
	for row in streamed_dataset:
		first_record = unwrap_file_values(row)
		break

	if first_record is None:
		raise ValueError(f"Hugging Face dataset has no rows in split '{hugging_face_split}': {dataset_name}")

	return first_record


def unwrap_file_values(row) -> dict:
	"""
	Input: one Hugging Face row. Output: the same row.
	A file column read without decoding is {"bytes": ..., "path": ...}; it
	is replaced by its bytes, or by its hf:// path when only that is given.
	"""
	for field_name, field_value in row.items():
		if not isinstance(field_value, dict):
			continue

		file_bytes = field_value.get("bytes")
		file_path = field_value.get("path")
		if isinstance(file_bytes, bytes):
			row[field_name] = file_bytes
		elif isinstance(file_path, str) and file_path.startswith(HUGGING_FACE_FILE_PREFIX):
			row[field_name] = file_path

	return row


def get_hugging_face_file_url(hf_path) -> str:
	"""
	Input: "hf://datasets/<owner>/<name>@<revision>/<file path>".
	Output: its download URL on HUGGING_FACE_HOST.
	"""
	repo_and_file = hf_path[len(HUGGING_FACE_FILE_PREFIX):]
	path_parts = repo_and_file.split("/", 2)
	owner = path_parts[0]
	name_and_revision = path_parts[1]
	file_path = path_parts[2]
	name, revision = name_and_revision.split("@", 1)
	quoted_file_path = urllib.parse.quote(file_path)
	return f"https://{HUGGING_FACE_HOST}/datasets/{owner}/{name}/resolve/{revision}/{quoted_file_path}"


def build_url_request(url, method, extra_headers) -> urllib.request.Request:
	"""
	Input: a URL, an HTTP method ("GET" or "HEAD"), and a dict of extra
	request headers.
	Output: a urllib Request ready to be opened.
	What it does: sets the User-Agent header plus any extra headers given.
	"""
	request_headers = {"User-Agent": URL_USER_AGENT}
	for header_name, header_value in extra_headers.items():
		request_headers[header_name] = header_value

	return urllib.request.Request(url, headers=request_headers, method=method)


def get_hugging_face_row_count(dataset_name, hugging_face_split: str) -> int:
	"""
	Input: a Hugging Face dataset name (e.g. "owner/name") and the split to count.
	Output: the number of rows in that split, or -1 if unknown.
	What it does: reads the dataset's published info (a small metadata
	download, not the data itself). Many datasets do not publish a row
	count; for those, and if the info cannot be loaded at all, returns -1.
	"""
	# Imported here so local datasets do not pay the import cost.
	from datasets import load_dataset_builder

	try:
		dataset_builder = load_dataset_builder(dataset_name)
	except Exception as error:
		logger.warning("Could not read Hugging Face dataset info for %s: %s: %s", dataset_name, type(error).__name__, error)
		return -1

	dataset_splits = dataset_builder.info.splits
	if dataset_splits is None:
		return -1

	if hugging_face_split not in dataset_splits:
		return -1

	row_count = dataset_splits[hugging_face_split].num_examples
	if row_count is None:
		return -1

	if row_count <= 0:
		return -1

	return row_count


def iterate_hugging_face_rows(dataset_name, hugging_face_split: str) -> Iterator:
	"""
	Input: a Hugging Face dataset name and the split to read.
	Output: an iterator of row dicts, one per dataset row. A row that
		cannot be unwrapped is logged and given as None, so it still
		counts as read.
	What it does: opens the dataset in streaming mode, so rows are
		downloaded as they are read.
	"""
	# Imported here so local datasets do not pay the import cost.
	from datasets import load_dataset

	dataset = load_dataset(dataset_name, split=hugging_face_split, streaming=True)
	# Keep file columns (e.g. Pdf) as raw bytes instead of opening them
	dataset = dataset.decode(False)

	for row in dataset:
		try:
			unwrapped_row = unwrap_file_values(row)
		except Exception as error:
			logger.warning("Skipping row: could not be read: %s", describe_error(error))
			unwrapped_row = None
		yield unwrapped_row


def download_hugging_face_file(hf_path) -> bytes:
	"""
	Input: hf_path - "hf://datasets/..." path of one Hugging Face file.
	Output: the downloaded bytes.
	What it does: downloads the whole file from its Hugging Face download
		URL. Raises urllib.error.URLError (or a subclass) if the download
		fails, or if the server does not respond within URL_TIMEOUT_SECONDS.
	"""
	download_url = get_hugging_face_file_url(hf_path)
	request = build_url_request(download_url, "GET", {})
	with urllib.request.urlopen(request, timeout=URL_TIMEOUT_SECONDS) as response:
		return response.read()
