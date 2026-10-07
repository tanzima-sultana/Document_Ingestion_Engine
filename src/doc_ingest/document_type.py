"""
document_type.py

Works out a document's type (the parser registry key, e.g. "pdf") from its
file extension or from its leading bytes.
"""

import io
import os
import zipfile


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


def get_extension_of_file(file_path) -> str:
	"""
	Input: path to a single file.
	Output: lowercase extension without the dot, or "" if there is none.
	What it does: splits the extension off the file name and normalizes it.
	"""
	_name, extension_with_dot = os.path.splitext(file_path)
	return extension_with_dot.lstrip(".").lower()


def get_document_type_from_bytes(content_bytes) -> str:
	"""
	Input: raw bytes of one document.
	Output: the guessed document type ("pdf", "docx", "pptx", "xlsx",
	"html" or "txt").
	What it does: looks at the leading bytes ("magic bytes"). PDF files start
	with "%PDF". DOCX/PPTX/XLSX are zip files, told apart by the folders
	inside the zip. HTML is detected by an <html> or <!doctype html> tag near
	the start. Anything else is treated as plain text.
	"""
	if content_bytes.startswith(b"%PDF"):
		return "pdf"

	if content_bytes.startswith(b"PK"):
		office_type = get_office_document_type_from_zip(content_bytes)
		if office_type is not None:
			return office_type

	leading_text = content_bytes[:1024].decode("utf-8", errors="ignore").lower()
	if "<html" in leading_text:
		return "html"
	if "<!doctype html" in leading_text:
		return "html"

	return "txt"


def get_office_document_type_from_zip(content_bytes) -> str | None:
	"""
	Input: raw bytes of a zip file.
	Output: "docx", "pptx", "xlsx", or None if it is not an Office document.
	What it does: opens the bytes as a zip archive and checks for the folder
	each Office format uses ("word/", "ppt/", "xl/"). Returns None if the
	bytes cannot be opened as a zip.
	"""
	try:
		zip_archive = zipfile.ZipFile(io.BytesIO(content_bytes))
	except zipfile.BadZipFile:
		return None

	with zip_archive:
		for member_name in zip_archive.namelist():
			if member_name.startswith("word/"):
				return "docx"
			if member_name.startswith("ppt/"):
				return "pptx"
			if member_name.startswith("xl/"):
				return "xlsx"

	return None
