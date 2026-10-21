"""
dataset/local.py

Local datasets: a single document file, a folder of document files, or
JSONL/JSON container files holding many documents as records.
"""

import json
import os

from doc_ingest.dataset.document_type import EXTENSION_TO_DOCUMENT_TYPE
from doc_ingest.dataset.document_type import get_extension_of_file


# Extensions of files that hold many documents as records, with each
# document's content stored inside one field of the record.
CONTAINER_EXTENSIONS = [
	"jsonl",
	"json",
]

# Value of DatasetConfig.format for a local folder of document files. The
# files can be of different types; each file's type comes from its own
# extension.
FOLDER_FORMAT = "folder"

def get_local_dataset_format(path) -> str:
	"""
	Input: path to a local dataset file or directory.
	Output: the dataset format, which decides how the dataset is read:
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


def get_local_dataset_size(path, dataset_format: str) -> int:
	"""
	Input: path to a local dataset file or directory; dataset_format - its format (see get_local_dataset_format).
	Output: the number of documents, or -1 if it is unknown.
	What it does: container datasets (JSONL/JSON) give -1, because counting records means reading every
	line or the whole file; a single file gives 1; a directory gives the number of files with a supported
	document extension (other files are ignored by ingestion anyway).
	"""
	if dataset_format in CONTAINER_EXTENSIONS:
		return -1

	if os.path.isfile(path):
		return 1

	document_count = 0
	for file_path in list_dataset_files(path):
		if get_extension_of_file(file_path) in EXTENSION_TO_DOCUMENT_TYPE:
			document_count = document_count + 1

	return document_count


def read_first_local_record(path) -> dict:
	"""
	Input: path to a local container dataset (JSONL/JSON file or directory of them).
	Output: the first record as a dict.
	What it does: finds the first container file, then reads its first
	record. For JSONL, that is the first non-empty line. For JSON, the file
	must hold either one object or a list of objects; the first object is
	returned. Raises ValueError if no record can be found.
	"""
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
