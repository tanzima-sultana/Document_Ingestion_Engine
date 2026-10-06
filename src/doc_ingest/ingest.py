
import concurrent.futures
import multiprocessing
import os

from doc_ingest.schema import Document
from doc_ingest.raw_data import RawDataFetcher
from doc_ingest.dedup import Deduplicator

from doc_ingest import dataset_config
from doc_ingest import progress
from doc_ingest import cache
from doc_ingest import parser


# Number of documents sent to a parse worker process in one go
PARSE_DOC_COUNT = 16

# Default number of documents downloaded/decoded at the same time
DEFAULT_DOWNLOAD_WORKERS = 64

def ingest_documents(size: int, input_path: str, output_path: str, *, download_workers: int = DEFAULT_DOWNLOAD_WORKERS, parse_workers: int | None = None) -> dict[str, Document]:
	"""
	Input:
		size - maximum number of documents to return.
		input_path - the --input_path value: a local file or folder, a web
		URL, or a Hugging Face dataset name.
		output_path - the --output_path folder, which also holds the cache
		of processed documents.
		download_workers - optional; documents downloaded/decoded at the
		same time (default DEFAULT_DOWNLOAD_WORKERS).
		parse_workers - optional; documents parsed at the same time, one
		process each (default: number of CPU cores).
	Output:
		A dict that maps each document id to its Document.
	What it does:
		Works out the dataset config, loads the saved progress for it, and
		reads back documents that were already processed from the cache.
		A processed document whose cached file is missing or damaged is
		marked as skipped. If size documents have been loaded, it saves the progress
		and returns them.
		Otherwise it reads the dataset in batches, continuing after the
		rows read in earlier runs: each batch is decoded and saved to raw/,
		parsed in parallel worker processes, and checked for exact and
		near duplicates. New documents are cached, and the progress is
		saved after every batch. Stops when size documents are collected
		or the dataset has no more rows.
	"""
	documents = {}

	# 1. Get dataset config
	db_config = dataset_config.get_dataset_config(input_path)

	# 2. Load progress
	saved_progress = progress.load_progress(output_path, db_config.name)

	raw_data_count = saved_progress.raw_data_count
	processed_doc_ids = []
	skipped_doc_ids = set(saved_progress.skipped_doc_ids)

	# 3. Check cached processed documents

	deduplicator = Deduplicator(threshold=0.90)

	cached_index = 0
	while cached_index < len(saved_progress.processed_doc_ids):
		doc_id = saved_progress.processed_doc_ids[cached_index]
		cached_index += 1

		cached_doc = cache.load_processed_document(output_path, db_config.name, doc_id)
		# If a processed doc is missing or damaged on disk
		if cached_doc is None:
			print(f"Processed document {doc_id} is missing or damaged on disk, marking it as skipped.")
			skipped_doc_ids.add(doc_id)
			continue

		processed_doc_ids.append(doc_id)
		documents[doc_id] = cached_doc
		deduplicator.add(cached_doc)

		# if there is dataset_size cached documents already exists
		if len(documents) == size:
			# Keep the not-yet-checked cached ids in progress too
			unchecked_doc_ids = saved_progress.processed_doc_ids[cached_index:]
			all_processed_doc_ids = processed_doc_ids + unchecked_doc_ids
			updated_progress = progress.make_progress(
				db_config.name,
				raw_data_count,
				all_processed_doc_ids,
				list(skipped_doc_ids),
			)
			progress.save_progress(output_path, db_config.name, updated_progress)
			print(f"Loaded {len(documents)} already processed document(s). Nothing new to process.")
			return documents
	

	# 4. Fetch raw data in batches, then process each batch
	raw_data_fetcher = RawDataFetcher(input_path, output_path, db_config, download_workers)
	row_iterator = raw_data_fetcher.get_iterator(raw_data_count)

	batch_number = 0
	source_exhausted = False

	if parse_workers is None:
		parse_workers = os.cpu_count()
		# os.cpu_count() returns None if the core count is unknown
		if parse_workers is None:
			parse_workers = 1

	spawn_context = multiprocessing.get_context("spawn")
	with concurrent.futures.ProcessPoolExecutor(max_workers=parse_workers, mp_context=spawn_context) as parse_executor:

		while len(documents) < size and not source_exhausted:

			# 4a. Download/decode as many rows as documents still missing,
			# at most raw_data.MAX_BATCH_ROWS per batch
			batch_number += 1
			rows_needed = size - len(documents)
			print(f"Batch {batch_number}: fetching {rows_needed} row(s).")

			raw_batch = raw_data_fetcher.fetch_raw_batch(row_iterator, rows_needed)
			raw_items = raw_batch.raw_items
			raw_data_count += raw_batch.rows_read
			source_exhausted = raw_batch.source_exhausted
			
			# 4b. Leave out documents that were skipped before
			parse_items = []
			for raw_data in raw_items:
				if raw_data.doc_id in skipped_doc_ids:
					continue
				parse_items.append(raw_data)

			# 4c. Parse them in parallel, in parse_workers processes.
			# executor.map returns results in the same order as parse_items
			processed_docs= parse_executor.map(
					parser.parse_document,
					parse_items,
					chunksize=PARSE_DOC_COUNT,
			)

			# 4d. Keep each parsed document unless it failed or is a duplicate
			for doc_id, doc in processed_docs:

				# Skipped
				if doc is None:
					print(f"Skipping document {doc_id}: parse failed")
					skipped_doc_ids.add(doc_id)
					continue

				# No text, e.g. a scanned PDF
				if doc.text.strip() == "":
					print(f"Skipping document {doc_id}: no text")
					skipped_doc_ids.add(doc_id)
					continue

				# Duplicate
				if not deduplicator.add_if_new(doc):
					continue
				
				processed_doc_ids.append(doc_id)
				documents[doc_id] = doc
				cache.save_processed_document(output_path, db_config.name, doc)

			# 4e. Save progress after every batch
			updated_progress = progress.make_progress(
				db_config.name,
				raw_data_count,
				processed_doc_ids,
				list(skipped_doc_ids),
			)
			progress.save_progress(output_path, db_config.name, updated_progress)


	return documents

