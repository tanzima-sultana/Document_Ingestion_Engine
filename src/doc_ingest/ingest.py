
import logging
import concurrent.futures
import dataclasses
import concurrent.futures.process
import multiprocessing
import os
import time

from doc_ingest.schema import Document
from doc_ingest.raw_data import RawDataFetcher
from doc_ingest.dedup import Deduplicator
from doc_ingest.summary import Summary
from doc_ingest.summary import print_run_summary
from doc_ingest.error import describe_error

from doc_ingest import dataset_config
from doc_ingest import dataset_hf
from doc_ingest import progress
from doc_ingest import validate
from doc_ingest import cache
from doc_ingest import parser
from doc_ingest.settings import DownloadSettings
from doc_ingest.settings import ProcessSettings

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class IngestResult:
	"""
	What ingest_documents returns: the collected Documents and the run's Summary
	(counts by skip reason, duplicates, timings).
	"""
	documents: list[Document]
	summary: Summary


class IngestEngine:
	"""
	One ingest run. Holds the run's state (documents, progress ids, summary, deduplicator, parse pool)
	so each step can be a method instead of a function with many parameters.
	"""

	def __init__(self, size: int, input_path: str, download_settings: DownloadSettings, process_settings: ProcessSettings):
		"""
		Input: size, input_path, and the run's DownloadSettings and ProcessSettings.
		Output: a new engine with empty run state. Nothing is checked, downloaded or parsed yet.
		"""
		self.run_start = time.perf_counter()
		self.size = size
		self.input_path = input_path
		self.download_settings = download_settings
		self.process_settings = process_settings


		self.storage_path = cache.get_storage_path()

		self.documents = {}
		self.processed_doc_ids = []
		self.skipped_doc_ids = set()
		self.raw_data_count = 0
		self.batch_number = 0
		self.source_exhausted = False

		self.summary = Summary()
		self.summary.requested_size = size

		# Set in run(), once the inputs and settings pass validation
		self.deduplicator = None
		self.db_config = None
		self.parse_executor = None

	def run(self) -> IngestResult:
		"""
		Input: none (uses the engine's state).
		Output: an IngestResult with up to size Documents and the run's Summary.
		What it does: validates inputs, loads cached documents, then fetches and processes batches until size is reached or the dataset runs out.
		"""
		# 0. Validate inputs before any work is done.
		# A Hugging Face dataset page URL is turned into the dataset name first.
		self.input_path = dataset_hf.normalize_input_path(self.input_path)
		validate.validate_inputs(self.size, self.input_path, self.storage_path, self.download_settings, self.process_settings)
		self.deduplicator = Deduplicator(threshold=self.process_settings.dedup_threshold)

		# 1. Get dataset config
		self.db_config = dataset_config.get_dataset_config(self.input_path, self.download_settings.hugging_face_split)

		# 2. Load progress
		saved_progress = progress.load_progress(self.storage_path, self.db_config.name)
		self.raw_data_count = saved_progress.raw_data_count
		self.skipped_doc_ids = set(saved_progress.skipped_doc_ids)

		# 3. Check cached processed documents
		size_reached = self.load_cached_documents(saved_progress.processed_doc_ids)
		if size_reached:
			logger.info("Loaded %s already processed document(s). Nothing new to process.", len(self.documents))
			return self.finish()

		# 4. Fetch raw data in batches, then process each batch
		raw_data_fetcher = RawDataFetcher(self.input_path, self.storage_path, self.db_config, self.download_settings)
		row_iterator = raw_data_fetcher.get_iterator(self.raw_data_count)

		self.create_parse_executor()
		try:
			while len(self.documents) < self.size and not self.source_exhausted:

				# 4a. Download/decode as many rows as documents still missing,
				# at most download_settings.max_batch_rows per batch
				self.batch_number += 1
				rows_needed = self.size - len(self.documents)
				logger.info("Batch %s: fetching %s row(s).", self.batch_number, rows_needed)

				download_start = time.perf_counter()
				raw_batch = raw_data_fetcher.fetch_raw_batch(row_iterator, rows_needed)
				self.summary.download_seconds += time.perf_counter() - download_start
				raw_items = raw_batch.raw_items
				self.raw_data_count += raw_batch.rows_read
				self.source_exhausted = raw_batch.source_exhausted

				self.summary.rows += raw_batch.rows_read
				self.summary.downloaded += raw_batch.downloaded
				self.summary.download_failed += raw_batch.rows_read - raw_batch.downloaded
				self.summary.prepare_failed += raw_batch.prepare_failed
				self.summary.unsupported_type += raw_batch.downloaded - raw_batch.prepare_failed - len(raw_items)

				# 4b. Leave out documents that were skipped before
				parse_items = []
				for raw_data in raw_items:
					if raw_data.doc_id in self.skipped_doc_ids:
						continue
					parse_items.append(raw_data)

				# 4c. Parse them in parallel, in parse_workers processes.
				# Results are in the same order as parse_items.
				# Parse time covers 4c and 4d.
				parse_start = time.perf_counter()
				parsed_docs = self.parse_batch(parse_items)

				# 4d. Keep each parsed document unless it failed or is a duplicate
				self.process_parsed_documents(parsed_docs)
				self.summary.parse_seconds += time.perf_counter() - parse_start

				# 4e. Save progress after every batch
				self.update_progress(self.processed_doc_ids)

		finally:
			self.parse_executor.shutdown()

		return self.finish()

	def load_cached_documents(self, cached_doc_ids: list[str]) -> bool:
		"""
		Input: cached_doc_ids - processed document ids from the saved progress.
		Output: True if size documents were loaded (progress is then already saved), else False.
		What it does: loads each cached document into documents and the deduplicator; a missing or damaged one is marked as skipped.
		"""
		cached_index = 0
		while cached_index < len(cached_doc_ids):
			doc_id = cached_doc_ids[cached_index]
			cached_index += 1

			cached_doc = cache.load_processed_document(self.storage_path, self.db_config.name, doc_id)
			# If a processed doc is missing or damaged on disk
			if cached_doc is None:
				logger.warning("Processed document %s is missing or damaged on disk, marking it as skipped.", doc_id)
				self.skipped_doc_ids.add(doc_id)
				self.summary.cache_missing += 1
				self.summary.skipped += 1
				continue

			try:
				self.deduplicator.add(cached_doc)
			except Exception as error:
				logger.warning("Processed document %s could not be added to the duplicate check, marking it as skipped: %s", doc_id, describe_error(error))
				self.skipped_doc_ids.add(doc_id)
				self.summary.cache_missing += 1
				self.summary.skipped += 1
				continue

			self.processed_doc_ids.append(doc_id)
			self.documents[doc_id] = cached_doc
			self.summary.loaded_from_cache += 1

			# if there is dataset_size cached documents already exists
			if len(self.documents) == self.size:
				# Keep the not-yet-checked cached ids in progress too
				unchecked_doc_ids = cached_doc_ids[cached_index:]
				all_processed_doc_ids = self.processed_doc_ids + unchecked_doc_ids
				self.update_progress(all_processed_doc_ids)
				return True

		return False

	def create_parse_executor(self) -> None:
		"""
		Input: none (uses process_settings.parse_workers; None means one per CPU core).
		Output: None. Sets self.parse_executor to a new pool of parse worker processes.
		What it does: starts the pool with "spawn" (see README: forking with Hugging Face threads can deadlock).
		"""
		parse_workers = self.process_settings.parse_workers
		if parse_workers is None:
			parse_workers = os.cpu_count()
			# os.cpu_count() returns None if the core count is unknown
			if parse_workers is None:
				parse_workers = 1

		spawn_context = multiprocessing.get_context("spawn")
		self.parse_executor = concurrent.futures.ProcessPoolExecutor(max_workers=parse_workers, mp_context=spawn_context)

	def parse_batch(self, parse_items: list) -> list:
		"""
		Input: parse_items - the RawData items to parse.
		Output: a (doc_id, Document or None) per item, in parse_items order.
		What it does: parses all items in parallel in self.parse_executor. If a worker process dies, the pool is replaced and the unfinished items are parsed again one at a time, so only the item that kills a worker is skipped (None).
		"""
		futures = []
		for raw_data in parse_items:
			future = self.parse_executor.submit(parser.parse_document, raw_data, self.process_settings.parse_timeout_seconds)
			futures.append(future)

		results = []
		unfinished_indexes = []
		for item_index in range(len(parse_items)):
			raw_data = parse_items[item_index]
			try:
				result = futures[item_index].result()
			except concurrent.futures.process.BrokenProcessPool:
				unfinished_indexes.append(item_index)
				result = (raw_data.doc_id, None)
			except Exception as error:
				logger.warning("Parse failed for document %s: %s", raw_data.doc_id, describe_error(error))
				result = (raw_data.doc_id, None)
			results.append(result)

		if len(unfinished_indexes) == 0:
			return results

		logger.warning("A parse worker process died. Parsing %s unfinished document(s) again, one at a time.", len(unfinished_indexes))
		self.parse_executor.shutdown()
		self.create_parse_executor()

		for item_index in unfinished_indexes:
			raw_data = parse_items[item_index]
			try:
				future = self.parse_executor.submit(parser.parse_document, raw_data, self.process_settings.parse_timeout_seconds)
				result = future.result()
			except concurrent.futures.process.BrokenProcessPool:
				logger.warning("Parse failed for document %s: its parse worker process died", raw_data.doc_id)
				self.parse_executor.shutdown()
				self.create_parse_executor()
				result = (raw_data.doc_id, None)
			except Exception as error:
				logger.warning("Parse failed for document %s: %s", raw_data.doc_id, describe_error(error))
				result = (raw_data.doc_id, None)
			results[item_index] = result

		return results

	def process_parsed_documents(self, parsed_docs: list) -> None:
		"""
		Input: parsed_docs - (doc_id, Document or None) pairs from parse_batch.
		Output: None. Adds kept documents to documents and processed_doc_ids, and skipped ones to skipped_doc_ids.
		What it does: skips failed, empty and duplicate documents and caches the rest. Raises OSError if the storage folder can't be written.
		"""
		for doc_id, doc in parsed_docs:

			# Skipped
			if doc is None:
				logger.warning("Skipping document %s: parse failed", doc_id)
				self.skipped_doc_ids.add(doc_id)
				self.summary.skipped += 1
				self.summary.parse_error += 1
				continue

			try:
				# No text, e.g. a scanned PDF
				if doc.text.strip() == "":
					logger.warning("Skipping document %s: no text", doc_id)
					self.skipped_doc_ids.add(doc_id)
					self.summary.skipped += 1
					self.summary.no_text += 1
					continue

				# Duplicate
				if not self.deduplicator.add_if_new(doc):
					self.summary.duplicate += 1
					continue

				cache.save_processed_document(self.storage_path, self.db_config.name, doc)
			except OSError:
				# Writing to the storage folder failed: stop the run
				raise
			except Exception as error:
				logger.warning("Skipping document %s: duplicate check or saving failed: %s", doc_id, describe_error(error))
				self.skipped_doc_ids.add(doc_id)
				self.summary.skipped += 1
				self.summary.keep_error += 1
				continue

			self.processed_doc_ids.append(doc_id)
			self.documents[doc_id] = doc
			self.summary.processed += 1

	def update_progress(self, processed_doc_ids: list[str]) -> None:
		"""
		Input: processed_doc_ids - the processed ids to save (can include not-yet-checked cached ids).
		Output: None.
		What it does: saves the run's progress (rows read, processed and skipped ids) to the dataset's progress file.
		"""
		progress.update_progress(
			self.storage_path,
			self.db_config.name,
			self.raw_data_count,
			processed_doc_ids,
			list(self.skipped_doc_ids),
		)

	def finish(self) -> IngestResult:
		"""
		Input: none (uses the engine's state).
		Output: an IngestResult with the collected Documents and the run's Summary.
		What it does: fills in the final summary numbers and logs the run summary.
		"""
		self.summary.returned_size = len(self.documents)
		self.summary.source_exhausted = self.source_exhausted
		self.summary.batches = self.batch_number
		self.summary.total_seconds = time.perf_counter() - self.run_start
		print_run_summary(self.summary)

		document_list = list(self.documents.values())
		ingest_result = IngestResult(documents=document_list, summary=self.summary)
		return ingest_result


# --------------- CLI entry
def ingest_documents(size: int, input_path: str, *, download_settings: DownloadSettings | None = None, process_settings: ProcessSettings | None = None) -> IngestResult:
	"""
	Input: size - max documents to return; input_path - local file/folder or Hugging Face dataset; download_settings/process_settings - optional (None: all defaults).
	Output: an IngestResult: .documents (up to size Documents) and .summary (the run's Summary).
	What it does: loads cached documents first, then downloads, parses and dedups new ones in batches, saving progress after each batch so a later run can resume.
	"""
	# None, not DownloadSettings(), as the default: a default object would be shared by every call
	if download_settings is None:
		download_settings = DownloadSettings()
	if process_settings is None:
		process_settings = ProcessSettings()

	ingest_engine = IngestEngine(size, input_path, download_settings, process_settings)
	ingest_result = ingest_engine.run()
	return ingest_result
