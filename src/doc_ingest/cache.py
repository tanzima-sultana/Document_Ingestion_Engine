import os
import json
from doc_ingest.schema import Document


def get_processed_document_path(output_path: str, dataset_name: str, doc_id: str) -> str:
	"""
	Input:
		output_path - the --output_path folder.
		dataset_name - name of the dataset (from get_dataset_name).
		doc_id - id of the processed document.
	Output:
		Path of the document's cached JSON file, for example
		"outputs/<dataset_name>/data/processed/<doc_id>.json".
	What it does:
		Builds the path where a processed document is cached.
	"""
	processed_document_file_name = f"{doc_id}.json"
	processed_document_path = os.path.join(f"{output_path}/{dataset_name}/data/processed/", processed_document_file_name)
	return processed_document_path


def load_processed_document(output_path: str, dataset_name: str, doc_id: str) -> Document | None:
	"""
	Input:
		output_path - the --output_path folder.
		dataset_name - name of the dataset (from get_dataset_name).
		doc_id - id of the processed document.
	Output:
		The cached Document, or None if no cached file exists for doc_id.
	What it does:
		Reads the document's cached JSON file and turns it into a Document.
		Pydantic checks the file against the schema while reading it and
		raises pydantic.ValidationError if a field is missing or has the
		wrong type.
	"""
	processed_document_path = get_processed_document_path(output_path, dataset_name, doc_id)
	if not os.path.exists(processed_document_path):
		return None

	with open(processed_document_path, encoding="utf-8") as processed_document_file:
		processed_document_json = processed_document_file.read()

	processed_document = Document.model_validate_json(processed_document_json)
	return processed_document

def save_processed_document(output_path: str, dataset_name: str, document: Document):
	"""
	Input:
		output_path - the --output_path folder.
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
	processed_document_path = get_processed_document_path(output_path, dataset_name, document.id)
	temporary_document_path = f"{processed_document_path}.tmp"

	os.makedirs(os.path.dirname(processed_document_path), exist_ok=True)

	with open(temporary_document_path, "w", encoding="utf-8") as f:
		f.write(document.model_dump_json())

	os.replace(temporary_document_path, processed_document_path)
