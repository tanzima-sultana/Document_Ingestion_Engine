import base64
import binascii
import dataclasses
import hashlib
import io
import json
import os
import re
import urllib.parse
import urllib.request
import zipfile


# Maps a lowercase file extension (without the dot) to the document type
# used by the parser registry.
EXTENSION_TO_DOCUMENT_TYPE = {
	"pdf": "pdf",
	"docx": "docx",
	"pptx": "pptx",
	"xlsx": "xlsx",
	"csv": "csv",
	"html": "html",
	"htm": "html",
	"md": "md",
	"markdown": "md",
	"txt": "txt",
	"log": "txt",
	"py": "txt",
	"js": "txt",
	"java": "txt",
	"c": "txt",
	"cpp": "txt",
	"h": "txt",
	"sh": "txt",
}

# Extensions of files that hold many documents as records, with each
# document's content stored inside one field of the record.
CONTAINER_EXTENSIONS = [
	"jsonl",
	"json",
]

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

# URL schemes that mark a value as a web link.
URL_SCHEMES = [
	"http",
	"https",
]

# Shortest string that is considered when guessing whether a value is base64.
MINIMUM_BASE64_LENGTH = 16

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

# Value of DatasetConfig.format for a Hugging Face dataset, which is a set
# of records rather than files with one extension.
HUGGING_FACE_FORMAT = "hf"

# Value of DatasetConfig.format for a local folder of document files. The
# files can be of different types; each file's type comes from its own
# extension.
FOLDER_FORMAT = "folder"

# Start of the path of a file stored in a Hugging Face dataset repository.
HUGGING_FACE_FILE_PREFIX = "hf://datasets/"

# Split read from a Hugging Face dataset.
HUGGING_FACE_SPLIT = "train"

# Per-process cache of each Hugging Face dataset's first row, so the
# dataset is not opened again by every helper. Keyed by dataset name.
HUGGING_FACE_FIRST_RECORD_CACHE = {}

# Per-process cache of each dataset's format, so a local folder is not
# walked again by every helper that needs the format. Keyed by path.
DATASET_FORMAT_CACHE = {}


@dataclasses.dataclass
class DatasetConfig:
	name: str
	path: str
	path_type: str
	format: str
	content_field: str | None
	size: int


def get_dataset_config(path) -> DatasetConfig:
	"""
	Input: path to a dataset, either a single file or a directory of files.
	Output: a DatasetConfig describing the dataset.
	What it does: inspects the path and collects the dataset name, whether it
	is a local path or Hugging Face dataset, the dataset format (see
	get_dataset_format), (for container datasets such as JSONL) which field
	holds the content, and the number of documents in the dataset. The
	document type and the content encoding are not part of the config,
	because they can differ from one document to the next; they are found
	per document when the raw data is read (see raw_data.py).
	"""
	name = get_dataset_name(path)
	path_type = get_dataset_path_type(path)
	dataset_format = get_dataset_format(path)
	content_field = get_content_field(path)
	size = get_dataset_size(path)

	return DatasetConfig(name, path, path_type, dataset_format, content_field, size)


def get_dataset_size(path) -> int:
	"""
	Input: path to a dataset file or directory, or a Hugging Face dataset name.
	Output: the number of documents in the dataset, or -1 if it is unknown.
	What it does: counts documents only when that is possible without reading
	the whole dataset:
	- Hugging Face dataset: the row count published in the dataset's info,
	  or -1 if the dataset does not publish one.
	- Container datasets (JSONL/JSON): -1, because counting records means
	  reading every line or the whole file.
	- A single local file: 1, since it is one document.
	- A local directory: the number of files with a supported document
	  extension (other files are ignored by ingestion anyway).
	"""
	if is_hugging_face_dataset(path):
		return get_hugging_face_row_count(path)

	if is_container_dataset(path):
		return -1

	if os.path.isfile(path):
		return 1

	document_count = 0
	for file_path in list_dataset_files(path):
		if get_extension_of_file(file_path) in EXTENSION_TO_DOCUMENT_TYPE:
			document_count = document_count + 1

	return document_count


def get_dataset_name(path) -> str:
	"""
	Input: path to a dataset file or directory, or a Hugging Face dataset name.
	Output: the dataset name, e.g. "reports_1a2b3c4d".
	What it does: last part of the path without extension, plus a short hash
	of the full path or dataset name, so two inputs never share progress and cache.
	"""
	if is_hugging_face_dataset(path):
		name_parts = path.split("/")
		readable_name = name_parts[-1]
		full_path = path
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
	Output: the dataset format (see find_dataset_format).
	What it does: returns the format from DATASET_FORMAT_CACHE if it was
	already found for this path; otherwise finds it with
	find_dataset_format and caches it.
	"""
	if path in DATASET_FORMAT_CACHE:
		return DATASET_FORMAT_CACHE[path]

	dataset_format = find_dataset_format(path)
	DATASET_FORMAT_CACHE[path] = dataset_format
	return dataset_format


def find_dataset_format(path) -> str:
	"""
	Input: path to a dataset file or directory, or a Hugging Face dataset name.
	Output: the dataset format, which decides how the dataset is read:
		HUGGING_FACE_FORMAT ("hf") - a Hugging Face dataset
		"jsonl" or "json"          - container files holding records
		FOLDER_FORMAT ("folder")   - a local folder of document files
		any other extension        - a single document file (e.g. "pdf", "docx")
	What it does: for a single file, returns its extension. For a directory,
	if it holds container files
	(JSONL/JSON), returns the most common container extension; otherwise
	returns FOLDER_FORMAT, because the folder can hold documents of
	different types. Raises ValueError if a file has no extension, or a
	directory has no container files and no supported document files.
	"""
	if is_hugging_face_dataset(path):
		return HUGGING_FACE_FORMAT

	if os.path.isfile(path):
		extension = get_extension_of_file(path)
		if extension == "":
			raise ValueError(f"Dataset file has no extension: {path}")
		return extension

	container_extension_counts = {}
	supported_document_count = 0
	for file_path in list_dataset_files(path):
		extension = get_extension_of_file(file_path)
		if extension in CONTAINER_EXTENSIONS:
			if extension not in container_extension_counts:
				container_extension_counts[extension] = 0
			container_extension_counts[extension] = container_extension_counts[extension] + 1
		elif extension in EXTENSION_TO_DOCUMENT_TYPE:
			supported_document_count = supported_document_count + 1

	if len(container_extension_counts) > 0:
		most_common_extension = ""
		most_common_count = 0
		for extension, count in container_extension_counts.items():
			if count > most_common_count:
				most_common_extension = extension
				most_common_count = count
		return most_common_extension

	if supported_document_count == 0:
		raise ValueError(f"No container files or supported document files found in dataset directory: {path}")

	return FOLDER_FORMAT


def get_content_field(path) -> str | None:
	"""
	Input: path to a dataset file or directory, or a Hugging Face dataset name.
	Output: name of the record field holding the document content, or None.
	What it does: only applies to container datasets (JSONL/JSON/Hugging
	Face). Reads the first record and returns the first field from
	CONTENT_FIELD_CANDIDATES whose value is a string or bytes. Returns None
	for normal document files. Raises ValueError if a container record has
	no usable content field.
	"""
	if not is_container_dataset(path):
		return None

	first_record = read_first_container_record(path)
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


def get_document_type_from_bytes(content_bytes) -> str:
	"""
	Input: raw bytes of one document.
	Output: the guessed document type ("pdf", "docx", "pptx", "xlsx",
	"html" or "txt").
	What it does: looks at the leading bytes ("magic bytes"). PDF files start
	with "%PDF". DOCX/PPTX/XLSX are zip files, told apart by the folders
	inside the zip. HTML is detected by an <html> or <!doctype html> tag near
	the start. Anything else is treated as plain text.
	"""
	if content_bytes.startswith(b"%PDF"):
		return "pdf"

	if content_bytes.startswith(b"PK"):
		office_type = get_office_document_type_from_zip(content_bytes)
		if office_type is not None:
			return office_type

	leading_text = content_bytes[:1024].decode("utf-8", errors="ignore").lower()
	if "<html" in leading_text:
		return "html"
	if "<!doctype html" in leading_text:
		return "html"

	return "txt"


def get_office_document_type_from_zip(content_bytes) -> str | None:
	"""
	Input: raw bytes of a zip file.
	Output: "docx", "pptx", "xlsx", or None if it is not an Office document.
	What it does: opens the bytes as a zip archive and checks for the folder
	each Office format uses ("word/", "ppt/", "xl/"). Returns None if the
	bytes cannot be opened as a zip.
	"""
	try:
		zip_archive = zipfile.ZipFile(io.BytesIO(content_bytes))
	except zipfile.BadZipFile:
		return None

	with zip_archive:
		for member_name in zip_archive.namelist():
			if member_name.startswith("word/"):
				return "docx"
			if member_name.startswith("ppt/"):
				return "pptx"
			if member_name.startswith("xl/"):
				return "xlsx"

	return None


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


def read_first_container_record(path) -> dict:
	"""
	Input: path to a container dataset (JSONL/JSON file or directory of them),
	or a Hugging Face dataset name.
	Output: the first record as a dict.
	What it does: finds the first container file, then reads its first
	record. For JSONL, that is the first non-empty line. For JSON, the file
	must hold either one object or a list of objects; the first object is
	returned. Hugging Face datasets are handled by
	read_first_hugging_face_record. Raises ValueError if no record can be found.
	"""
	if is_hugging_face_dataset(path):
		return read_first_hugging_face_record(path)

	container_file_path = get_first_container_file(path)
	extension = get_extension_of_file(container_file_path)

	if extension == "jsonl":
		with open(container_file_path, "r", encoding="utf-8") as container_file:
			for line in container_file:
				stripped_line = line.strip()
				if stripped_line == "":
					continue
				record = json.loads(stripped_line)
				if not isinstance(record, dict):
					raise ValueError(f"First JSONL record is not an object in: {container_file_path}")
				return record
		raise ValueError(f"JSONL file has no records: {container_file_path}")

	with open(container_file_path, "r", encoding="utf-8") as container_file:
		loaded_json = json.load(container_file)

	return get_first_record_from_loaded_json(loaded_json, container_file_path)


def get_first_record_from_loaded_json(loaded_json, source) -> dict:
	"""
	Input: the parsed contents of a JSON file, and the file path it came
	from (used only in error messages).
	Output: the first record as a dict.
	What it does: if the JSON is one object, returns it. If it is a list,
	returns its first item, which must be an object. Raises ValueError
	otherwise.
	"""
	if isinstance(loaded_json, dict):
		return loaded_json

	if isinstance(loaded_json, list):
		if len(loaded_json) == 0:
			raise ValueError(f"JSON file has an empty list: {source}")
		first_item = loaded_json[0]
		if not isinstance(first_item, dict):
			raise ValueError(f"First JSON record is not an object in: {source}")
		return first_item

	raise ValueError(f"JSON file is not an object or list of objects: {source}")


def get_first_container_file(path) -> str:
	"""
	Input: path to a container dataset file or directory.
	Output: path to the first container file (JSONL/JSON).
	What it does: if the path is a file, returns it. If it is a directory,
	returns the first container file found (in sorted order). Raises
	ValueError if the directory has no container files.
	"""
	if os.path.isfile(path):
		return path

	for file_path in list_dataset_files(path):
		extension = get_extension_of_file(file_path)
		if extension in CONTAINER_EXTENSIONS:
			return file_path

	raise ValueError(f"No container files found in dataset directory: {path}")


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


def get_extension_of_file(file_path) -> str:
	"""
	Input: path to a single file.
	Output: lowercase extension without the dot, or "" if there is none.
	What it does: splits the extension off the file name and normalizes it.
	"""
	_name, extension_with_dot = os.path.splitext(file_path)
	return extension_with_dot.lstrip(".").lower()


def is_url(path) -> bool:
	"""
	Input: a dataset path string, or a content value of a record.
	Output: True if it is an http or https URL with a host name, otherwise
	False.
	What it does: parses the string, checks its scheme against URL_SCHEMES,
	and checks that a host name is present (so "https://" alone is not a
	URL).
	"""
	parsed_path = urllib.parse.urlparse(path)
	if parsed_path.scheme not in URL_SCHEMES:
		return False

	if parsed_path.netloc == "":
		return False

	return True


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

	print("Note: input_path " + repr(input_path) + " is a Hugging Face dataset page. Using dataset " + repr(dataset_name) + ".")
	return dataset_name


def is_container_dataset(path) -> bool:
	"""
	Input: a dataset path string.
	Output: True if the dataset stores many documents as records (Hugging
	Face dataset, JSONL or JSON), otherwise False.
	What it does: Hugging Face datasets are always record-based. Otherwise
	checks the dataset's format against CONTAINER_EXTENSIONS.
	"""
	if is_hugging_face_dataset(path):
		return True

	dataset_format = get_dataset_format(path)
	return dataset_format in CONTAINER_EXTENSIONS


def read_first_hugging_face_record(dataset_name) -> dict:
	"""
	Input: a Hugging Face dataset name (e.g. "owner/name").
	Output: the first row of the dataset's train split as a dict.
	What it does: opens the dataset in streaming mode, so only the first row
	is downloaded, not the whole dataset. The result is cached per name.
	Raises ValueError if the split has no rows.
	"""
	if dataset_name in HUGGING_FACE_FIRST_RECORD_CACHE:
		return HUGGING_FACE_FIRST_RECORD_CACHE[dataset_name]

	# Imported here so local datasets do not pay the import cost.
	from datasets import load_dataset

	streamed_dataset = load_dataset(dataset_name, split=HUGGING_FACE_SPLIT, streaming=True)
	# Keep file columns (e.g. Pdf) as raw bytes instead of opening them
	streamed_dataset = streamed_dataset.decode(False)
	first_record = None
	for row in streamed_dataset:
		first_record = unwrap_file_values(row)
		break

	if first_record is None:
		raise ValueError(f"Hugging Face dataset has no rows in split '{HUGGING_FACE_SPLIT}': {dataset_name}")

	HUGGING_FACE_FIRST_RECORD_CACHE[dataset_name] = first_record
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


def get_hugging_face_row_count(dataset_name) -> int:
	"""
	Input: a Hugging Face dataset name (e.g. "owner/name").
	Output: the number of rows in the train split, or -1 if unknown.
	What it does: reads the dataset's published info (a small metadata
	download, not the data itself). Many datasets do not publish a row
	count; for those, and if the info cannot be loaded at all, returns -1.
	"""
	# Imported here so local datasets do not pay the import cost.
	from datasets import load_dataset_builder

	try:
		dataset_builder = load_dataset_builder(dataset_name)
	except Exception as error:
		print(f"Could not read Hugging Face dataset info for {dataset_name}: {type(error).__name__}: {error}")
		return -1

	dataset_splits = dataset_builder.info.splits
	if dataset_splits is None:
		return -1

	if HUGGING_FACE_SPLIT not in dataset_splits:
		return -1

	row_count = dataset_splits[HUGGING_FACE_SPLIT].num_examples
	if row_count is None:
		return -1

	if row_count <= 0:
		return -1

	return row_count
