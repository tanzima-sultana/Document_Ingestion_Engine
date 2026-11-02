"""
fetching/records.py

Record handling shared by the dataset sources: which field of a record
holds the document, how its value is encoded, and telling web links apart.
"""

import base64
import binascii
import urllib.parse

from doc_ingest.error import IngestError


# URL schemes that mark a value as a web link.
URL_SCHEMES = [
	"http",
	"https",
]

# Start of the path of a file stored in a Hugging Face dataset repository.
HUGGING_FACE_FILE_PREFIX = "hf://datasets/"

# Field names checked, in order, when looking for the field that holds
# the document content inside a record.
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


def find_content_field(first_record: dict, path) -> str:
	"""
	Input: first_record - the first record of a dataset; path - the
	dataset's path or name (used only in the error message).
	Output: name of the record field holding the document content.
	What it does: returns the first field from CONTENT_FIELD_CANDIDATES whose
	value is a string or bytes. Raises IngestError if there is none.
	"""
	for candidate_field in CONTENT_FIELD_CANDIDATES:
		if candidate_field not in first_record:
			continue
		candidate_value = first_record[candidate_field]
		if isinstance(candidate_value, str):
			return candidate_field
		if isinstance(candidate_value, bytes):
			return candidate_field

	raise IngestError(
		f"No content field found in first record of dataset: {path}. "
		f"Looked for: {CONTENT_FIELD_CANDIDATES}"
	)


def get_content_encoding(content_value) -> str:
	"""
	Input: the value of the content field of one record.
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


def decode_content_value(content_value, content_encoding: str) -> bytes:
	"""
	Input: content_value - the value of a record's content field; content_encoding - from get_content_encoding.
	Output: the document's raw bytes. Raises ValueError for an encoding that has no bytes to decode, such as "hf_file".
	"""
	if content_encoding == "base64":
		return base64.b64decode(content_value)
	if content_encoding == "bytes":
		return content_value
	if content_encoding == "text":
		return content_value.encode("utf-8")

	raise ValueError(f"Cannot decode content_encoding '{content_encoding}'.")


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
