"""
parser.py

Defines the Parser interface every format implementation must follow,
plus the registry mapping document type -> implementation, the lookup
function, and parse_document, which ingest.py runs in parse worker
processes.

Concrete parsers (e.g. PyPdfParser) subclass Parser, so they import this
module. Importing them back at the top of this module would create a
circular import, since this module would then depend on them too — so
the registry is built lazily inside get_parser instead, once Parser has
already finished being defined.
"""

import logging
import abc
import hashlib
import signal
import threading
import time 

from doc_ingest.schema import Document
from doc_ingest.raw_data import RawData
from doc_ingest.error import describe_error
from doc_ingest.settings import ParserSettings

logger = logging.getLogger(__name__)


class ParseTimeoutError(Exception):
	"""Raised when one document takes longer than its parse time limit."""

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


def get_parser(doc_type: str, parser_settings: ParserSettings) -> type[Parser]:
	"""
	Input: doc_type - a document type (e.g. "pdf"); parser_settings - which library to use per type.
	Output: the Parser class registered for that type and chosen library.
	What it does: looks the type up in the parser registry, then picks the
		library chosen in parser_settings. Raises ValueError if no parser
		is registered for the type or the library.
	"""
	# imported here, not at module level, to avoid the circular import
	# described above
	from doc_ingest.parsers.pdf import PyPdfParser
	from doc_ingest.parsers.pdf import PyPdfium2Parser

	# document type -> library name -> Parser class
	parser_registry: dict[str, dict[str, type[Parser]]] = {
		"pdf": {
			"pypdf": PyPdfParser,
			"pypdfium2": PyPdfium2Parser,
		},
	}

	# document type -> the library chosen for it
	chosen_parser_names = {
		"pdf": parser_settings.pdf_parser,
	}

	if doc_type not in parser_registry:
		raise ValueError(
			f"Unknown doc_type '{doc_type}'. Registered types: {list(parser_registry.keys())}"
		)

	parsers_for_type = parser_registry[doc_type]
	chosen_parser_name = chosen_parser_names[doc_type]
	if chosen_parser_name not in parsers_for_type:
		raise ValueError(
			f"Unknown {doc_type} parser '{chosen_parser_name}'. Registered parsers: {list(parsers_for_type.keys())}"
		)
	return parsers_for_type[chosen_parser_name]

def parse_document(raw_data: RawData, parser_settings: ParserSettings | None = None) -> tuple:
	"""
	Input: raw_data - the document to parse (doc_id, doc_type and
		raw_path of its saved raw file); parser_settings - which library
		to use per type and the time limit per document (None: the defaults).
	Output: (doc_id, document). On failure, document is None.
	What it does: picks the parser for raw_data.doc_type (and the chosen library) and parses the
		raw file, in a parse worker process. Parse errors, and parsing
		longer than parser_settings.parse_timeout_seconds, are not raised; the reason is
		logged and the document is returned as None instead.
	"""
	if parser_settings is None:
		parser_settings = ParserSettings()

	timeout_is_set = start_parse_timeout(parser_settings.parse_timeout_seconds)
	try:
		parser_cls = get_parser(raw_data.doc_type, parser_settings)
		parser = parser_cls()
		document = parser.parse(raw_data)
	except Exception as error:
		logger.warning("Parse failed for document %s: %s", raw_data.doc_id, describe_error(error))
		return raw_data.doc_id, None
	finally:
		if timeout_is_set:
			signal.alarm(0)

	return raw_data.doc_id, document


def start_parse_timeout(parse_timeout_seconds: int) -> bool:
	"""
	Input: parse_timeout_seconds - the time limit. Output: True if a time limit was set, else False.
	Makes ParseTimeoutError be raised after parse_timeout_seconds. Only
	possible on systems with SIGALRM (not Windows) and in the main thread.
	"""
	if not hasattr(signal, "SIGALRM"):
		return False
	if threading.current_thread() is not threading.main_thread():
		return False

	def raise_parse_timeout(signal_number, stack_frame):
		"""
		Input: the signal number and current stack frame (given by Python).
		Output: none. Raises ParseTimeoutError to stop the parse in progress.
		"""
		raise ParseTimeoutError(f"parsing took longer than {parse_timeout_seconds} seconds")

	signal.signal(signal.SIGALRM, raise_parse_timeout)
	signal.alarm(parse_timeout_seconds)
	return True
