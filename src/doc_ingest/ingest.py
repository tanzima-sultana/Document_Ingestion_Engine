
import concurrent.futures
import multiprocessing
import os
import time

from doc_ingest.schema import Document
from doc_ingest.raw_data import RawDataFetcher
from doc_ingest.dedup import Deduplicator
from doc_ingest.summary import Summary
from doc_ingest.summary import print_run_summary

from doc_ingest import dataset_config
from doc_ingest import progress
from doc_ingest import validate
from doc_ingest import cache
from doc_ingest import parser

# Number of documents sent to a parse worker process in one go
PARSE_DOC_COUNT = 16

# Default number of documents downloaded/decoded at the same time
DEFAULT_DOWNLOAD_WORKERS = 64

def ingest_documents(size: int, input_path: str, *, download_workers: int = DEFAULT_DOWNLOAD_WORKERS, parse_workers: int | None = None) -> list[Document]:
	"""
	Input:
		size - maximum number of documents to return.
		input_path - the --input_path value: a local file or folder, a
		Hugging Face dataset name, or its Hugging Face page URL.
		download_workers - optional; documents downloaded/decoded at the
		same time (default DEFAULT_DOWNLOAD_WORKERS).
		parse_workers - optional; documents parsed at the same time, one
		process each (default: number of CPU cores).
	Output:
		A list of the collected Documents.
	What it does:
		First turns a Hugging Face dataset page URL into the dataset name
		(dataset_config.normalize_input_path). Then checks size, input_path and the storage folder with
		validate.validate_inputs, which raises TypeError or ValueError if
		a check fails. Raw files, processed documents and progress are
		stored under cache.get_storage_path().
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
	run_start = time.perf_counter()
	documents = {}
	storage_path = cache.get_storage_path()

	# 0. Validate inputs before any work is done.
	# A Hugging Face dataset page URL is turned into the dataset name first.
	input_path = dataset_config.normalize_input_path(input_path)
	validate.validate_inputs(size, input_path, storage_path)

	summary = Summary()
	summary.requested_size = size

	# 1. Get dataset config
	db_config = dataset_config.get_dataset_config(input_path)

	# 2. Load progress
	saved_progress = progress.load_progress(storage_path, db_config.name)

	raw_data_count = saved_progress.raw_data_count
	processed_doc_ids = []
	skipped_doc_ids = set(saved_progress.skipped_doc_ids)

	# 3. Check cached processed documents

	deduplicator = Deduplicator(threshold=0.90)

	cached_index = 0
	while cached_index < len(saved_progress.processed_doc_ids):
		doc_id = saved_progress.processed_doc_ids[cached_index]
		cached_index += 1

		cached_doc = cache.load_processed_document(storage_path, db_config.name, doc_id)
		# If a processed doc is missing or damaged on disk
		if cached_doc is None:
			print(f"Processed document {doc_id} is missing or damaged on disk, marking it as skipped.")
			skipped_doc_ids.add(doc_id)
			summary.cache_missing += 1
			summary.skipped += 1
			continue

		processed_doc_ids.append(doc_id)
		documents[doc_id] = cached_doc
		deduplicator.add(cached_doc)
		summary.loaded_from_cache += 1

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
			progress.save_progress(storage_path, db_config.name, updated_progress)
			print(f"Loaded {len(documents)} already processed document(s). Nothing new to process.")
			summary.returned_size = len(documents)
			summary.total_seconds = time.perf_counter() - run_start
			print_run_summary(summary)
			document_list = list(documents.values())
			return document_list


	# 4. Fetch raw data in batches, then process each batch
	raw_data_fetcher = RawDataFetcher(input_path, storage_path, db_config, download_workers)
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

			download_start = time.perf_counter()
			raw_batch = raw_data_fetcher.fetch_raw_batch(row_iterator, rows_needed)
			summary.download_seconds += time.perf_counter() - download_start
			raw_items = raw_batch.raw_items
			raw_data_count += raw_batch.rows_read
			source_exhausted = raw_batch.source_exhausted

			summary.rows += raw_batch.rows_read
			summary.downloaded += raw_batch.downloaded
			summary.download_failed += raw_batch.rows_read - raw_batch.downloaded
			summary.unsupported_type += raw_batch.downloaded - len(raw_items)
			
			# 4b. Leave out documents that were skipped before
			parse_items = []
			for raw_data in raw_items:
				if raw_data.doc_id in skipped_doc_ids:
					continue
				parse_items.append(raw_data)

			# 4c. Parse them in parallel, in parse_workers processes.
			# executor.map returns results in the same order as parse_items.
			# Results arrive while 4d loops over them, so parse time covers 4c and 4d.
			parse_start = time.perf_counter()
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
					summary.skipped += 1
					summary.parse_error += 1
					continue
		
				# No text, e.g. a scanned PDF
				if doc.text.strip() == "":
					print(f"Skipping document {doc_id}: no text")
					skipped_doc_ids.add(doc_id)
					summary.skipped += 1
					summary.no_text += 1
					continue

				# Duplicate
				if not deduplicator.add_if_new(doc):
					summary.duplicate += 1
					continue
				
				processed_doc_ids.append(doc_id)
				documents[doc_id] = doc
				cache.save_processed_document(storage_path, db_config.name, doc)
				summary.processed += 1

			summary.parse_seconds += time.perf_counter() - parse_start

			# 4e. Save progress after every batch
			updated_progress = progress.make_progress(
				db_config.name,
				raw_data_count,
				processed_doc_ids,
				list(skipped_doc_ids),
			)
			progress.save_progress(storage_path, db_config.name, updated_progress)

	# Run
	summary.returned_size = len(documents)
	summary.source_exhausted = source_exhausted
	summary.batches = batch_number
	summary.total_seconds = time.perf_counter() - run_start
	print_run_summary(summary)

	document_list = list(documents.values())
	return document_list

