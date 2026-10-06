"""
helpers.py

Shared helpers for the tests: build small PDFs in memory and write files.
"""

import io
import os

import pypdf


def make_pdf(pages: list[list[str]], info: dict) -> bytes:
	"""
	Input: lines of text for each page, and PDF info (e.g. {"Title": "x"}).
	Output: the bytes of a valid PDF with that text and info.
	"""
	objects = []
	objects.append("<< /Type /Catalog /Pages 2 0 R >>")

	kids = ""
	for page_index in range(len(pages)):
		kids = kids + f"{4 + 2 * page_index} 0 R "
	objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
	objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

	for page_index in range(len(pages)):
		content = "BT /F1 11 Tf 14 TL 50 750 Td "
		for line in pages[page_index]:
			content = content + f"({line}) Tj T* "
		content = content + "ET"
		content_number = 5 + 2 * page_index
		objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_number} 0 R >>")
		objects.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")

	info_entries = ""
	for key, value in info.items():
		info_entries = info_entries + f"/{key} ({value}) "
	objects.append(f"<< {info_entries}>>")
	info_number = len(objects)

	pdf_bytes = b"%PDF-1.4\n"
	offsets = []
	for object_index in range(len(objects)):
		offsets.append(len(pdf_bytes))
		object_text = f"{object_index + 1} 0 obj\n{objects[object_index]}\nendobj\n"
		pdf_bytes = pdf_bytes + object_text.encode("latin-1")

	xref_offset = len(pdf_bytes)
	xref_text = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
	for offset in offsets:
		xref_text = xref_text + f"{offset:010d} 00000 n \n"
	xref_text = xref_text + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_number} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
	pdf_bytes = pdf_bytes + xref_text.encode("latin-1")
	return pdf_bytes


def make_report_pdf(topic: str, page_count: int) -> bytes:
	"""
	Input: a topic word and a page count. Output: PDF bytes.
	Each page has a running header, 8 body lines and a "Page n of m" footer.
	"""
	pages = []
	for page_number in range(1, page_count + 1):
		lines = []
		lines.append(f"Quarterly Report on {topic}")
		for line_number in range(8):
			lines.append(f"Line {line_number} of page {page_number} talks about {topic} in detail.")
		lines.append(f"Page {page_number} of {page_count}")
		pages.append(lines)
	return make_pdf(pages, {"Title": f"{topic} report", "Author": "Tester"})


def make_encrypted_pdf() -> bytes:
	"""
	Input: none. Output: bytes of an encrypted one-page PDF.
	"""
	writer = pypdf.PdfWriter()
	writer.add_blank_page(100, 100)
	writer.encrypt(user_password="", owner_password="owner", algorithm="RC4-128")
	output = io.BytesIO()
	writer.write(output)
	return output.getvalue()


def write_file(folder: str, file_name: str, content: bytes) -> str:
	"""
	Input: folder, file name and bytes. Output: path of the written file.
	"""
	os.makedirs(folder, exist_ok=True)
	file_path = os.path.join(folder, file_name)
	with open(file_path, "wb") as output_file:
		output_file.write(content)
	return file_path
