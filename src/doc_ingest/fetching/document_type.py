"""
fetching/document_type.py

Checks whether a document is of the type the caller asked for (the parser
registry key, e.g. "pdf"), from its file extension or its leading bytes.
"""

import os


# Maps a lowercase file extension (without the dot) to the document type
# used by the parser registry.
EXTENSION_TO_DOCUMENT_TYPE = {
	"pdf": "pdf",
	"docx": "docx",
	"pptx": "pptx",
	"xlsx": "xlsx",
	"csv": "csv",
	"html": "html",
	"htm": "html",
	"md": "md",
	"markdown": "md",
	"txt": "txt",
	"log": "txt",
	"py": "txt",
	"js": "txt",
	"java": "txt",
	"c": "txt",
	"cpp": "txt",
	"h": "txt",
	"sh": "txt",
}


# How far into a document the "%PDF" header is looked for.
PDF_HEADER_SEARCH_BYTES = 1024


def get_extension_of_file(file_path) -> str:
	"""
	Input: path to a single file.
	Output: lowercase extension without the dot, or "" if there is none.
	What it does: splits the extension off the file name and normalizes it.
	"""
	_name, extension_with_dot = os.path.splitext(file_path)
	return extension_with_dot.lstrip(".").lower()


def file_matches_document_type(file_path, document_type: str) -> bool:
	"""
	Input: file_path - path of one file; document_type - the type the caller asked for (e.g. "pdf").
	Output: True if the file's extension belongs to document_type, otherwise False.
	"""
	extension = get_extension_of_file(file_path)
	if extension not in EXTENSION_TO_DOCUMENT_TYPE:
		return False

	return EXTENSION_TO_DOCUMENT_TYPE[extension] == document_type


def bytes_match_document_type(content_bytes, document_type: str) -> bool:
	"""
	Input: content_bytes - raw bytes of one document; document_type - the type the caller asked for.
	Output: True if the bytes look like document_type, otherwise False.
	What it does: for "pdf", looks for "%PDF" in the first PDF_HEADER_SEARCH_BYTES bytes, because
	PDF readers accept some bytes before the header. Raises ValueError for any other type.
	"""
	if document_type == "pdf":
		return b"%PDF" in content_bytes[:PDF_HEADER_SEARCH_BYTES]

	raise ValueError(f"Cannot check the bytes of document type '{document_type}'.")
