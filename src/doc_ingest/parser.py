"""
parser.py

Defines the Parser interface every format implementation must follow,
plus the registry mapping document type -> implementation, the lookup
function, and parse_document, which ingest.py runs in parse worker
processes.

Concrete parsers (e.g. PDFParser) subclass Parser, so they import this
module. Importing them back at the top of this module would create a
circular import, since this module would then depend on them too — so
the registry is built lazily inside get_parser instead, once Parser has
already finished being defined.
"""

import abc
import hashlib
import time 

from doc_ingest.schema import Document
from doc_ingest.raw_data import RawData

class Parser(abc.ABC):
	@abc.abstractmethod
	def parse(self, raw_data: RawData) -> Document:
		"""
		Input: raw_data - the document to parse: its doc_id (already
			computed from the raw bytes by RawDataFetcher.make_doc_id),
			its doc_type, raw_path, the path of its saved raw file, and
			source_path, where it came from.
		Output: a fully-populated Document.
		What it does: reads the raw file and builds a Document from it.
			Implementations must set Document.id to raw_data.doc_id
			directly rather than recomputing it.
		"""
		raise NotImplementedError


def get_parser(doc_type: str) -> type[Parser]:
	"""
	Input: doc_type - a document type (e.g. "pdf").
	Output: the Parser class registered for that type.
	What it does: looks the type up in the parser registry. Raises
		ValueError if no parser is registered for it.
	"""
	# imported here, not at module level, to avoid the circular import
	# described above
	from doc_ingest.parsers.pdf import PDFParser

	parser_registry: dict[str, type[Parser]] = {
		"pdf": PDFParser,
	}

	if doc_type not in parser_registry:
		raise ValueError(
			f"Unknown doc_type '{doc_type}'. Registered types: {list(parser_registry.keys())}"
		)
	return parser_registry[doc_type]

def parse_document(raw_data: RawData) -> tuple:
	"""
	Input: raw_data - the document to parse (doc_id, doc_type and
		raw_path of its saved raw file).
	Output: (doc_id, document). On failure, document is None.
	What it does: picks the parser for raw_data.doc_type and parses the
		raw file, in a parse worker process. Parse errors are not
		raised; the document is returned as None instead.
	"""
	
	try:
		parser_cls = get_parser(raw_data.doc_type)
		parser = parser_cls()
		document = parser.parse(raw_data)
	except Exception as error:
		return raw_data.doc_id, None

	return raw_data.doc_id, document
