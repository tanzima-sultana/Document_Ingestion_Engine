"""
pdf.py

Implements Parser for PDF documents. Opens the document's raw bytes
with pypdf, gets the cleaned text (text_cleanup.py) and the metadata
(metadata.py), and builds a Document.
"""

import datetime
import io

import pypdf

from doc_ingest.parser import Parser
from doc_ingest.schema import Document
from doc_ingest.schema import DocumentType
from doc_ingest.raw_data import RawData
from doc_ingest.metadata import extract_metadata
from doc_ingest.text_cleanup import extract_clean_text

class PDFParser(Parser):
	def parse(self, raw_data: RawData) -> Document:
		"""
		Input: raw_data - the PDF to parse: its doc_id (set directly on
			the returned Document, not recomputed), its doc_type, and
			raw_path, the path of its saved raw file, and source_path,
			where it came from.
		Output: a fully-populated Document.
		What it does: reads the PDF's bytes from raw_path, opens them
			with pypdf, extracts and cleans the text, extracts the
			metadata (title, author, content hash, source, etc.), and
			builds the Document.
		"""
		raw_path = raw_data.raw_path
		with open(raw_path, "rb") as f:
			raw_bytes = f.read()

		reader = pypdf.PdfReader(io.BytesIO(raw_bytes))

		# Document id
		doc_id = raw_data.doc_id

		# Docuemnt Type
		doc_type = DocumentType(raw_data.doc_type) 

		# Text cleanup
		doc_text = extract_clean_text(reader)

		# Meata
		doc_metadata = extract_metadata(raw_data, raw_bytes)

		return Document(
			id=doc_id,
			type = doc_type,
			text = doc_text,
			metadata = doc_metadata
		)
