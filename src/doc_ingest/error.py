"""
error.py

The library's exception and error helpers, shared across modules.
"""


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


def fix_broken_characters(text: str) -> str:
	"""
	Input: text. Output: the same text, safe to save as UTF-8.
	Text extractors can return a character split into two halves (a UTF-16 surrogate pair, e.g. math
	letters); pairs are joined back, lone halves become "\ufffd".
	"""
	text_bytes = text.encode("utf-16-le", "surrogatepass")
	fixed_text = text_bytes.decode("utf-16-le", "replace")
	return fixed_text
