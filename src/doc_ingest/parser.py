"""
parser.py

Defines the Parser interface every format implementation must follow,
including the content hash every parser computes, plus the registry
mapping format name -> implementation and the lookup function used by
ingest.py.

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


class Parser(abc.ABC):
	@abc.abstractmethod
	def parse(self, doc_id: str, source_path: str) -> Document:
		"""
		doc_id: this document's identifier, already computed from the raw
			 bytes by RawData.make_doc_id. Implementations must set
			 Document.id to this value directly rather than recomputing it.
		source_path: the original raw data path of the document.

		Returns a fully-populated Document.
		"""
		raise NotImplementedError


def get_parser(doc_type: str) -> type[Parser]:
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

def parse_document(doc_type: str, doc_id: str, source_path: str) -> tuple:
	"""
	doc_type: document type (e.g. "docx").
	doc_id: document identifier.
	source_path: path of the raw file.

	Reads and parses the raw file in a parse worker process. Parse
	errors are not raised; the document is returned as None instead.

	Returns (doc_id, document). On failure, document is None.
	"""
	
	try:
		parser_cls = get_parser(doc_type)
		parser = parser_cls()
		document = parser.parse(doc_id, source_path)
	except Exception as error:
		return doc_id, None

	return doc_id, document
