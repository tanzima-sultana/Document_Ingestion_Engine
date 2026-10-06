from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
	"""
	The supported document types. There is one value per parser in parsers/.
	Each value is a plain string, so it is saved in the output JSON as text,
	for example "pdf".
	"""
	PDF = "pdf"
	SCANNED_PDF = "scanned_pdf"
	DOCX = "docx"
	PPTX = "pptx"
	XLSX = "xlsx"
	CSV = "csv"
	HTML = "html"
	MD = "md"
	TXT = "txt"


class Metadata(BaseModel):
	source: str = Field(..., description="Original input file path or URL")
	file_size_bytes: int = Field(..., ge=0, description="Size of the raw input file")
	content_hash: str = Field(..., description="SHA-256 hash of raw bytes for exact deduplication")
	minhash_signature: list[int] | None = Field(None, description="MinHash/LSH signature")
	author: str | None = None
	title: str | None = None
	creation_date: str | None = None

class Document(BaseModel):
	id: str = Field(..., description="Unique identifier derived from content hash")
	type: DocumentType = Field(..., description="Detected document type (e.g., pdf, docx)")
	text: str = Field(..., description="Cleaned full text content of the document")
	metadata: Metadata = Field(..., description="Document-level metadata")
