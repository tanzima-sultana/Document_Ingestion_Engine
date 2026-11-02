import os

from doc_ingest.fetching.document_type import file_matches_document_type
from doc_ingest.fetching.document_type import get_extension_of_file
from doc_ingest.fetching.local import RECORD_EXTENSIONS
from doc_ingest.fetching.local import list_dataset_files
from doc_ingest.fetching.records import is_url
from doc_ingest.error import IngestError
from doc_ingest.schema import DocumentType
from doc_ingest.settings import Settings


def validate_common(size: int, document_type: str, settings: Settings):
	"""
	Input:
		size - maximum number of documents to process.
		document_type - the type of document to keep (e.g. "pdf").
		settings - the run's Settings.
	Output:
		None. Returns normally only if every check passes.
	What it does:
		Runs the checks every source needs, in order. The first check that
		fails raises an error, which stops document processing.
	"""

	# 1. size must be a whole number
	validate_size_is_integer(size)

	# 2. size must be greater than 0
	validate_size_is_positive(size)

	# 3. timeout_seconds must be a whole number of at least 1
	# (a timeout_seconds of 0 would turn the time limit off)
	validate_setting_is_at_least_one("timeout_seconds", settings.timeout_seconds)

	# 4. dedup_threshold must be a number greater than 0 and at most 1
	validate_dedup_threshold_is_in_range(settings.dedup_threshold)

	# 5. document_type must be a type that has a parser
	validate_document_type_is_supported(document_type)


def validate_local(path: str, size: int, document_type: str, settings: Settings):
	"""
	Input:
		path - local file or folder to read documents from.
		size, document_type, settings - see validate_common.
	Output:
		None. Returns normally only if every check passes.
	What it does:
		Runs the common checks, then the checks for a local path.
	"""
	validate_common(size, document_type, settings)

	# 1. path must not be empty or only spaces
	validate_path_is_not_empty(path)

	# 2. path must be a local file or folder that exists
	validate_path_exists(path)

	# 3. path must hold something of document_type
	validate_path_has_documents(path, document_type)


def validate_size_is_integer(size):
	"""
	Input:
		size - the --size value.
	Output:
		None. Raises TypeError if the check fails.
	What it does:
		Checks that size is a whole number (int). True/False are rejected
		even though Python treats them as int.
	"""
	size_is_boolean = isinstance(size, bool)
	if size_is_boolean:
		raise TypeError("size must be a whole number, got a boolean: " + repr(size))

	size_is_integer = isinstance(size, int)
	if not size_is_integer:
		raise TypeError("size must be a whole number, got " + type(size).__name__ + ": " + repr(size))


def validate_size_is_positive(size):
	"""
	Input:
		size - the --size value, which must already be an int.
	Output:
		None. Raises IngestError if the check fails.
	What it does:
		Checks that size is greater than 0, so at least one document
		will be processed.
	"""
	if size <= 0:
		raise IngestError("size must be greater than 0, got " + str(size))


def validate_setting_is_at_least_one(setting_name, setting_value):
	"""
	Input: setting_name - the setting's name (used in the message); setting_value - its value.
	Output: None. Raises TypeError if the value is not a whole number (True/False are rejected), IngestError if it is below 1.
	"""
	if isinstance(setting_value, bool):
		raise TypeError(setting_name + " must be a whole number, got a boolean: " + repr(setting_value))

	if not isinstance(setting_value, int):
		raise TypeError(setting_name + " must be a whole number, got " + type(setting_value).__name__ + ": " + repr(setting_value))

	if setting_value < 1:
		raise IngestError(setting_name + " must be at least 1, got " + str(setting_value))


def validate_dedup_threshold_is_in_range(dedup_threshold):
	"""
	Input: dedup_threshold - the near-duplicate similarity.
	Output: None. Raises TypeError if it is not a number (True/False are rejected), IngestError if it is not greater than 0 and at most 1.
	A threshold of 0 would mark every document as a duplicate of the first one.
	"""
	if isinstance(dedup_threshold, bool):
		raise TypeError("dedup_threshold must be a number, got a boolean: " + repr(dedup_threshold))

	if not isinstance(dedup_threshold, (int, float)):
		raise TypeError("dedup_threshold must be a number, got " + type(dedup_threshold).__name__ + ": " + repr(dedup_threshold))

	if dedup_threshold <= 0:
		raise IngestError("dedup_threshold must be greater than 0, got " + str(dedup_threshold))

	if dedup_threshold > 1:
		raise IngestError("dedup_threshold must be at most 1, got " + str(dedup_threshold))


def validate_document_type_is_supported(document_type):
	"""
	Input: document_type - the type of document to keep.
	Output: None. Raises TypeError if it is not text, IngestError if no parser exists for it.
	"""
	if not isinstance(document_type, str):
		raise TypeError("document_type must be text, got " + type(document_type).__name__ + ": " + repr(document_type))

	supported_types = []
	for supported_type in DocumentType:
		supported_types.append(supported_type.value)

	if document_type not in supported_types:
		raise IngestError("document_type must be one of " + str(supported_types) + ", got " + repr(document_type))


def validate_path_is_not_empty(path):
	"""
	Input:
		path - the --path value.
	Output:
		None. Raises TypeError or IngestError if the check fails.
	What it does:
		Checks that path is text and is not empty or made only of
		spaces, tabs or newlines.
	"""
	path_is_text = isinstance(path, str)
	if not path_is_text:
		raise TypeError("path must be text, got " + type(path).__name__ + ": " + repr(path))

	path_without_spaces = path.strip()
	if path_without_spaces == "":
		raise IngestError("path must not be empty, got " + repr(path))


def validate_path_exists(path):
	"""
	Input:
		path - the --path value.
	Output:
		None. Raises IngestError if the check fails.
	What it does:
		Web URLs are not supported, so a URL fails. Anything else must be
		a local file or folder that exists on this machine.
	"""
	if is_url(path):
		raise IngestError("path must be a local file or folder, web URLs are not supported: " + repr(path))

	if not os.path.exists(path):
		raise IngestError("path does not exist on this machine: " + repr(path))


def validate_path_has_documents(path, document_type):
	"""
	Input:
		path - a local file or folder that exists.
		document_type - the type of document to keep.
	Output:
		None. Raises IngestError if the check fails.
	What it does:
		A single file must be of document_type or a JSONL/JSON file. A
		folder must hold at least one such file. The records inside
		JSONL/JSON files are only checked when they are read.
	"""
	if os.path.isfile(path):
		if not is_usable_file(path, document_type):
			raise IngestError("path is not a " + document_type + " file: " + repr(path))
		return

	for file_path in list_dataset_files(path):
		if is_usable_file(file_path, document_type):
			return

	raise IngestError("path has no " + document_type + " files: " + repr(path))


def is_usable_file(file_path, document_type) -> bool:
	"""
	Input: file_path - path of one file; document_type - the type of document to keep.
	Output: True if the file is of document_type or is a JSONL/JSON file, otherwise False.
	"""
	if get_extension_of_file(file_path) in RECORD_EXTENSIONS:
		return True

	return file_matches_document_type(file_path, document_type)
