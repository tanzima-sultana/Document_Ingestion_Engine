"""
settings.py

Settings for an ingest run. Settings is what the caller sets; every field has a
default. FetchSettings, ParseSettings and ProcessSettings are what each phase uses.
"""

import dataclasses

# Default longest time one document may take to parse before it is skipped
DEFAULT_PARSE_TIMEOUT_SECONDS = 120

# Default Jaccard similarity at or above which two documents are near-duplicates
DEFAULT_DEDUP_THRESHOLD = 0.90


@dataclasses.dataclass
class Settings:
	"""
	What the caller sets: dedup_threshold - near-duplicate similarity;
	timeout_seconds - parse time limit per document. The code splits it into the classes below.
	"""
	dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD
	timeout_seconds: int = DEFAULT_PARSE_TIMEOUT_SECONDS


@dataclasses.dataclass
class FetchSettings:
	"""
	Internal. How a source is read: document_type - the type to keep.
	"""
	document_type: str


@dataclasses.dataclass
class ParseSettings:
	"""
	Internal. How documents are parsed: document_type - decides which parser is used;
	timeout_seconds - time limit per document.
	"""
	document_type: str
	timeout_seconds: int = DEFAULT_PARSE_TIMEOUT_SECONDS


@dataclasses.dataclass
class ProcessSettings:
	"""
	Internal. How parsed documents are processed: dedup_threshold - near-duplicate similarity.
	"""
	dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD
