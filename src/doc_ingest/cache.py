import logging
import os
import json

from doc_ingest.schema import Document
from doc_ingest.error import describe_error

logger = logging.getLogger(__name__)

# Name of this library's folder inside the user's cache folder
CACHE_FOLDER_NAME = "doc_ingest"

# Optional environment variable that sets the storage folder directly
CACHE_DIR_ENV_VAR = "DOC_INGEST_CACHE_DIR"


def get_storage_path() -> str:
	"""
	Input: none. Output: the folder where raw files, processed documents
	and progress are stored: $DOC_INGEST_CACHE_DIR if set, else
	$XDG_CACHE_HOME/doc_ingest if set, else ~/.cache/doc_ingest.
	"""
	chosen_storage_path = os.environ.get(CACHE_DIR_ENV_VAR, "")
	if chosen_storage_path != "":
		expanded_storage_path = os.path.expanduser(chosen_storage_path)
		return expanded_storage_path

	user_cache_folder = os.environ.get("XDG_CACHE_HOME", "")
	if user_cache_folder == "":
		user_cache_folder = os.path.join(os.path.expanduser("~"), ".cache")

	storage_path = os.path.join(user_cache_folder, CACHE_FOLDER_NAME)
	return storage_path


def get_processed_document_path(storage_path: str, dataset_name: str, doc_id: str) -> str:
	"""
	Input:
		storage_path - the storage folder (cache.get_storage_path()).
		dataset_name - name of the dataset (from get_dataset_name).
		doc_id - id of the processed document.
	Output:
		Path of the document's cached JSON file, for example
		"~/.cache/doc_ingest/<dataset_name>/data/processed/<doc_id>.json".
	What it does:
		Builds the path where a processed document is cached.
	"""
	processed_document_file_name = f"{doc_id}.json"
	processed_document_path = os.path.join(f"{storage_path}/{dataset_name}/data/processed/", processed_document_file_name)
	return processed_document_path


def load_processed_document(storage_path: str, dataset_name: str, doc_id: str) -> Document | None:
	"""
	Input:
		storage_path - the storage folder (cache.get_storage_path()).
		dataset_name - name of the dataset (from get_dataset_name).
		doc_id - id of the processed document.
	Output:
		The cached Document, or None if no cached file exists for doc_id
		or the file is damaged.
	What it does:
		Reads the document's cached JSON file and turns it into a Document.
		Pydantic checks the file against the schema while reading it. If
		the file cannot be read, is not valid UTF-8 JSON, or a field is
		missing or has the wrong type, a message is printed and None is
		returned, so one damaged file does not stop the run.
	"""
	processed_document_path = get_processed_document_path(storage_path, dataset_name, doc_id)
	if not os.path.exists(processed_document_path):
		return None

	# pydantic.ValidationError and UnicodeDecodeError are both ValueErrors
	try:
		with open(processed_document_path, encoding="utf-8") as processed_document_file:
			processed_document_json = processed_document_file.read()
		processed_document = Document.model_validate_json(processed_document_json)
	except (OSError, ValueError) as load_error:
		logger.warning("Cached document %s is damaged: %s (%s)", doc_id, processed_document_path, describe_error(load_error))
		return None

	return processed_document

def save_processed_document(storage_path: str, dataset_name: str, document: Document):
	"""
	Input:
		storage_path - the storage folder (cache.get_storage_path()).
		dataset_name - name of the dataset (DatasetConfig.name).
		document - the processed Document to cache.
	Output:
		None.
	What it does:
		Writes the document as JSON to its cached file (see
		get_processed_document_path), creating the processed/ folder if
		needed. The JSON is first written to a temporary file next to it,
		which then replaces the cached file in one step. If the program
		stops halfway through writing, only the temporary file is left
		incomplete, so load_processed_document never reads a half-written
		cached file.
	"""
	processed_document_path = get_processed_document_path(storage_path, dataset_name, document.id)
	temporary_document_path = f"{processed_document_path}.tmp"

	# Turned into JSON before any file is opened, so a document that cannot
	# be saved as JSON leaves no empty temporary file behind
	document_json = document.model_dump_json()

	os.makedirs(os.path.dirname(processed_document_path), exist_ok=True)

	with open(temporary_document_path, "w", encoding="utf-8") as f:
		f.write(document_json)

	os.replace(temporary_document_path, processed_document_path)
