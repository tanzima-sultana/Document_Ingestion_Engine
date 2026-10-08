"""
settings.py

Optional settings for an ingest run, grouped by pipeline stage. Every field
has a default, so a caller only sets what it wants to change.
"""

import dataclasses

# Default number of documents downloaded/decoded at the same time
DEFAULT_DOWNLOAD_WORKERS = 64

# Default largest number of rows read in one batch, so a large request does
# not hold every document's bytes in memory at once
DEFAULT_MAX_BATCH_ROWS = 256

# Default split read from a Hugging Face dataset
DEFAULT_HUGGING_FACE_SPLIT = "train"

# Default longest time one document may take to parse before it is skipped
DEFAULT_PARSE_TIMEOUT_SECONDS = 120

# Default Jaccard similarity at or above which two documents are near-duplicates
DEFAULT_DEDUP_THRESHOLD = 0.90

# PDF parsing libraries that can be chosen, and the default one.
# pypdfium2 is an optional install (pip install doc-ingest[pdfium]).
PDF_PARSER_NAMES = ["pypdf", "pypdfium2"]
DEFAULT_PDF_PARSER = "pypdf"


@dataclasses.dataclass
class DownloadSettings:
	"""
	How the source is read: download_workers - rows downloaded/decoded at the same time;
	max_batch_rows - most rows read per batch; hugging_face_split - split read from a Hugging Face dataset.
	"""
	download_workers: int = DEFAULT_DOWNLOAD_WORKERS
	max_batch_rows: int = DEFAULT_MAX_BATCH_ROWS
	hugging_face_split: str = DEFAULT_HUGGING_FACE_SPLIT


@dataclasses.dataclass
class ProcessSettings:
	"""
	How raw files become kept documents: parse_workers - parse processes (None: one per CPU core);
	parse_timeout_seconds - time limit per document; dedup_threshold - near-duplicate similarity.
	"""
	parse_workers: int | None = None
	parse_timeout_seconds: int = DEFAULT_PARSE_TIMEOUT_SECONDS
	dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD


@dataclasses.dataclass
class ParserSettings:
	"""
	Which library parses each document type: pdf_parser - "pypdf" (default) or "pypdfium2".
	Every choice produces the same Document format; only the extracted text can differ.
	"""
	pdf_parser: str = DEFAULT_PDF_PARSER
