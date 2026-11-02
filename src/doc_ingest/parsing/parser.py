"""
parsing/parser.py

Defines ParsedDocument, ParseSummary and BaseParser. Each document type
subclasses BaseParser and says how one file is read; BaseParser picks the
subclass for the document type and handles failures and the time limit.

Concrete parsers (e.g. PdfParser) subclass BaseParser, so they import this
module. Importing them back at the top of this module would create a
circular import, so the registry is built lazily inside get_parser_class instead.
"""

import dataclasses
import logging
import signal
import threading

from doc_ingest.error import describe_error
from doc_ingest.fetching.fetcher import RawDocument
from doc_ingest.settings import ParseSettings

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ParsedDocument:
	"""
	One parsed document, ready to be processed. The processor turns it into a Document.

	id: id of the document.
	type: the document type (e.g. "pdf").
	source: where the document came from.
	title: its title as stored in the document, or None.
	raw_texts: the raw, uncleaned text of each page, in page order.
	"""
	id: str
	type: str
	source: str
	title: str | None
	raw_texts: list[str]


@dataclasses.dataclass
class ParseSummary:
	"""
	What parsing did so far.

	total_parsed: documents sent to be parsed.
	parse_success: documents parsed.
	parse_failed: documents that failed to parse.
	"""
	total_parsed: int = 0
	parse_success: int = 0
	parse_failed: int = 0


class BaseParser:
	"""
	Parses documents one at a time. Each document type subclasses it and says how one file is parsed (parse).
	"""

	def __init__(self, parse_settings: ParseSettings):
		"""
		Input: parse_settings - the document type and the time limit per document.
		Output: none.
		"""
		self.parse_settings = parse_settings
		self.summary = ParseSummary()

	@classmethod
	def parse(cls, raw_document: RawDocument) -> ParsedDocument:
		"""
		Input: raw_document - the document to parse.
		Output: a ParsedDocument with raw_document.id as its id. Raises an error if it cannot be parsed.
		"""
		raise NotImplementedError

	def parse_document(self, raw_document: RawDocument) -> ParsedDocument | None:
		"""
		Input: raw_document - the document to parse.
		Output: a ParsedDocument, or None if parsing failed.
		What it does: picks the parser for the document type and parses the document. Errors, and parsing longer
			than parse_settings.timeout_seconds, are not raised; the reason is logged instead.
		"""
		self.summary.total_parsed += 1

		timeout_is_set = start_parse_timeout(self.parse_settings.timeout_seconds)
		try:
			parser_class = get_parser_class(self.parse_settings.document_type)
			parsed_document = parser_class.parse(raw_document)
		except Exception as error:
			logger.warning("Parse failed for document %s: %s", raw_document.id, describe_error(error))
			self.summary.parse_failed += 1
			return None
		finally:
			if timeout_is_set:
				signal.alarm(0)

		self.summary.parse_success += 1
		return parsed_document


def get_parser_class(document_type: str) -> type[BaseParser]:
	"""
	Input: document_type - a document type (e.g. "pdf").
	Output: the BaseParser subclass registered for that type.
	What it does: looks the type up in the parser registry. Raises ValueError if no parser is registered for the type.
	"""
	# imported here, not at module level, to avoid the circular import
	# described above
	from doc_ingest.parsing.pdf import PdfParser

	# document type -> BaseParser subclass
	parser_registry: dict[str, type[BaseParser]] = {
		"pdf": PdfParser,
	}

	if document_type not in parser_registry:
		raise ValueError(
			f"Unknown document type '{document_type}'. Registered types: {list(parser_registry.keys())}"
		)

	return parser_registry[document_type]


class ParseTimeoutError(Exception):
	"""Raised when one document takes longer than its parse time limit."""


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
