
import concurrent.futures
import multiprocessing

from doc_ingest.schema import Document
from doc_ingest.raw_data import RawData
from doc_ingest.dedup import Deduplicator

from doc_ingest import dataset_config
from doc_ingest import progress
from doc_ingest import cache
from doc_ingest import parser


# Number of documents parsed at the same time, each in its own process
PARSE_WORKERS = 16

# Number of documents sent to a parse worker process in one go
PARSE_DOC_COUNT = 16

def ingest_documents(size: int, input_path: str, output_path: str) -> dict[str, Document]:
	"""
	Input:
		size - maximum number of documents to return.
		input_path - the --input_path value: a local file or folder, a web
		URL, or a Hugging Face dataset name.
		output_path - the --output_path folder, which also holds the cache
		of processed documents.
	Output:
		A dict that maps each document id to its Document.
	What it does:
		Works out the dataset name, loads the saved progress for it, and
		reads back documents that were already processed from the cache.
		A processed document whose cached file is missing is marked as
		skipped. Once size documents have been loaded, it saves the
		progress and returns them.
	"""
	documents = {}

	# 1. Get dataset name
	config = dataset_config.get_dataset_config(input_path)

	# 2. Load progress
	saved_progress = progress.load_progress(config.name)

	raw_data_count = saved_progress.raw_data_count
	processed_doc_ids = []
	skipped_doc_ids = set(saved_progress.skipped_doc_ids)

	# 3. Check cached processed documents

	deduplicator = Deduplicator(threshold=0.90)

	cached_index = 0
	while cached_index < len(saved_progress.processed_doc_ids):
		doc_id = saved_progress.processed_doc_ids[cached_index]
		cached_index += 1

		cached_doc = cache.load_processed_document(output_path, config.name, doc_id)
		# If a processed doc is physically removed somehow
		if cached_doc is None:
			print(f"Processed document {doc_id} is missing on disk, marking it as skipped.")
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
				config.name,
				raw_data_count,
				all_processed_doc_ids,
				list(skipped_doc_ids),
			)
			progress.save_progress(config.name, updated_progress)
			print(f"Loaded {len(documents)} already processed document(s). Nothing new to process.")
			return documents
	

	# 4. Fetch raw data in batches, then process each batch
	raw_data = RawData(input_path, output_path, config)
	row_iterator = raw_data.get_iterator(raw_data_count)

	batch_number = 0
	source_exhausted = False

	spawn_context = multiprocessing.get_context("spawn")
	with concurrent.futures.ProcessPoolExecutor(max_workers=PARSE_WORKERS, mp_context=spawn_context) as parse_executor:

		while len(documents) < size and not source_exhausted:

			# 4a. Download/decode as many rows as documents still missing,
			# at most raw_data.MAX_BATCH_ROWS per batch
			batch_number += 1
			rows_needed = size - len(documents)
			print(f"Batch {batch_number}: fetching {rows_needed} row(s).")

			raw_batch = raw_data.fetch_raw_batch(row_iterator, rows_needed)
			raw_items = raw_batch.items
			raw_data_count += raw_batch.count
			source_exhausted = raw_batch.source_exhausted

			# 4b. Collect the batch's documents that still need parsing
			# Need list to parallel process
			doc_type_to_parse = []
			doc_ids_to_parse = []
			source_paths_to_parse = []
			for doc_id, source_path in raw_items:
				if doc_id in skipped_doc_ids:
					continue
				doc_type_to_parse.append(config.doc_type)
				doc_ids_to_parse.append(doc_id)
				source_paths_to_parse.append(source_path)
			
			# 4c. Parse them in parallel, in PARSE_WORKERS processes.
			# executor.map returns results in the same order as doc_ids_to_parse
			processed_docs= parse_executor.map(
					parser.parse_document,
					doc_type_to_parse,
					doc_ids_to_parse,
					source_paths_to_parse,
					chunksize=PARSE_DOC_COUNT,
			)

			for doc_id, doc in processed_docs:

				# Skipped
				if not doc:
					print(f"Skipping document {doc_id}: parse failed")
					skipped_doc_ids.add(doc_id)
					continue

				# Duplicate
				if not deduplicator.add_if_new(doc):
					continue
				
				processed_doc_ids.append(doc_id)
				documents[doc_id] = doc
				cache.save_processed_document(output_path, config.name, doc)

			# 4e. Save progress after every batch
			updated_progress = progress.make_progress(
				config.name,
				raw_data_count,
				processed_doc_ids,
				list(skipped_doc_ids),
			)
			progress.save_progress(config.name, updated_progress)


	return documents

