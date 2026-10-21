"""
error.py

The library's exception and error helpers, shared across modules.
"""

from doc_ingest.processing.text_cleanup import fix_broken_characters


class IngestError(ValueError):
	"""
	A problem the user can fix (bad input or settings).
	The CLI prints only its message, without a traceback.
	"""


def describe_error(error: Exception) -> str:
	"""
	Input: an error. Output: "<ErrorType>: <message>" as printable text.
	Broken characters in the message are fixed, so printing it cannot fail.
	"""
	error_text = f"{type(error).__name__}: {error}"
	return fix_broken_characters(error_text)
