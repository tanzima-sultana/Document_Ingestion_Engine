import logging
import os
import tempfile

from doc_ingest.dataset_hf import has_hugging_face_name_shape
from doc_ingest.dataset_hf import is_url
from doc_ingest.error import IngestError
from doc_ingest.settings import DownloadSettings
from doc_ingest.settings import ProcessSettings

logger = logging.getLogger(__name__)


def validate_inputs(size: int, input_path: str, storage_path: str | None, download_settings: DownloadSettings, process_settings: ProcessSettings):
	"""
	Input:
		size - maximum number of documents to process.
		input_path - where to read documents from.
		storage_path - the cache_dir folder where raw files, processed documents and progress are stored (None: caching off, checks 10-13 are skipped).
		download_settings, process_settings - the run's settings.
	Output:
		None. Returns normally only if every check passes.
	What it does:
		Runs each check in order. The first check that fails raises an
		error, which stops validation and stops document processing.
	"""

	# 1. size must be a whole number
	validate_size_is_integer(size)

	# 2. size must be greater than 0
	validate_size_is_positive(size)

	# 3. download_workers, max_batch_rows and parse_timeout_seconds must be whole numbers of at least 1
	# (a parse_timeout_seconds of 0 would turn the time limit off)
	validate_setting_is_at_least_one("download_workers", download_settings.download_workers)
	validate_setting_is_at_least_one("max_batch_rows", download_settings.max_batch_rows)
	validate_setting_is_at_least_one("parse_timeout_seconds", process_settings.parse_timeout_seconds)

	# 4. parse_workers must be None (one per CPU core) or a whole number of at least 1
	if process_settings.parse_workers is not None:
		validate_setting_is_at_least_one("parse_workers", process_settings.parse_workers)

	# 5. hugging_face_split must not be empty or only spaces
	validate_hugging_face_split_is_not_empty(download_settings.hugging_face_split)

	# 6. dedup_threshold must be a number greater than 0 and at most 1
	validate_dedup_threshold_is_in_range(process_settings.dedup_threshold)

	# 7. input_path must not be empty or only spaces
	validate_input_path_is_not_empty(input_path)

	# 8. input_path must not match more than one kind of input
	validate_input_path_is_not_ambiguous(input_path)

	# 9. input_path must be a local path that exists or a Hugging Face dataset name
	validate_local_input_path_exists(input_path)

	# Caching off: there is no storage folder to check
	if storage_path is None:
		return

	# 10. storage_path must not be empty or only spaces
	validate_storage_path_is_not_empty(storage_path)

	# 11. if storage_path already exists, it must be a folder, not a file
	validate_storage_path_is_not_a_file(storage_path)

	# 12. storage_path must not be the input folder or inside it
	# (runs before 13, so a bad storage folder is never created)
	validate_storage_path_is_outside_input_folder(input_path, storage_path)

	# 13. storage_path must be creatable and writable
	validate_storage_path_is_writable(storage_path)


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


def validate_hugging_face_split_is_not_empty(hugging_face_split):
	"""
	Input: hugging_face_split - the split read from a Hugging Face dataset.
	Output: None. Raises TypeError if it is not text, IngestError if it is empty or only spaces.
	Whether the split exists is only found out when the dataset is opened.
	"""
	if not isinstance(hugging_face_split, str):
		raise TypeError("hugging_face_split must be text, got " + type(hugging_face_split).__name__ + ": " + repr(hugging_face_split))

	if hugging_face_split.strip() == "":
		raise IngestError("hugging_face_split must not be empty, got " + repr(hugging_face_split))


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


def validate_input_path_is_not_empty(input_path):
	"""
	Input:
		input_path - the --input_path value.
	Output:
		None. Raises TypeError or IngestError if the check fails.
	What it does:
		Checks that input_path is text and is not empty or made only of
		spaces, tabs or newlines.
	"""
	input_path_is_text = isinstance(input_path, str)
	if not input_path_is_text:
		raise TypeError("input_path must be text, got " + type(input_path).__name__ + ": " + repr(input_path))

	input_path_without_spaces = input_path.strip()
	if input_path_without_spaces == "":
		raise IngestError("input_path must not be empty, got " + repr(input_path))


def validate_input_path_is_not_ambiguous(input_path):
	"""
	Input:
		input_path - the --input_path value, which must already be
		non-empty text.
	Output:
		None. Never raises.
	What it does:
		If input_path is an existing local file or folder and also has the
		shape of a Hugging Face dataset name ("owner/name"), the local path
		wins and a note is printed saying so.
	"""
	if not is_local_path(input_path):
		return

	if not has_hugging_face_name_shape(input_path):
		return

	logger.warning("Note: input_path %r matches a local path and a Hugging Face dataset name. Using the local path.", input_path)


def validate_local_input_path_exists(input_path):
	"""
	Input:
		input_path - the --input_path value.
	Output:
		None. Raises IngestError if the check fails.
	What it does:
		Web URLs are not supported, so a URL fails. A Hugging Face dataset
		name ("owner/name") passes. Anything else must be a local file or
		folder that exists on this machine.
	"""
	if is_url(input_path):
		raise IngestError("input_path must be a local path or a Hugging Face dataset name, web URLs are not supported: " + repr(input_path))

	if has_hugging_face_name_shape(input_path):
		return

	if not is_local_path(input_path):
		raise IngestError("input_path does not exist on this machine: " + repr(input_path))


def validate_storage_path_is_not_empty(storage_path):
	"""
	Input:
		storage_path - the cache folder (cache_dir given to ingest_documents).
	Output:
		None. Raises TypeError or IngestError if the check fails.
	What it does:
		Checks that storage_path is text and is not empty or made only of
		spaces, tabs or newlines.
	"""
	storage_path_is_text = isinstance(storage_path, str)
	if not storage_path_is_text:
		raise TypeError("storage folder must be text, got " + type(storage_path).__name__ + ": " + repr(storage_path))

	storage_path_without_spaces = storage_path.strip()
	if storage_path_without_spaces == "":
		raise IngestError("storage folder must not be empty, got " + repr(storage_path))


def validate_storage_path_is_not_a_file(storage_path):
	"""
	Input:
		storage_path - the cache folder (cache_dir given to ingest_documents).
	Output:
		None. Raises IngestError if the check fails.
	What it does:
		If storage_path already exists, checks that it is a folder and not
		a file. A path that does not exist yet passes, because it will be
		created as a folder.
	"""
	storage_path_exists = os.path.exists(storage_path)
	if not storage_path_exists:
		return

	storage_path_is_folder = os.path.isdir(storage_path)
	if not storage_path_is_folder:
		raise IngestError("storage folder already exists and is a file, not a folder: " + repr(storage_path))


def validate_storage_path_is_outside_input_folder(input_path, storage_path):
	"""
	Input:
		input_path - the --input_path value.
		storage_path - the cache folder (cache_dir given to ingest_documents).
	Output:
		None. Raises IngestError if the check fails.
	What it does:
		If input_path is a local folder, checks that storage_path is not
		that same folder and not anywhere inside it. Otherwise a later run
		would read its own stored files as input documents.
		Both paths are turned into full real paths first (symbolic links
		resolved), so "./data" and "data/" count as the same folder.
		Skipped when input_path is not a local folder (a file or a
		dataset name).
	"""
	input_path_is_folder = os.path.isdir(input_path)
	if not input_path_is_folder:
		return

	real_input_folder = os.path.realpath(input_path)
	real_storage_folder = os.path.realpath(storage_path)

	if real_storage_folder == real_input_folder:
		raise IngestError("storage folder must not be the same folder as input_path: " + repr(storage_path) + ". Choose a cache_dir outside it.")

	shared_parent_folder = os.path.commonpath([real_input_folder, real_storage_folder])
	storage_is_inside_input = shared_parent_folder == real_input_folder
	if storage_is_inside_input:
		raise IngestError("storage folder must not be inside the input_path folder: " + repr(storage_path) + ". Choose a cache_dir outside it.")


def validate_storage_path_is_writable(storage_path):
	"""
	Input:
		storage_path - the cache folder (cache_dir given to ingest_documents).
	Output:
		None. Raises IngestError if the check fails.
	What it does:
		Creates the storage_path folder if it does not exist yet, then
		writes a small temporary test file inside it and deletes it again.
		This is the most reliable way to know that results can be saved
		there. Raises an error if the folder cannot be created or the
		test file cannot be written.
	"""
	try:
		os.makedirs(storage_path, exist_ok=True)
	except OSError as create_error:
		raise IngestError("storage folder could not be created: " + repr(storage_path) + " (" + str(create_error) + ")")

	try:
		with tempfile.TemporaryFile(dir=storage_path) as test_file:
			test_file.write(b"write test")
	except OSError as write_error:
		raise IngestError("storage folder is not writable: " + repr(storage_path) + " (" + str(write_error) + ")")


def is_local_path(path):
	"""
	Input:
		path - a file or folder path.
	Output:
		True if path is an existing file or folder on this machine,
		otherwise False.
	What it does:
		Checks the local file system for path.
	"""
	path_exists = os.path.exists(path)
	return path_exists
