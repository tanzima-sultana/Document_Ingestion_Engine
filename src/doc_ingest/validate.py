import os
import tempfile
import urllib.error
import urllib.request

from doc_ingest.dataset_config import URL_TIMEOUT_SECONDS
from doc_ingest.dataset_config import build_url_request
from doc_ingest.dataset_config import has_hugging_face_name_shape
from doc_ingest.dataset_config import is_url


def validate_inputs(size: int, input_path: str, output_path: str):
	"""
	Input:
		size - maximum number of documents to process.
		input_path - where to read documents from.
		output_path - folder where the output is written.
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

	# 5. local input_path must exist on this machine
	validate_local_input_path_exists(input_path)

	# 6. url input_path must be reachable
	validate_url_input_path_exists(input_path)

	# 7. output_path must not be empty or only spaces
	validate_output_path_is_not_empty(output_path)

	# 8. if output_path already exists, it must be a folder, not a file
	validate_output_path_is_not_a_file(output_path)

	# 9. output_path must not be the input folder or inside it
	# (runs before 10, so a bad output folder is never created)
	validate_output_path_is_outside_input_folder(input_path, output_path)

	# 10. output_path must be creatable and writable
	validate_output_path_is_writable(output_path)


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
		None. Raises ValueError if the check fails.
	What it does:
		Checks that size is greater than 0, so at least one document
		will be processed.
	"""
	if size <= 0:
		raise ValueError("size must be greater than 0, got " + str(size))


def validate_input_path_is_not_empty(input_path):
	"""
	Input:
		input_path - the --input_path value.
	Output:
		None. Raises TypeError or ValueError if the check fails.
	What it does:
		Checks that input_path is text and is not empty or made only of
		spaces, tabs or newlines.
	"""
	input_path_is_text = isinstance(input_path, str)
	if not input_path_is_text:
		raise TypeError("input_path must be text, got " + type(input_path).__name__ + ": " + repr(input_path))

	input_path_without_spaces = input_path.strip()
	if input_path_without_spaces == "":
		raise ValueError("input_path must not be empty, got " + repr(input_path))


def validate_input_path_is_not_ambiguous(input_path):
	"""
	Input:
		input_path - the --input_path value, which must already be
		non-empty text.
	Output:
		None. Raises ValueError if the kind cannot be decided.
	What it does:
		Works out which kinds of input the path matches: an existing local
		file or folder, a web URL, or a Hugging Face dataset name.
		If it matches more than one kind and one of them is local, the
		local path wins and a note is printed saying so.
		If it matches more than one kind and none is local, there is no
		safe choice, so it raises an error.
		Paths that match no kind are left for the later input checks.
	"""
	matched_kinds = []

	if is_local_path(input_path):
		matched_kinds.append("local")

	if is_url(input_path):
		matched_kinds.append("url")

	if has_hugging_face_name_shape(input_path):
		matched_kinds.append("huggingface_dataset")

	if len(matched_kinds) <= 1:
		return

	if "local" in matched_kinds:
		print(
			"Note: input_path " + repr(input_path) + " matches "
			+ ", ".join(matched_kinds) + ". Using the local path."
		)
		return

	raise ValueError(
		"input_path " + repr(input_path) + " is ambiguous, it matches "
		+ ", ".join(matched_kinds)
	)


def validate_local_input_path_exists(input_path):
	"""
	Input:
		input_path - the --input_path value.
	Output:
		None. Raises ValueError if the check fails.
	What it does:
		If input_path is meant to be a local file or folder (it is not a
		URL and not a Hugging Face dataset name), checks that it exists on
		this machine. URLs and dataset names are skipped.
	"""
	if is_url(input_path):
		return

	if has_hugging_face_name_shape(input_path):
		return

	if not is_local_path(input_path):
		raise ValueError("input_path does not exist on this machine: " + repr(input_path))


def validate_url_input_path_exists(input_path):
	"""
	Input:
		input_path - the --input_path value.
	Output:
		None. Raises ValueError if the check fails.
	What it does:
		If input_path is a URL, asks the web server whether the page or
		file exists. It first sends a HEAD request (headers only, no
		download). Some servers refuse HEAD, so on a 403 or 405 answer it
		tries a normal GET request and closes it without reading the body.
		Raises an error if the server answers with an error code (for
		example 404), cannot be reached, or does not answer within
		URL_TIMEOUT_SECONDS. Inputs that are not URLs are skipped.
	"""
	if not is_url(input_path):
		return

	try:
		request_url_and_close(input_path, "HEAD")
	except urllib.error.HTTPError as head_error:
		head_was_refused = head_error.code in (403, 405)
		if not head_was_refused:
			raise ValueError("input_path URL returned HTTP " + str(head_error.code) + ": " + input_path)

		try:
			request_url_and_close(input_path, "GET")
		except urllib.error.HTTPError as get_error:
			raise ValueError("input_path URL returned HTTP " + str(get_error.code) + ": " + input_path)
		except (urllib.error.URLError, OSError) as get_connection_error:
			raise ValueError("input_path URL could not be reached: " + input_path + " (" + str(get_connection_error) + ")")
	except (urllib.error.URLError, OSError) as head_connection_error:
		raise ValueError("input_path URL could not be reached: " + input_path + " (" + str(head_connection_error) + ")")


def request_url_and_close(url, request_method):
	"""
	Input:
		url - the web address to request.
		request_method - "HEAD" or "GET".
	Output:
		None. Raises urllib.error.HTTPError for error answers (400 and
		above), and urllib.error.URLError or OSError when the server
		cannot be reached or times out.
	What it does:
		Sends one request to url, follows redirects, and closes the
		connection straight away without downloading the body.
	"""
	url_request = build_url_request(url, request_method, {})
	with urllib.request.urlopen(url_request, timeout=URL_TIMEOUT_SECONDS):
		pass


def validate_output_path_is_not_empty(output_path):
	"""
	Input:
		output_path - the --output_path value.
	Output:
		None. Raises TypeError or ValueError if the check fails.
	What it does:
		Checks that output_path is text and is not empty or made only of
		spaces, tabs or newlines.
	"""
	output_path_is_text = isinstance(output_path, str)
	if not output_path_is_text:
		raise TypeError("output_path must be text, got " + type(output_path).__name__ + ": " + repr(output_path))

	output_path_without_spaces = output_path.strip()
	if output_path_without_spaces == "":
		raise ValueError("output_path must not be empty, got " + repr(output_path))


def validate_output_path_is_not_a_file(output_path):
	"""
	Input:
		output_path - the --output_path value.
	Output:
		None. Raises ValueError if the check fails.
	What it does:
		If output_path already exists, checks that it is a folder and not
		a file. A path that does not exist yet passes, because it will be
		created as a folder.
	"""
	output_path_exists = os.path.exists(output_path)
	if not output_path_exists:
		return

	output_path_is_folder = os.path.isdir(output_path)
	if not output_path_is_folder:
		raise ValueError("output_path already exists and is a file, not a folder: " + repr(output_path))


def validate_output_path_is_outside_input_folder(input_path, output_path):
	"""
	Input:
		input_path - the --input_path value.
		output_path - the --output_path value.
	Output:
		None. Raises ValueError if the check fails.
	What it does:
		If input_path is a local folder, checks that output_path is not
		that same folder and not anywhere inside it. Otherwise a later run
		would read its own output files as input documents.
		Both paths are turned into full real paths first (symbolic links
		resolved), so "./data" and "data/" count as the same folder.
		Skipped when input_path is not a local folder (a file, URL or
		dataset name).
	"""
	input_path_is_folder = os.path.isdir(input_path)
	if not input_path_is_folder:
		return

	real_input_folder = os.path.realpath(input_path)
	real_output_folder = os.path.realpath(output_path)

	if real_output_folder == real_input_folder:
		raise ValueError("output_path must not be the same folder as input_path: " + repr(output_path))

	shared_parent_folder = os.path.commonpath([real_input_folder, real_output_folder])
	output_is_inside_input = shared_parent_folder == real_input_folder
	if output_is_inside_input:
		raise ValueError("output_path must not be inside the input_path folder: " + repr(output_path))


def validate_output_path_is_writable(output_path):
	"""
	Input:
		output_path - the --output_path value.
	Output:
		None. Raises ValueError if the check fails.
	What it does:
		Creates the output_path folder if it does not exist yet, then
		writes a small temporary test file inside it and deletes it again.
		This is the most reliable way to know that results can be saved
		there. Raises an error if the folder cannot be created or the
		test file cannot be written.
	"""
	try:
		os.makedirs(output_path, exist_ok=True)
	except OSError as create_error:
		raise ValueError("output_path folder could not be created: " + repr(output_path) + " (" + str(create_error) + ")")

	try:
		with tempfile.TemporaryFile(dir=output_path) as test_file:
			test_file.write(b"write test")
	except OSError as write_error:
		raise ValueError("output_path folder is not writable: " + repr(output_path) + " (" + str(write_error) + ")")


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
