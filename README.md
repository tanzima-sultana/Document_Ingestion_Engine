# Document Ingestion Engine

A pluggable Python library that turns raw files into clean, deduplicated documents, one document per file in a single output format. It can be imported into any Python project or run as a standalone command-line tool.

## Features

- **Built on LangChain:** uses LangChain's document parsers underneath.
- **Text cleanup:** removes repeated headers and footers, extra whitespace and stray characters.
- **Deduplication:** removes exact and near-duplicate documents.
- **Skips blank documents:** totally empty documents are never processed or returned.
- **Returns the requested count:** keeps reading past skipped documents until it has the number of documents asked for, or the source runs out.
- **Measured accuracy and quality:** text accuracy, cleanup, metadata and deduplication are evaluated against an independent reference and compared with plain LangChain.
- **Compared with LangChain:** on 100 DUDE PDFs, F1 0.82 vs 0.78, word error rate 0.59 vs 0.64, character error rate 0.46 vs 0.52.

## Installation

Requires Python 3.10 or later.

```bash
pip install git+https://github.com/tanzima-sultana/doc_ingest_engine.git
```

### Quick start

```python
from doc_ingest import ingest_documents

result = ingest_documents("path/to/folder", size=50, document_type="pdf")

for document in result.documents:
	print(document.source, len(document.pages))
```

### Command line

```bash
python -m doc_ingest --path path/to/folder --size 50 --document_type pdf
```

## API

```python
ingest_documents(path, size, document_type, settings=None) -> IngestResult
```

- **path:** a local file or folder.
- **size:** the number of documents to return.
- **document_type:** the type of documents to keep, e.g. `pdf`.
- **settings:** optional `Settings(dedup_threshold=0.90, timeout_seconds=120)`.

`IngestResult` has:

- **documents:** the returned documents.
- **summary:** counts for each step of the run.
- **sources_read:** every source that was read, including the skipped ones.

Invalid input raises `IngestError`. A document that fails is skipped and the run continues.

## Output Format

The output format `Document` is a Pydantic model:

```python
class Page(BaseModel):
	number: int        # page number, from 1
	text: str          # cleaned text of the page ("" for a page with no text)

class Document(BaseModel):
	id: str                    # unique id made from the file's content
	type: DocumentType         # e.g. DocumentType.PDF
	source: str                # path of the original file
	title: str | None          # title, if it has one
	pages: list[Page]          # pages in order

	@property
	def text(self) -> str: ... # all non-empty pages joined with a blank line
```

A returned one looks like this:

```python
Document(
	id="3f9a1c0e8b2d4a71",
	type=DocumentType.PDF,
	source="path/to/folder/report.pdf",
	title="Annual Report",
	pages=[
		Page(number=1, text="Annual Report ..."),
		Page(number=2, text=""),
		Page(number=3, text="Financial summary ..."),
	],
)
```

## Architecture

![Architecture](assets/architecture.svg)

## Evaluation

The evaluation scores the engine's output against an independent reference built from Amazon Textract. Before scoring, the evaluation matches the engine's output to the reference: how many documents and pages were read, returned and left out. 

Run on 50 DUDE dataset.

| | doc_ingest |
|---|---|
| reference_documents | 62 |
| documents_returned | 50 |
| documents_not_returned | 12 |
| documents_not_in_reference | 0 |
| reference_pages | 262 |
| pages_of_returned_documents | 234 |
| pages_of_documents_not_returned | 28 |

- **reference_documents (62):** the documents doc_ingest read to return the 50 requested. It skips empty documents and keeps reading until it has 50.
- **documents_returned (50):** the 50 documents requested.
- **documents_not_returned (12):** documents with no text on any page (`empty_documents` = 12), which doc_ingest leaves out.
- **documents_not_in_reference (0):** every returned document has a reference, so all of them can be scored.
- **reference_pages (262):** the total pages of the 62 documents read.
- **pages_of_returned_documents (234):** the pages doc_ingest is scored on.
- **pages_of_documents_not_returned (28):** the pages of the 12 empty documents.

**Evaluation criteria**

- **Text accuracy:** word recall, precision, F1, word error rate and character error rate.
- **Cleanup:** share of boilerplate removed and share of content lost.
- **Metadata:** source exists, page count matches the file, page numbers run 1 to n, each page matches its reference page, and empty titles.
- **Deduplication:** exact and near copies caught, copies missed and false matches, on a generated test set.

## Results

Results are from one run on the DUDE dataset: 50 documents requested, `pdf` type. doc_ingest read 62 files to return 50.

**Text accuracy**

| | doc_ingest |
|---|---|
| scored_pages | 234 |
| reference_words | 70098 |
| output_words | 69506 |
| matched_words | 56291 |
| word_edits | 44749 |
| reference_characters | 376517 |
| character_edits | 178539 |
| recall | 0.803 |
| precision | 0.8099 |
| f1 | 0.8064 |
| wer | 0.6384 |
| cer | 0.4742 |

- **scored_pages (234):** the pages of the 50 returned documents.
- **reference_words (70098) and reference_characters (376517):** the reference text on those pages.
- **output_words (69506):** the words doc_ingest produced on those pages.
- **matched_words (56291):** words found in both the reference and doc_ingest's text on the same page.
- **recall (0.803):** doc_ingest finds about 80 of every 100 reference words. A higher recall means less of each document's text is lost.
- **precision (0.8099):** about 81 of every 100 words doc_ingest produces are in the reference. A higher precision means fewer extra or wrong words.
- **f1 (0.8064):** recall and precision combined into one score.
- **word_edits (44749) and wer (0.6384):** the words that would need fixing to match the reference exactly, in the same order, as a share of the reference words. Word order counts, so text read in a different order raises it. A lower WER means the text is closer to the reference.
- **character_edits (178539) and cer (0.4742):** the same, counted in characters. A lower CER means the text is closer to the reference.

**Cleanup quality**

| | doc_ingest |
|---|---|
| scored_pages | 234 |
| boilerplate_lines | 297 |
| boilerplate_lines_removed | 179 |
| content_words | 69384 |
| content_words_missing | 13501 |
| boilerplate_removed | 0.6027 |
| content_wrongly_removed | 0.1946 |

- **scored_pages (234):** the pages of the 50 returned documents.
- **boilerplate_lines (297):** lines on those pages that are repeated headers, footers or page numbers. They are found in the reference text, with a rule independent of doc_ingest's own cleanup.
- **boilerplate_lines_removed (179):** the boilerplate lines no longer in doc_ingest's output.
- **boilerplate_removed (0.6027):** about 60 of every 100 boilerplate lines are removed. A higher share means cleaner text.
- **content_words (69384):** the reference words on those pages that are not boilerplate.
- **content_words_missing (13501):** content words not in doc_ingest's output.
- **content_wrongly_removed (0.1946):** about 19 of every 100 content words are missing. This includes words never extracted, not only words removed by cleanup. A lower share means less real content is lost.

**Metadata quality**

| | doc_ingest |
|---|---|
| documents | 50 |
| sources_exist | 50 |
| sources_missing | 0 |
| page_counts_checked | 50 |
| page_counts_match | 50 |
| page_counts_differ | 0 |
| page_counts_not_checked | 0 |
| page_numbers_in_order | 50 |
| page_numbers_not_in_order | 0 |
| documents_without_title_field | 0 |
| titles_empty | 37 |
| documents_in_reference | 50 |
| pages_checked | 229 |
| pages_best_match_same_number | 217 |
| pages_best_match_other_number | 11 |
| pages_no_match | 1 |
| pages_empty | 5 |
| source_exists_rate | 1.0 |
| page_count_match_rate | 1.0 |
| page_numbers_in_order_rate | 1.0 |
| citation_accuracy | 0.9476 |
| title_empty_rate | 0.74 |

- **Source (50, 0, 1.0):** the source file of all 50 returned documents exists, so every document can be traced back to its file.
- **Page count (50, 0, 0, 1.0):** the page count of all 50 documents matches the file's real page count, and none were left unchecked.
- **Page numbers (50, 0, 1.0):** the pages of all 50 documents run 1 to n with no gaps, so a page number always points to the right page of the file.
- **Citation check (229, 217, 11, 1, 0.9476):** each page with text is compared with the reference pages of its document. 217 of 229 best match the reference page with the same number, 11 match a different page, and 1 shares no words with any reference page. A higher citation accuracy means a page's text can be cited by its page number with more confidence.
- **pages_empty (5):** pages with no text, which aren't checked for citation.
- **Title (0, 37, 0.74):** every document has a title field, and 37 of 50 titles are empty. Titles come from the file's own properties, so there's no reference to check them against.

**Deduplication quality**

Run on 100 DUDE dataset

| | doc_ingest |
|---|---|
| originals | 100 |
| originals_kept | 100 |
| false_matches | 0 |
| exact_copies | 20 |
| exact_copies_caught | 20 |
| exact_copies_missed | 0 |
| near_copies | 20 |
| near_copies_caught | 14 |
| near_copies_missed | 6 |
| copies | 40 |
| copies_caught | 34 |
| copies_missed | 6 |
| exact_copy_catch_rate | 1.0 |
| near_copy_catch_rate | 0.7 |
| copy_catch_rate | 0.85 |
| false_match_rate | 0.0 |

- **Test set:** 100 original documents, plus 20 exact copies (the same bytes) and 20 near copies (0.5% of the words changed). Each original has at most one copy.
- **Originals (100, 100, 0, 0.0):** all 100 originals were kept, so no distinct document was removed by mistake. A lower false match rate means fewer real documents are lost.
- **Exact copies (20, 20, 0, 1.0):** all 20 exact copies were removed.
- **Near copies (20, 14, 6, 0.7):** 14 of 20 near copies were removed and 6 were kept. Near copies are caught when their similarity is at or above the 0.90 threshold.
- **All copies (40, 34, 6, 0.85):** 34 of 40 copies were removed. A higher catch rate means fewer duplicates in the output.

## Limitations

## Work in Progress
