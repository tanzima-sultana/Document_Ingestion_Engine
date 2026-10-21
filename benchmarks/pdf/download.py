"""
Benchmark data: download the first <size> PDFs of a Hugging Face dataset into a local folder once,
so every benchmark run (LangChain and doc_ingest) reads exactly the same files from disk.
"""

import argparse
import os

import yaml

# Written into the folder after a complete download. Hidden (starts with "."), so neither tool parses it.
COMPLETE_MARKER_FILE_NAME = ".download_complete"


def load_config(config_path: str) -> dict:
	"""
	Input: config_path - the benchmark's config.yaml.
	Output: the config as a dict.
	"""
	with open(config_path, encoding="utf-8") as config_file:
		config = yaml.safe_load(config_file)
	return config


def download_pdfs(dataset_name: str, hugging_face_split: str, size: int, input_path: str) -> None:
	"""
	Input: dataset_name and hugging_face_split - the Hugging Face dataset to read; size - rows to save; input_path - the folder to fill.
	Output: none. Saves row i's PDF bytes as <input_path>/<i>.pdf (zero padded, so name order is row order), then writes the complete marker.
	A row without PDF bytes is reported and not saved.
	"""
	# Imported here so the already-downloaded case does not pay the import cost
	from datasets import load_dataset

	os.makedirs(input_path, exist_ok=True)

	dataset = load_dataset(dataset_name, split=hugging_face_split, streaming=True)
	# Keep the pdf column as raw bytes instead of opening it
	dataset = dataset.decode(False)

	rows_saved = 0
	rows_without_pdf = 0
	row_index = 0
	for row in dataset:
		if row_index == size:
			break

		pdf_bytes = row.get("pdf")
		if isinstance(pdf_bytes, bytes):
			file_path = os.path.join(input_path, f"{row_index:06d}.pdf")
			with open(file_path, "wb") as pdf_file:
				pdf_file.write(pdf_bytes)
			rows_saved = rows_saved + 1
		else:
			print(f"Row {row_index} has no PDF bytes, not saved")
			rows_without_pdf = rows_without_pdf + 1

		row_index = row_index + 1
		if row_index % 500 == 0:
			print(f"Downloaded {row_index} of {size} rows")

	marker_path = os.path.join(input_path, COMPLETE_MARKER_FILE_NAME)
	with open(marker_path, "w", encoding="utf-8") as marker_file:
		marker_file.write(f"rows_read: {row_index}\nrows_saved: {rows_saved}\nrows_without_pdf: {rows_without_pdf}\n")

	print(f"Download finished: {rows_saved} PDF(s) saved to {input_path} ({rows_without_pdf} row(s) without PDF bytes)")


def main() -> None:
	"""
	Input: --config_path from the command line (run.sh passes it).
	Output: none. Downloads the PDFs unless input_path already holds a complete download.
	"""
	argument_parser = argparse.ArgumentParser(description="Download benchmark PDFs once into a local folder.")
	argument_parser.add_argument("--config_path", required=True, help="The benchmark's config.yaml")
	arguments = argument_parser.parse_args()

	config = load_config(arguments.config_path)
	dataset_name = config["dataset"]
	size = config["size"]
	input_path = config["input_path"]
	hugging_face_split = config["download_settings"]["hugging_face_split"]

	marker_path = os.path.join(input_path, COMPLETE_MARKER_FILE_NAME)
	if os.path.exists(marker_path):
		print(f"Benchmark data already downloaded: {input_path}")
		return

	print(f"Downloading {size} rows of {dataset_name} (split {hugging_face_split}) to {input_path}")
	download_pdfs(dataset_name, hugging_face_split, size, input_path)


if __name__ == "__main__":
	main()
