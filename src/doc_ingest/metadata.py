"""
metadata.py

Builds a document's Metadata. The size and content hash come from the
raw bytes for every document type. Title, author and creation date are
read from the document's own properties, which each format stores
differently, so they are read per document type.
"""

import datetime
import hashlib
import io

import pypdf

from doc_ingest.schema import DocumentType
from doc_ingest.schema import Metadata
from doc_ingest.raw_data import RawData


def extract_metadata(raw_data: RawData, raw_bytes: bytes) -> Metadata:
	"""
	Input: RawData and raw bytes of a document. Output: its Metadata.
	Sets source, size and SHA-256 content hash; for PDFs also title,
	author and creation date.
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
	if raw_data.doc_type == DocumentType.PDF:
		fill_pdf_properties(metadata, raw_bytes)

	return metadata


def fill_pdf_properties(metadata: Metadata, raw_bytes: bytes) -> None:
	"""
	Input: metadata - the Metadata to fill in; raw_bytes - the PDF's raw
		bytes.
	Output: none. Sets metadata.title, metadata.author and
		metadata.creation_date.
	What it does: opens the PDF with pypdf and reads its document
		information. A PDF without document information leaves all three
		as None. A creation date that pypdf cannot parse leaves only the
		date as None.
	"""
	reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
	pdf_information = reader.metadata
	if pdf_information is None:
		return

	metadata.author = clean_property_text(pdf_information.author)
	metadata.title = clean_property_text(pdf_information.title)
	
	try:
		creation_datetime = pdf_information.creation_date
	except ValueError as date_error:
		print(f"Could not parse PDF creation date: {date_error}")
		creation_datetime = None

	metadata.creation_date = format_creation_date(creation_datetime)


def clean_property_text(value) -> str | None:
	"""
	Input: value - a property value as stored in the document, or None.
	Output: the value as stripped text, or None if it is missing or blank.
	What it does: turns the value into a string, strips whitespace and
		null characters from its ends, and treats an empty result as
		missing.
	"""
	if value is None:
		return None

	text = str(value)
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
