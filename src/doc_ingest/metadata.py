"""
metadata.py

Builds the generic part of a document's Metadata (source, size, content
hash) from its raw bytes, for every document type. Title, author and
creation date are stored differently by each format, so each parser
fills them in itself, using the helpers below to tidy the values.
"""

import datetime
import hashlib

from doc_ingest.schema import Metadata
from doc_ingest.raw_data import RawData
from doc_ingest.text_cleanup import fix_broken_characters


def extract_metadata(raw_data: RawData, raw_bytes: bytes) -> Metadata:
	"""
	Input: RawData and raw bytes of a document. Output: its Metadata.
	Sets source, size and SHA-256 content hash; title, author and creation
	date are left as None for the parser to fill in.
	"""

	source = raw_data.source_path
	file_size_bytes = len(raw_bytes)
	content_hash = hashlib.sha256(raw_bytes).hexdigest()

	metadata = Metadata(
		source=source,
		file_size_bytes=file_size_bytes,
		content_hash=content_hash,
		minhash_signature = None,
		author = None,
		title = None,
		creation_date = None
	)
	return metadata


def clean_property_text(value) -> str | None:
	"""
	Input: value - a property value as stored in the document, or None.
	Output: the value as stripped text, or None if it is missing or blank.
	What it does: turns the value into a string, fixes broken characters
		(fix_broken_characters), strips whitespace and null characters from
		its ends, and treats an empty result as missing.
	"""
	if value is None:
		return None

	text = str(value)
	text = fix_broken_characters(text)
	text = text.strip()
	text = text.strip("\x00")
	text = text.strip()
	if text == "":
		return None

	return text


def format_creation_date(creation_datetime: datetime.datetime | None) -> str | None:
	"""
	Input: creation_datetime - the creation date as a datetime, or None.
	Output: the date as an ISO 8601 string, or None.
	What it does: formats the datetime with isoformat, which keeps the
		time zone if the document stored one.
	"""
	if creation_datetime is None:
		return None

	return creation_datetime.isoformat()
