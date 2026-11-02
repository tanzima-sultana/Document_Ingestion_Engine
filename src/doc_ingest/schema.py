from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
	"""
	The supported document types. There is one value per parser in parsing/.
	Each value is a plain string, so it is saved in the output JSON as text,
	for example "pdf".
	"""
	PDF = "pdf"


class Page(BaseModel):
	number: int = Field(..., ge=1, description="Page number as shown in the document, starting from 1")
	text: str = Field(..., description="Cleaned text of the page (empty for a page with no text)")


class Document(BaseModel):
	id: str = Field(..., description="Unique identifier derived from content hash")
	type: DocumentType = Field(..., description="Document type (e.g., pdf)")
	source: str = Field(..., description="Original input file path or URL")
	title: str | None = Field(None, description="Document title, if it has one")
	pages: list[Page] = Field(..., description="Cleaned text of each page, in page order")

	@property
	def text(self) -> str:
		"""
		Input: none. Output: the text of the non-empty pages, joined with a blank line.
		"""
		page_texts = []
		for page in self.pages:
			if page.text != "":
				page_texts.append(page.text)
		return "\n\n".join(page_texts)
