import dataclasses
import json
import os

from doc_ingest.error import IngestError


@dataclasses.dataclass
class Progress:
	dataset_name: str
	raw_data_count: int
	processed_doc_ids: list[str]
	skipped_doc_ids: list[str]


def make_progress(dataset_name: str, raw_data_count: int, processed_doc_ids: list[str], skipped_doc_ids: list[str]) -> Progress:
	"""
	Input:
		dataset_name - name of the dataset (from get_dataset_name).
		raw_data_count - number of source rows read so far, across all
		runs; the next run continues after them.
		processed_doc_ids - ids of documents already processed.
		skipped_doc_ids - ids of documents that were skipped.
	Output:
		A Progress object holding these values.
	What it does:
		Builds a Progress object from the given values.
	"""
	progress = Progress(
		dataset_name=dataset_name,
		raw_data_count=raw_data_count,
		processed_doc_ids=processed_doc_ids,
		skipped_doc_ids=skipped_doc_ids,
	)
	return progress


def get_progress_path(storage_path: str, dataset_name: str) -> str:
	"""
	Input:
		storage_path - the cache folder (cache_dir given to ingest_documents).
		dataset_name - name of the dataset (from get_dataset_name).
	Output:
		Path of this dataset's progress file, for example
		"~/.cache/doc_ingest/data_docx-corpus/progress.json".
	What it does:
		Keeps the progress file next to the dataset's cached documents, so
		the progress always describes the cache in the same storage folder.
	"""
	progress_path = os.path.join(f"{storage_path}/data_{dataset_name}/", f"progress.json")
	return progress_path


def load_progress(storage_path: str, dataset_name: str) -> Progress:
	"""
	Input:
		storage_path - the cache folder (cache_dir given to ingest_documents).
		dataset_name - name of the dataset (from get_dataset_name).
	Output:
		The saved Progress for this dataset, or an empty Progress (count 0,
		no processed or skipped ids) if nothing was saved yet.
	What it does:
		Reads the dataset's progress file. Raises IngestError if the file is
		damaged, is missing a field, or belongs to a different dataset.
	"""
	progress_path = get_progress_path(storage_path, dataset_name)

	if not os.path.exists(progress_path):
		empty_progress = make_progress(dataset_name, 0, [], [])
		return empty_progress

	try:
		with open(progress_path, encoding="utf-8") as progress_file:
			saved_data = json.load(progress_file)
	except json.JSONDecodeError as decode_error:
		raise IngestError("progress file is damaged and cannot be read: " + progress_path + " (" + str(decode_error) + ")")

	try:
		progress = Progress(
			dataset_name=saved_data["dataset_name"],
			raw_data_count=saved_data["raw_data_count"],
			processed_doc_ids=saved_data["processed_doc_ids"],
			skipped_doc_ids=saved_data["skipped_doc_ids"],
		)
	except (KeyError, TypeError) as missing_field_error:
		raise IngestError("progress file is missing a field: " + progress_path + " (" + str(missing_field_error) + ")")

	if progress.dataset_name != dataset_name:
		raise IngestError(
			"progress file " + progress_path + " belongs to dataset "
			+ repr(progress.dataset_name) + ", not " + repr(dataset_name)
		)

	return progress


def save_progress(storage_path: str, dataset_name: str, progress: Progress) -> None:
	"""
	Input:
		storage_path - the cache folder (cache_dir given to ingest_documents).
		dataset_name - name of the dataset (from get_dataset_name).
		progress - the Progress to save.
	Output:
		None.
	What it does:
		Writes progress to the dataset's progress file. It first writes a
		temporary file and then swaps it into place, so a crash while
		writing never leaves a half-written progress file behind.
	"""
	progress_path = get_progress_path(storage_path, dataset_name)
	temporary_file_path = progress_path + ".tmp"

	progress_folder = os.path.dirname(progress_path)
	if progress_folder != "":
		os.makedirs(progress_folder, exist_ok=True)

	with open(temporary_file_path, "w", encoding="utf-8") as temporary_file:
		json.dump(dataclasses.asdict(progress), temporary_file)

	os.replace(temporary_file_path, progress_path)


def update_progress(storage_path: str, dataset_name: str, raw_data_count: int, processed_doc_ids: list[str], skipped_doc_ids: list[str]) -> None:
	"""
	Input: storage_path, dataset_name, and the progress values (raw_data_count, processed_doc_ids, skipped_doc_ids).
	Output: None.
	What it does: builds a Progress from the values and saves it to the dataset's progress file.
	"""
	updated_progress = make_progress(dataset_name, raw_data_count, processed_doc_ids, skipped_doc_ids)
	save_progress(storage_path, dataset_name, updated_progress)
