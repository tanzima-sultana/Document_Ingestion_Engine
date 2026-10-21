import os

from doc_ingest.schema import Document


def get_processed_document_path(storage_path: str, dataset_name: str, doc_id: str) -> str:
	"""
	Input:
		storage_path - the run's temporary storage folder.
		dataset_name - name of the dataset (from get_dataset_name).
		doc_id - id of the processed document.
	Output:
		Path of the document's JSON file, for example
		"<storage_path>/data_<dataset_name>/processed/<doc_id>.json".
	What it does:
		Builds the path where a processed document is saved.
	"""
	processed_document_file_name = f"{doc_id}.json"
	processed_document_path = os.path.join(f"{storage_path}/data_{dataset_name}/processed/", processed_document_file_name)
	return processed_document_path


def save_processed_document(storage_path: str, dataset_name: str, document: Document):
	"""
	Input:
		storage_path - the run's temporary storage folder.
		dataset_name - name of the dataset (DatasetConfig.name).
		document - the processed Document to save.
	Output:
		None.
	What it does:
		Writes the document as JSON to its file (see
		get_processed_document_path), creating the processed/ folder if
		needed. The JSON is first written to a temporary file next to it,
		which then replaces the document's file in one step, so the file
		is never left half-written.
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
