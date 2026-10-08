"""
doc_ingest package.
Exposes the public API. The command line entry point is __main__.py (python -m doc_ingest).
"""

from doc_ingest.error import IngestError
from doc_ingest.ingest import IngestResult
from doc_ingest.ingest import ingest_documents
from doc_ingest.schema import Document
from doc_ingest.settings import DownloadSettings
from doc_ingest.settings import ProcessSettings
from doc_ingest.settings import ParserSettings

__all__ = [
	"ingest_documents",
	"IngestResult",
	"IngestError",
	"Document",
	"DownloadSettings",
	"ProcessSettings",
	"ParserSettings",
]
