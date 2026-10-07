import os
import tempfile

from doc_ingest.dataset_config import has_hugging_face_name_shape
from doc_ingest.dataset_config import is_url


class IngestError(ValueError):
	"""
	A problem the user can fix (bad input, unusable storage folder, damaged
	progress file). The CLI prints only its message, without a traceback.
	"""


def validate_inputs(size: int, input_path: str, storage_path: str):
	"""
	Input:
		size - maximum number of documents to process.
		input_path - where to read documents from.
		storage_path - folder where raw files, processed documents and progress are stored.
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

	# 3. input_path must not be empty or only spaces
	validate_input_path_is_not_empty(input_path)

	# 4. input_path must not match more than one kind of input
	validate_input_path_is_not_ambiguous(input_path)

	# 5. input_path must be a local path that exists or a Hugging Face dataset name
	validate_local_input_path_exists(input_path)

	# 6. storage_path must not be empty or only spaces
	validate_storage_path_is_not_empty(storage_path)

	# 7. if storage_path already exists, it must be a folder, not a file
	validate_storage_path_is_not_a_file(storage_path)

	# 8. storage_path must not be the input folder or inside it
	# (runs before 9, so a bad storage folder is never created)
	validate_storage_path_is_outside_input_folder(input_path, storage_path)

	# 9. storage_path must be creatable and writable
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

	print("Note: input_path " + repr(input_path) + " matches a local path and a Hugging Face dataset name. Using the local path.")


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
		storage_path - the storage folder from cache.get_storage_path().
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
		storage_path - the storage folder from cache.get_storage_path().
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
		storage_path - the storage folder from cache.get_storage_path().
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
		raise IngestError("storage folder must not be the same folder as input_path: " + repr(storage_path) + ". Set DOC_INGEST_CACHE_DIR to a folder outside it.")

	shared_parent_folder = os.path.commonpath([real_input_folder, real_storage_folder])
	storage_is_inside_input = shared_parent_folder == real_input_folder
	if storage_is_inside_input:
		raise IngestError("storage folder must not be inside the input_path folder: " + repr(storage_path) + ". Set DOC_INGEST_CACHE_DIR to a folder outside it.")


def validate_storage_path_is_writable(storage_path):
	"""
	Input:
		storage_path - the storage folder from cache.get_storage_path().
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
