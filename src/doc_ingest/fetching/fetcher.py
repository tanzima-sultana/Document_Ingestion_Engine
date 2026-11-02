"""
fetching/fetcher.py

Defines RawDocument, FetchSummary and BaseFetcher. Each source subclasses
BaseFetcher and says how its rows are read; BaseFetcher goes through them.
"""

import abc
import dataclasses
import hashlib
import os
from typing import Iterator

from doc_ingest.settings import FetchSettings


@dataclasses.dataclass
class RawDocument:
	"""
	One decoded document on disk, ready to be parsed.

	id: id of the document, from BaseFetcher.make_doc_id.
	type: the document type the caller asked for (e.g. "pdf").
	raw_path: path of its file on disk: the original file, or the copy saved in raw/.
	source: where the document came from (e.g. "data/a.pdf" or "data/a.jsonl#12").
	"""
	id: str
	type: str
	raw_path: str
	source: str


@dataclasses.dataclass
class FetchSummary:
	"""
	What fetching did so far.

	total_fetched: source rows read, including those skipped.
	fetch_success: rows whose bytes were read or decoded.
	fetch_failed: rows whose bytes could not be read or decoded.
	wrong_doc_type: rows that are not of the requested document type.
	"""
	total_fetched: int = 0
	fetch_success: int = 0
	fetch_failed: int = 0
	wrong_doc_type: int = 0


class BaseFetcher(abc.ABC):
	"""
	Reads a dataset's rows one at a time. Each source subclasses it and says
	which rows it has (get_iterator) and how one row is fetched (fetch_row).
	"""

	def __init__(self, storage_path: str, fetch_settings: FetchSettings):
		"""
		Input: storage_path - storage folder that raw/ is saved under; fetch_settings - the type to keep.
		Output: none.
		"""
		self.storage_path = storage_path
		self.fetch_settings = fetch_settings
		self.summary = FetchSummary()

	@abc.abstractmethod
	def get_iterator(self) -> Iterator:
		"""
		Input: none.
		Output: an iterator of rows, in a fixed source order, starting at the first row.
		"""
		raise NotImplementedError

	@abc.abstractmethod
	def fetch_row(self, row, row_number: int) -> RawDocument | None:
		"""
		Input: row - one row from get_iterator; row_number - its position in the dataset, from 0.
		Output: its RawDocument, or None if it is skipped; the reason is added to self.summary.
		"""
		raise NotImplementedError

	def make_doc_id(self, raw_bytes: bytes) -> str:
		"""
		Input: raw_bytes - one document's raw bytes.
		Output: the document id: the first 16 hex characters of the bytes' SHA-256 hash.
		What it does: hashes the bytes, so the same document always gets the same id.
		"""
		return hashlib.sha256(raw_bytes).hexdigest()[:16]

	def save_raw_file(self, doc_id: str, raw_bytes: bytes) -> str:
		"""
		Input: doc_id and raw_bytes - a document's id and bytes.
		Output: the path of the saved file.
		What it does: writes the bytes to "<storage_path>/raw/<doc_id>.<document_type>",
			for a document that is not in a file of its own yet.
		"""
		raw_folder_path = os.path.join(self.storage_path, "raw")
		os.makedirs(raw_folder_path, exist_ok=True)

		raw_file_path = os.path.join(raw_folder_path, f"{doc_id}.{self.fetch_settings.document_type}")
		with open(raw_file_path, "wb") as raw_file:
			raw_file.write(raw_bytes)
		return raw_file_path
	
	def fetch_documents(self) -> Iterator[RawDocument]:
		"""
		Input: none.
		Output: an iterator of RawDocuments, one at a time, without the skipped rows.
		"""
		row_number = 0
		for row in self.get_iterator():
			self.summary.total_fetched += 1
			raw_document = self.fetch_row(row, row_number)
			row_number = row_number + 1
			if raw_document is not None:
				yield raw_document
