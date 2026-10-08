# DocIngestEngine

## 1. Introduction

DocIngestEngine is a Python library and command line tool that turns a pile of raw documents into clean, deduplicated, structured documents that are ready to use downstream, for example as the knowledge base of a RAG system. You point it at a source, either a local file, a local folder of documents, JSONL/JSON files that hold many documents as records, or a Hugging Face dataset (by its name like `owner/name` or by its dataset page URL, streamed so the whole dataset is never downloaded at once), and tell it how many documents you want. It reads the source in batches, downloads/decodes each document, works out its type, parses it in parallel worker processes, cleans the extracted text (removes repeated headers and footers, page numbers, icon characters, broken characters, extra whitespace and blank lines), extracts metadata (source, size, SHA-256 content hash, title, author, creation date), and drops exact duplicates (same content hash) and near duplicates (MinHash signatures with LSH). Every kept document is returned as a Pydantic `Document` (id, type, cleaned text, metadata) together with a run summary that counts what was kept and why anything was skipped. Caching is optional and off by default: without it nothing is kept on disk after the run (raw files go to a temporary folder that is deleted before the documents are returned). With a `cache_dir`, raw files, processed documents and progress are cached there, so a later or interrupted run continues where the last one stopped instead of starting over. One bad document never stops the run (it is skipped and counted), a parse worker process that crashes is recovered from, every document has a parse time limit (on Linux/macOS), and all inputs and settings are validated before any work starts. Download and parse parallelism, batch size, Hugging Face split, parse timeout and the near-duplicate threshold can all be tuned from Python or from the command line. Right now native text PDFs are parsed end to end, with pypdf (the default) or pypdfium2 (an optional, much faster install), and the output format is the same whichever is used; the parser design (one parser class per format, looked up by document type) is ready for more formats such as DOCX, PPTX, XLSX, HTML, Markdown and plain text.

Key results:

- **5000 PDFs in 7.7 minutes:** ingesting 5000 documents streamed from the Hugging Face dataset `pixparse/pdfa-eng-wds` took 462 s with 64 download workers and 16 parse workers, versus 1754 s with 1 and 1, a 3.8x speed-up (20-core machine, 15 GB RAM).
- **Parsing is the bottleneck, and parallel parsing fixes most of it:** going from 1 to 16 parse workers cut parse time from about 1340 s to about 320 s (about 4.2x). Download workers barely matter on this dataset (1 vs 64 download workers saved about 20 s), because the PDF bytes arrive inside the streamed rows.
- **pypdfium2 cuts the best run from 7.7 to 3.4 minutes with the same output:** on the same 5000 streamed documents, `--pdf_parser pypdfium2` took 203 s at 64/16 (parse 77 s versus 324 s with pypdf) and 265 s at 1/1 (parse 130 s versus 1336 s, about 10x faster on one core). The documents kept, failures, duplicates and pages were identical. Downloading is now the bottleneck.
- **3.9x faster than LangChain on the same 6000 local PDFs:** 389 s with 16 parse workers versus 1512 s for LangChain's `PyPDFLoader` (7.9 ms versus 30.2 ms per page). Both use pypdf, so the speed-up comes from parallel parsing; the engine also cleans the text, extracts metadata and removes duplicates, which LangChain does not.
- **Same output no matter how it is tuned:** all four worker settings (1/1, 64/1, 1/16, 64/16) read the same 5101 rows and returned exactly the same result: 5000 documents kept, 94 skipped as parse failures (78 encrypted PDFs, 10 rows detected as plain text with no parser yet, 6 AES-encrypted PDFs) and 7 removed as duplicates.
- **Fast resume (with `cache_dir`):** documents already processed are loaded back from the cache instead of being parsed again, and their saved MinHash signatures are reused for duplicate checking, which made loading 1000 cached documents about 15x faster (0.10 s versus 1.49 s).
- **Robust by design:** a run never stops because of one document; only a failure to write to disk (for example a full disk) stops it, and with a `cache_dir` the progress saved after the last batch lets the next run continue.
- **Tested offline:** 66 tests cover validation, dataset detection, raw data reading, PDF parsing with both parsers, text cleanup, deduplication, caching/progress and full end-to-end runs with caching on and off, without needing network access.

## 2. Tech Stack

**Language and environment**

- **Python 3.10** (developed and benchmarked on 3.10.12; `pyproject.toml` requires 3.10 or newer). The code uses modern type hints such as `list[str]` and `str | None`.
- **Linux** is the development and benchmark platform. Everything runs on other systems too, except the per-document parse time limit, which uses the Unix-only `SIGALRM` signal (see Known Issues).
- A **pyenv virtualenv** (`~/pyenv`) holds the interpreter and all packages; `run.sh` activates it before running.

**Third-party libraries** (four required runtime dependencies and one optional one, listed in `pyproject.toml`)

- **pydantic** (2.x, tested with 2.13): defines the output schema, the `Document` and `Metadata` models, and validates every document as it is built. A document can be turned into JSON and read back from JSON with the same checks, which is how processed documents are cached on disk.
- **datasets** (Hugging Face, 5.x, tested with 5.0): opens Hugging Face datasets in streaming mode, so rows are downloaded as they are read instead of downloading the whole dataset first. It is also used to read a dataset's published info (its row count) and its first row, without downloading the data. It is imported only when a Hugging Face dataset is used, so local runs do not pay its import cost. It brings in `huggingface_hub`, `fsspec` and `httpx` underneath.
- **datasketch** (2.x, tested with 2.0): provides `MinHash` signatures (128 hash permutations, `affine32` hashing scheme) and the `MinHashLSH` index used for near-duplicate detection. LSH lets each new document be checked against every kept document without comparing them one by one.
- **pypdf** (6.x, tested with 6.16): reads PDFs, extracts the text of each page, reads the document information (title, author, creation date) and detects encrypted PDFs. It is pure Python, which is why parsing is CPU-bound and is run in separate worker processes rather than threads. It is the default PDF parser.
- **pypdfium2** (optional, 5.x, tested with 5.14; `pip install "doc-ingest[pdfium]"`): Python bindings for PDFium, Google's PDF engine written in C++. Chosen with `pdf_parser="pypdfium2"`, it does the same jobs as pypdf (page text, title/author/date, encryption check) and parsed the benchmark documents about 10x faster on one core. It is imported only when it is chosen, so it is not needed otherwise. License: Apache-2.0 or BSD-3-Clause.

**Python standard library (the main parts used)**

- `concurrent.futures`: a `ThreadPoolExecutor` downloads/decodes rows in parallel (I/O-bound work), and a `ProcessPoolExecutor` parses documents in parallel (CPU-bound work).
- `multiprocessing`: parse worker processes are started with the `spawn` method rather than `fork`, because forking a process that has Hugging Face streaming threads running can deadlock.
- `signal`: the per-document parse time limit (`SIGALRM`).
- `logging`: all progress, warnings and the run summary are logged, never printed by the library; the command line tool decides how they are shown.
- `argparse`: the command line options, grouped into download settings, process settings and parser settings.
- `dataclasses`: the internal records (`RawData`, `RawDataBatch`, `DatasetConfig`, `Progress`, `Summary`) and the settings (`DownloadSettings`, `ProcessSettings`, `ParserSettings`) and the result (`IngestResult`).
- `hashlib`: SHA-256 for document ids, content hashes and dataset names.
- `urllib`: downloading files that a Hugging Face row only links to (`hf://` paths), and recognizing Hugging Face dataset page URLs.
- `zipfile`, `base64`, `binascii`, `json`, `re`, `io`, `tempfile`, `os`: detecting Office files from their zip contents, decoding base64 content, reading JSONL/JSON records, text cleanup patterns, in-memory file handling, the temporary raw-file folder when caching is off, the cache folder write check, and file system work.

**Packaging and tooling**

- **setuptools** with a `pyproject.toml` (`src/` layout). Installing the package (`pip install -e .`) adds a `doc-ingest` command; without installing, the tool runs as `python -m doc_ingest` or through `run.sh`.
- **pytest** (tested with 9.1) runs the test suite. The tests themselves are written with the standard `unittest` module and build their own small PDFs in memory, so they need no network and no test data files. pytest is a development tool only and is not a runtime dependency.
- **Bash**: `run.sh` is the benchmark/run script (activates the environment, sets `PYTHONPATH`, clears its cache folder, runs the tool and saves a log).

## 3. Installation / Setup

**What you need**

- Python 3.10 or newer.
- Internet access only if you ingest a Hugging Face dataset. Local files, local folders and JSONL/JSON files work fully offline, and so do the tests.
- Enough disk space for a copy of every raw document read in a run. With caching off they sit in a temporary folder until the run ends; with a `cache_dir` they are kept across runs, together with one JSON file per processed document and a small progress file (see Configuration).

**Steps**

1. Clone the repository: `git clone git@github.com:tanzima-sultana/doc_ingest_engine.git` and go into the folder.
2. Create and activate a virtual environment with Python 3.10+. This project uses a pyenv virtualenv at `~/pyenv`, activated with `source ~/pyenv/bin/activate`; `run.sh` expects it to be there. Any other virtual environment works too if you run the tool yourself instead of through `run.sh`. Do not install into the system Python.
3. Install the package and its four dependencies (pydantic, datasets, datasketch, pypdf) from the repository root with `pip install -e .`. The `-e` (editable) install means code changes take effect without reinstalling, and it adds the `doc-ingest` command to the environment.
   - Optional: to use pypdfium2 as the PDF parser, install the `pdfium` extra with `pip install -e ".[pdfium]"` (or just `pip install pypdfium2`). Without it, choosing pypdfium2 stops the run before any work with a message saying what to install.
   - If you prefer not to install the package, install just the dependencies and point Python at the source folder instead: `export PYTHONPATH="$(pwd)/src"` from the repository root. This is what `run.sh` does. You then run the tool as `python -m doc_ingest`.
4. Optional, for Hugging Face: create a `.env` file in the repository root containing `export HF_TOKEN=<your Hugging Face access token>`. `run.sh` loads it automatically if it exists. A token is not needed for public datasets, but Hugging Face gives authenticated requests higher rate limits, which helps when streaming thousands of rows, and it is required for gated or private datasets. `.env` is listed in `.gitignore`, so the token is never committed.

**Running the tests**

- Install pytest in the same environment (`pip install pytest`); it is a development tool, not a runtime dependency.
- From the repository root, with the environment active and `PYTHONPATH` set to `src` (or the package installed), run `python -m pytest tests`. The standard library runner works as well: `python -m unittest discover -s tests`.
- All 66 tests run offline in about 3 seconds. They create small PDFs in memory, write them to temporary folders and clean up after themselves, so they never touch a real cache folder and need no test data files or network access.
- What they cover: input and settings validation, dataset type and format detection (local folders, single files, JSONL, Hugging Face names and URLs), raw data reading and resuming from a row count, PDF parsing and metadata, text cleanup, exact and near-duplicate detection (including reuse of saved MinHash signatures), cache and progress files, and full end-to-end ingestion runs including resuming from the cache and running with caching off (checking nothing is left on disk).

**Project conventions (for anyone changing the code)**

- Indentation is tabs everywhere (an `.editorconfig` is included), except YAML files.
- Code style is deliberately verbose and explicit: no list/dict/set comprehensions, no `map`/`filter`/`reduce`, one statement per line, descriptive names, and every function has a short docstring saying its input, its output and what it does.
- Any new shell script follows the same pattern as `run.sh`: activate `~/pyenv`, then set `PYTHONPATH` to the repository's `src` folder.
- New third-party dependencies are added only after discussion.

## 4. Usage

There are three ways to run DocIngestEngine. All of them end up calling the same function, `ingest_documents`, so they behave the same way.

**1. `run.sh` (the benchmark script)**

- Run `./run.sh` from anywhere; it moves to the repository root itself, activates `~/pyenv`, loads `.env` if present, sets `PYTHONPATH`, and runs the tool.
- The source and size are set at the top of the script: `SIZE=5000` and `INPUT_PATH="pixparse/pdfa-eng-wds"`. Every setting is also listed there as a variable (download workers, max batch rows, Hugging Face split, parse workers, parse timeout, dedup threshold), so you can change any of them by editing one line.
- The two worker counts can be given as arguments: `./run.sh <download_workers> <parse_workers>`, for example `./run.sh 64 16`. Without arguments it uses 64 and 16.
- Benchmark runs cache into `outputs/` in the repository (`--cache_dir`). **`run.sh` deletes `outputs/` before every run**, so each run starts from nothing (no raw files, no processed documents, no progress) and runs are comparable.
- Everything the run prints is shown on screen and also saved to `logs/log_<size>_download<download_workers>_parse<parse_workers>.txt`, for example `logs/log_5000_download64_parse16.txt`. Note that the file name only contains the size and the two worker counts, so runs that differ only in another setting overwrite each other's log.
- The script fails with an error exit code if the tool fails (it uses `pipefail`, so the `tee` into the log does not hide the failure).

**2. The command line tool**

- Run `python -m doc_ingest --size <number> --input_path <source>` with the environment active and `PYTHONPATH` pointing at `src`, or, after `pip install -e .`, simply `doc-ingest --size <number> --input_path <source>` from anywhere.
- `--size` (how many documents you want) and `--input_path` (where to read them from) are required. Every other option is optional and falls back to its default (see Configuration); `--help` lists them in three groups, "download settings", "process settings" and "parser settings", with their defaults.
- `--pdf_parser pypdfium2` parses PDFs with pypdfium2 instead of pypdf (see Configuration).
- `--cache_dir <folder>` turns caching on (see Configuration). Without it, caching is off and nothing is kept on disk after the run.
- At the start it prints the size, input path, cache folder (or `off`) and the full download, process and parser settings it will use. During the run it logs each batch ("Batch 3: fetching 4500 row(s).") and a warning for every document or row it skips, with the reason. At the end it logs the run summary and prints "Document ingestion finished".
- Exit code 0 means the run finished. Exit code 1 with a single line "Ingestion stopped: <reason>" means a problem you can fix: a bad size, input path, cache folder or setting value, or a damaged progress file. Any other error (a bug, or the disk becoming unwritable, for example when it is full) stops the run with a full Python traceback, also with exit code 1; with a `cache_dir`, the progress saved after the last finished batch lets the next run continue.
- Only `doc_ingest`'s own progress messages are shown at INFO level; other libraries (for example the HTTP library Hugging Face uses) only show warnings, so the log is not flooded with HTTP requests.

**3. From your own Python code (for example a RAG pipeline)**

- Import it with `from doc_ingest import ingest_documents` and call `ingest_documents(size, input_path)`. Optionally pass `download_settings=DownloadSettings(...)`, `process_settings=ProcessSettings(...)` and/or `parser_settings=ParserSettings(...)` (all importable from `doc_ingest`) to change any setting, for example `parser_settings=ParserSettings(pdf_parser="pypdfium2")`; leave them out to use the defaults. Pass `cache_dir="<folder>"` to turn caching on; leave it out and nothing is kept on disk after the call.
- The call returns an `IngestResult` with four fields:
  - `documents`: a list of up to `size` `Document` objects. It can be shorter than `size` if the source runs out of rows.
  - `summary`: the run's `Summary` with every count and timing (see below), so your code can check, for example, how many documents failed to parse, without reading logs.
  - `raw_dir`: the absolute path of the cache folder holding the raw files (`<cache_dir>/<dataset name>/data/raw`), each saved as `<doc.id>.<type>`. `None` when caching is off.
  - `processed_dir`: the absolute path of the cache folder holding the kept documents (`<cache_dir>/<dataset name>/data/processed`), each saved as `<doc.id>.json`, so `os.path.join(result.processed_dir, doc.id + ".json")` is the file for a returned document. `None` when caching is off. A folder is only created once something is saved to it, so if every document of the first run is skipped it may not exist yet.
- The library never prints and never configures logging; it only logs through the `doc_ingest` logger. Your application decides what to show (for example silence it with `logging.getLogger("doc_ingest").setLevel(logging.ERROR)`).
- Errors you can fix are raised as `IngestError` (importable from `doc_ingest`, a subclass of `ValueError`), so you can catch them separately from bugs.
- **Important: protect the call with `if __name__ == "__main__":` when it sits at the top level of the script you run** (`python my_script.py`). Parse workers are started with `spawn`, which starts a fresh Python for every worker that re-imports your script; without the guard, each worker would run your top-level code again and the run fails with `RuntimeError: ... bootstrapping phase` and `BrokenProcessPool`. The guard is not needed when the call is inside a function of an imported module (for example a web request handler or a pipeline step), or with `python -c`. Jupyter should also work but has not been tested yet. This is the same rule as for PyTorch's DataLoader and Python's own `multiprocessing`. Spawn is used instead of fork because Hugging Face streaming runs background threads, and forking a process that has threads can deadlock; threads instead of processes would avoid the guard but would parse on a single core, because pypdf is pure Python.

**What you can give as `input_path`**

- **A single local file**, for example `report.pdf`. Its type comes from its extension.
- **A local folder** of documents, for example `data/pdfs`. All files in it and in its subfolders are read, in sorted order, skipping hidden files and hidden folders (names starting with "."). The folder can mix document types; each file's type comes from its own extension, and files with an unknown extension are skipped.
- **JSONL or JSON files** holding many documents as records (a single file, or a folder of them). The field holding each document is found automatically from the first record, trying `content`, `text`, `body`, `data`, `bytes`, `raw`, `document` and `pdf` in that order. Each record's value can be raw bytes, base64-encoded bytes, plain text, or an `hf://datasets/...` link to a file on Hugging Face (which is then downloaded). A JSON file must hold one object or a list of objects.
- **A Hugging Face dataset**, by its name in the form `owner/name` (for example `pixparse/pdfa-eng-wds`), or by its dataset page URL (for example `https://huggingface.co/datasets/pixparse/pdfa-eng-wds`, also with `/tree/...` or `/viewer/...` after it), which is turned into the name automatically. The dataset is streamed: rows are downloaded as they are read, so the whole dataset is never downloaded at once. File columns are kept as raw bytes, and columns that only hold an `hf://` path are downloaded one file per row.
- If a path exists locally and also looks like a Hugging Face name (for example a local folder called `owner/name`), the local path wins and a note is logged.
- **Not supported:** other web URLs (a URL that is not a Hugging Face dataset page is rejected before anything runs), and web links inside records (only Hugging Face file links are downloaded).
- Record rows (JSONL/JSON/Hugging Face) have no file extension, so their type is detected from their first bytes: PDF ("%PDF"), DOCX/PPTX/XLSX (zip files, told apart by the folders inside), HTML (an `<html>` or `<!doctype html>` tag near the start), and anything else as plain text. An `hf://` link with a known extension uses that extension instead.

**What a `Document` contains**

- `id`: the first 16 hex characters of the SHA-256 hash of the document's raw bytes, so the same document always gets the same id, in every run.
- `type`: the detected document type (currently always `pdf` for returned documents).
- `text`: the cleaned full text, with pages joined by a blank line.
- `metadata`:
  - `source`: where the document came from. A local file's path; for a record, `<input_path>#<row number>` (for example `pixparse/pdfa-eng-wds#1234`); for a downloaded Hugging Face file, its download URL.
  - `file_size_bytes`: the size of the raw document.
  - `content_hash`: the full SHA-256 of the raw bytes, used for exact duplicate detection.
  - `minhash_signature`: the 128 MinHash values used for near-duplicate detection (empty for documents too short to have any five-word sequence).
  - `title`, `author`, `creation_date`: read from the PDF's own document information when present (the date in ISO 8601 format, keeping the time zone); each is empty when missing or unreadable. Both PDF parsers read them the same way (including values the PDF stores as references to other objects) and convert the date with the same rules, so they give the same values.
  - `page_count`: the number of pages (empty for formats without pages).
  - `parser`: the library that extracted the text, `pypdf` or `pypdfium2`. Everything else in the document has the same format whichever parser is used; only the extracted text itself can differ slightly (for example spacing and line breaks).

**What the summary contains**

- The run: documents requested and returned, whether the dataset ran out of rows, and how many batches were read.
- Rows and documents: raw rows read, rows downloaded/decoded, documents loaded from the cache (always 0 with caching off), and documents newly processed.
- Skipped, by reason: rows that failed to download/decode, documents with an unsupported type, rows that could not be prepared for parsing (type, source or raw file could not be worked out or saved), documents that failed to parse (including encrypted PDFs and parse time-outs), documents with no text (for example scanned PDFs), documents whose duplicate check or saving failed, cached documents missing or damaged on disk, the total skipped, and duplicates removed.
- Timing: total time, download time and parse time (parse time includes duplicate checking and saving).
- Pages: the pages of every parsed document (kept, empty or duplicate) and pages per second of parse time.

**What is stored on disk, and how resuming works**

- Caching off (the default): raw files are written to a temporary folder, because the parse workers read each document from disk, and the folder is deleted before the documents are returned, also when the run fails. No processed documents or progress are written, so every run starts from the first row. Everything below applies only with a `cache_dir`.
- Everything is stored under `cache_dir` (see Configuration), in one folder per dataset named after the dataset plus a short hash of its full path or name (for example `pdfa-eng-wds_6b87b8a4`), so two inputs with the same folder name never share data. A Hugging Face split other than `train` is part of the name too (for example `pdfa-eng-wds_test_d6f9537c`), so two splits never share data either.
- Inside it: `data/raw/<doc_id>.<type>` holds each downloaded raw document, `data/processed/<doc_id>.json` holds each kept document as JSON, and `progress.json` records how many source rows have been read so far, the ids of the processed documents and the ids of the skipped ones. The progress file is written to a temporary file first and then swapped into place, so a crash can never leave it half-written.
- Running again with the same input continues from the saved progress:
  - Documents already processed are loaded back from `data/processed/` (with their saved MinHash signatures, so they are not hashed again) and count towards `size`. If they are already enough, nothing new is read at all.
  - Otherwise reading continues after the rows read by earlier runs, so no row is downloaded or parsed twice, and documents skipped before are not tried again.
  - A cached document that is missing or damaged on disk is marked as skipped and the run goes on.
- Asking for a smaller `size` than before returns that many documents from the cache; asking for a larger one continues reading where the last run stopped.
- To start over for a dataset, delete its folder in the cache folder (`run.sh` deletes its whole `outputs/` cache folder before every run).

## 5. Configuration

Only `size` and `input_path` are required. Everything else is optional and has a default, so you only set what you want to change.

**Required inputs**

- `size` (`--size`): the most documents to return. Must be a whole number greater than 0 (`True`/`False` are rejected even though Python treats them as numbers).
- `input_path` (`--input_path`): where to read documents from (see Usage for every kind of source). Must not be empty; must be an existing local file or folder, or a Hugging Face dataset name or page URL.

**Download settings** (`DownloadSettings` in Python, the "download settings" group on the command line): how the source is read.

- `download_workers` (`--download_workers`, default **64**): how many rows are downloaded/decoded at the same time, in threads. Must be a whole number of at least 1. It matters a lot for datasets whose rows only link to files (one HTTP request per document, mostly waiting on the network), and very little for datasets that carry the bytes inside the rows, local folders, or base64 content. On `pixparse/pdfa-eng-wds` going from 1 to 64 saved only about 20 seconds out of about 8 minutes.
- `max_batch_rows` (`--max_batch_rows`, default **256**): the most source rows read in one batch. Must be a whole number of at least 1. It limits memory use, because one batch's raw bytes are held in memory at once, and progress is saved after every batch, so it is also how much work an interrupted run can lose. Each batch reads only as many rows as documents are still missing, up to this limit, so batches shrink near the end of a run. Bigger batches mean fewer pauses where all parse workers wait for the slowest document of the batch.
- `hugging_face_split` (`--hugging_face_split`, default **train**): which split of a Hugging Face dataset is read. Must be non-empty text. Whether the split exists is only found out when the dataset is opened. A split other than `train` gets its own dataset folder (its name includes the split), so cache and progress of different splits never mix; `train` keeps the folder name it always had. It has no effect on local sources.

**Process settings** (`ProcessSettings` in Python, the "process settings" group on the command line): how raw files become kept documents.

- `parse_workers` (`--parse_workers`, default **one per CPU core**): how many documents are parsed at the same time, each in its own process. Must be left unset (one per core, or 1 if the core count is unknown) or be a whole number of at least 1. This is the setting that matters most: parsing is CPU-bound pure-Python work, and going from 1 to 16 workers made parsing about 4.2x faster in the benchmark. A value around the number of CPU cores is a good choice; more than that does not help. Each worker is a separate Python process, so memory use grows with this number.
- `parse_timeout_seconds` (`--parse_timeout_seconds`, default **120**): the longest time one document may take to parse; a document that takes longer is skipped and counted as a parse failure, so one pathological PDF cannot stall the run. Must be a whole number of at least 1 (0 would switch the limit off, so it is rejected). Only enforced on systems with `SIGALRM` (Linux/macOS); on Windows it is accepted but has no effect.
- `dedup_threshold` (`--dedup_threshold`, default **0.90**): the estimated similarity (Jaccard similarity of the documents' five-word sequences) at or above which a document counts as a near duplicate of one already kept and is dropped. Must be a number greater than 0 and at most 1 (0 would mark everything as a duplicate of the first document). Higher values drop only almost identical documents; lower values also drop documents that share a lot of text. The right value depends on the data and on what the documents are used for; exact duplicates (same bytes) are always dropped regardless of this setting.

**Parser settings** (`ParserSettings` in Python, the "parser settings" group on the command line): which library parses each document type. A field is added only when a format has more than one library to choose from.

- `pdf_parser` (`--pdf_parser`, default **pypdf**): `pypdf` or `pypdfium2`. Must be one of these, and the chosen library must be installed (pypdfium2 is optional, see Installation). Both follow the same rules (non-PDF and encrypted files are skipped) and give the same document format and metadata; `metadata.parser` records which one was used. pypdfium2 is much faster: on the benchmark's 5000 documents it parsed about 10x faster on one core, and cut the best run from 462 s to 203 s.

All settings are checked before any work starts, together with `size`, `input_path` and `cache_dir` when it is given. A value of the wrong type raises `TypeError`; a value out of range raises `IngestError`, which the command line tool shows as a single "Ingestion stopped: <reason>" line, for example "Ingestion stopped: download_workers must be at least 1, got 0".

**Caching** (`cache_dir`, `--cache_dir`, default **off**)

- Off: nothing is kept on disk after the run (see "What is stored on disk" above). The library never writes to a folder you did not choose.
- On: give a folder, from Python with `ingest_documents(..., cache_dir="<folder>")` or from the command line with `--cache_dir <folder>`. Raw files, processed documents and progress are kept there, so later runs resume and reuse them. A leading `~` is expanded. `run.sh` passes the repository's `outputs/` folder.
- Checked before the run starts, only when given: it must not be empty text, must not be an existing file, must not be the input folder itself or a folder inside the input folder (otherwise the tool would read its own output as input), and must be creatable and writable (it is created if it does not exist, and a small test file is written and removed).

**Environment variables**

- `HF_TOKEN`: a Hugging Face access token, read by the Hugging Face libraries; optional for public datasets (higher rate limits), required for gated or private ones. `run.sh` loads it from `.env`.

**Fixed values (not configurable, set in the code)**

- Near-duplicate detection: 128 MinHash permutations, the `affine32` MinHash hashing scheme, and five-word shingles (overlapping five-word sequences). Saved signatures are reused on later runs only if they have 128 values; changing the shingle size would require clearing the processed cache, because old signatures cannot be told apart.
- Header/footer removal: only for documents with at least 3 pages; a first or last line of a page is treated as a header/footer when it appears on at least half of the pages, compared in lowercase with every number replaced, so "Page 3 of 10" and "Page 4 of 10" count as the same line.
- Text cleanup also removes Unicode private-use characters (used by icon fonts, for example phone and mail icons), repairs characters that pypdf returns split into two halves, collapses runs of spaces and tabs into one space, and keeps at most one blank line in a row.
- Record handling: the list of content field names tried (`content`, `text`, `body`, `data`, `bytes`, `raw`, `document`, `pdf`), a string must be at least 16 characters (and pass a strict decode) to be treated as base64, and JSONL/JSON are the container file types.
- Hugging Face file downloads use a 30-second timeout and identify themselves with the user agent `DocIngestEngine/1.0`.
- File extensions mapped to document types: `pdf`; `docx`; `pptx`; `xlsx`; `csv`; `html`/`htm`; `md`/`markdown`; and `txt`, `log`, `py`, `js`, `java`, `c`, `cpp`, `h`, `sh` as plain text. Only `pdf` has a parser so far.

## 6. Architecture

**The big picture**

DocIngestEngine is a staged pipeline with a single public entry point. The layers, from the outside in:

1. **Entry points**: `__init__.py` is what you import (it exposes `ingest_documents`, `IngestResult`, `IngestError`, `Document`, `DownloadSettings`, `ProcessSettings`, `ParserSettings` and nothing else), and `__main__.py` is what you run from a terminal (`python -m doc_ingest`, the installed `doc-ingest` command, or `run.sh`). The command line tool only reads options, sets up logging, builds the two settings objects, calls `ingest_documents` and prints the result line; it contains no pipeline logic.
2. **Orchestrator**: `ingest_documents` (in `ingest.py`) fills in default settings, runs one `IngestEngine`, and with caching off deletes its temporary folder afterwards. `IngestEngine` holds the state of one run (documents collected so far, processed and skipped ids, rows read, the summary, the duplicate checker and the parse worker pool) and drives the steps below. Each step is a method, so the steps share state through the engine instead of passing many parameters around.
3. **Stage modules**: one module per job (dataset discovery, raw data fetching, parsing, cleanup, metadata, deduplication, caching, progress, validation, summary), each usable and testable on its own.

**What happens in one run** (the numbered steps match the comments in `ingest.py`)

- **Step 0, check everything first.** A Hugging Face dataset page URL is turned into the dataset name. Then `size`, `input_path`, `cache_dir` (only when given) and every download/process setting are validated. Nothing is read or downloaded before this passes, and the cache folder is only created as part of the last check (with caching off, the empty temporary folder already exists). Only after validation is the duplicate checker created with the chosen threshold.
- **Step 1, describe the dataset.** `get_dataset_config` builds a `DatasetConfig`: the dataset's name (readable name plus a short hash, plus the split if not `train`), whether it is local or Hugging Face, its format (`folder`, `jsonl`/`json`, a single file's extension, or `hf`), which record field holds the documents (for record-based datasets), and how many documents it has when that can be known cheaply (a Hugging Face dataset's published row count, the number of supported files in a folder, 1 for a single file, unknown for JSONL/JSON). The format is worked out once and passed to the other helpers.
- **Step 2, load progress** (caching on only; caching off starts from the first row). `progress.json` for this dataset gives the number of source rows read by earlier runs, the processed document ids and the skipped ids. A missing file means a fresh start; a damaged one, one with a missing field, or one belonging to another dataset stops the run with an `IngestError`.
- **Step 3, reuse the cache** (caching on only). Each previously processed document is loaded from `data/processed/<id>.json` and added to the duplicate checker (reusing its saved MinHash signature). A missing or damaged file, or one that cannot be added to the duplicate checker, is marked as skipped and the run goes on. If the cache alone already has `size` documents, progress is saved (keeping the ids that were not needed this time) and the run ends here without reading the source at all.
- **Step 4, read the source in batches** until `size` documents are collected or the source runs out. The parse worker pool is started once before the loop and shut down after it, even if the run fails.
  - **4a, fetch.** `RawDataFetcher` reads as many rows as documents are still missing, at most `max_batch_rows`, continuing after the rows read in earlier runs. The rows are downloaded/decoded in parallel threads (`download_workers`). For each decoded row it computes the document id from the bytes, works out the document type, records where it came from, and saves the bytes to `data/raw/<id>.<type>` (in the cache folder, or the temporary folder when caching is off). The result is a `RawDataBatch`: one `RawData` (id, type, raw file path, source) per prepared document, plus counts of rows read, downloaded and failed.
  - **4b, skip known failures.** Documents that were skipped in an earlier run (for example a PDF that failed to parse) are not tried again.
  - **4c, parse in parallel.** The documents are sent to the parse worker processes. In each worker, `parse_document` picks the parser for the document's type, sets the parse time limit, and returns `(id, Document)` or `(id, None)` on any failure; it never raises. Results come back in the same order as the documents went in, so a run is deterministic.
  - **4d, decide what to keep.** For each result, in order: a failed parse is skipped; a document with no text (for example a scanned PDF) is skipped; an exact or near duplicate of a document already kept is dropped; anything else is saved to `data/processed/<id>.json` (caching on only) and added to the results. Because kept documents are checked in a fixed order, the first copy of a duplicate is always the one kept.
  - **4e, save progress** (caching on only: rows read so far, processed ids, skipped ids) after every batch, so an interrupted run loses at most the batch in progress.
- **Finish.** The summary's final numbers are filled in, the run summary is logged, and an `IngestResult` (the list of documents, the summary, and the raw and processed cache folders, or `None` for both when caching is off) is returned.

**How data flows between stages**

- A **row** (a record dict from JSONL/JSON/Hugging Face, or a local file path) becomes a **`RawData`** (id, type, saved raw file, source) in the fetch stage, which becomes a **`Document`** (id, type, text, metadata) in the parse stage.
- Internal records are plain dataclasses: `DatasetConfig`, `RawData`, `RawDataBatch`, `Progress`, `Summary`, and the settings and result types. Only the output types (`Document`, `Metadata`, `DocumentType`) are Pydantic models, because that is where validation and JSON conversion are needed: documents leave the library and are written to and read back from the cache.

**What each module does**

- `ingest.py`: `ingest_documents`, `IngestEngine` (the steps above, the parse worker pool and its crash recovery) and `IngestResult`.
- `settings.py`: `DownloadSettings`, `ProcessSettings` and `ParserSettings`, every field with a named default, and the list of PDF parser names. All defaults live here and nowhere else.
- `validate.py`: every up-front check, one small function per check, run in a fixed order so the first problem found is reported.
- `error.py`: the library's exception `IngestError` (problems the user can fix) and `describe_error`, which turns any exception into safe, printable "ErrorType: message" text.
- `dataset_config.py`: builds the `DatasetConfig` by combining the answers from the local and Hugging Face modules, and holds the record handling both share: finding which field holds the document and how each record's value is encoded (raw bytes, base64, plain text or an `hf://` file link).
- `dataset_local.py`: local files, folders and JSONL/JSON container files: working out the format, counting documents, reading the first record, listing files.
- `dataset_hf.py`: everything Hugging Face: recognizing a dataset name or page URL, reading the first row and the published row count of a split, turning `hf://` file paths into download URLs and download requests. Web URLs are only accepted as Hugging Face pages or files, so the URL helpers live here too.
- `document_type.py`: works out a document's type from its file extension or, for records, from its first bytes.
- `raw_data.py`: `RawDataFetcher` (reading rows in a fixed order, resuming after a row count, parallel downloading/decoding, saving raw files) and the `RawData`/`RawDataBatch` records.
- `parser.py`: the `Parser` base class every format implements, the registry that maps a document type and library name to its parser (the library is picked from `ParserSettings`), and `parse_document`, the worker-side wrapper with the time limit.
- `parsers/pdf.py`: two interchangeable PDF parsers, `PyPdfParser` (pypdf) and `PyPdfium2Parser` (pypdfium2). Each opens the PDF once with its library, rejects non-PDFs and encrypted PDFs, extracts each page's text (a page that fails is treated as empty instead of losing the document) and reads the title, author and raw creation date. Everything after that is shared: `build_pdf_document` cleans the text and fills all metadata, and `parse_pdf_date` converts the date, so the output cannot differ by parser.
- `text_cleanup.py`: format-independent cleanup of page texts (it takes plain strings, so every future parser can reuse it).
- `metadata.py`: the generic metadata every format has (source, size, content hash) and small helpers that tidy property values (title/author text, dates); each parser fills in its own format's properties.
- `dedup.py`: `Deduplicator` (exact and near-duplicate detection).
- `cache.py`: saving/loading processed documents as JSON.
- `progress.py`: the `Progress` record and loading/saving `progress.json`.
- `summary.py`: the `Summary` counters and logging the run summary.
- `schema.py`: the Pydantic output models and the `DocumentType` values.

**Concurrency**

- **Threads for downloading, processes for parsing.** Downloading and decoding mostly wait on the network or disk, so threads are enough and cheap. Parsing is CPU-bound pure-Python work (pypdf), and Python threads cannot run Python code on several cores at once, so parsing runs in a pool of separate processes.
- **Spawn, not fork.** Hugging Face streaming runs background threads, and forking a process that has threads can deadlock. Spawned workers start as fresh Python processes, which is why a script calling the library at its top level needs the `__main__` guard (see Usage).
- **Worker crash recovery.** If a worker process dies (for example the operating system kills it for using too much memory, or a C library crashes), Python marks the whole pool as broken and every unfinished document fails at once, so it is not known which document caused it. The engine then shuts the broken pool down, starts a new one, and parses the unfinished documents again one at a time. Only the document that kills a worker again is skipped; the others are still parsed, and the pool is replaced again whenever needed.
- **Per-document time limit.** Inside a worker, a `SIGALRM` alarm interrupts a document that takes longer than `parse_timeout_seconds`; it is reported as a parse failure and the worker moves on to the next document.

**Failure handling**

- The rule: **one bad document never stops a run**. Every stage catches failures per row or per document, logs a warning with the reason, counts it in the summary under its own reason, and moves on. With a `cache_dir`, a skipped document's id is stored in the progress file, so later runs do not try it again.
- What is skipped and counted: rows that cannot be read or decoded, documents of an unsupported type, rows whose type, source or raw file cannot be worked out or saved, parse failures (broken, non-PDF and encrypted files, time-outs, crashed workers), documents with no text, failures of the duplicate check or of saving a document, and cached documents that are missing or damaged.
- What stops a run: a problem with the inputs, settings, cache folder or progress file (`IngestError`, shown as one clean line), and a failure to write to disk during the run (`OSError`, for example a full disk), because every later document would fail in the same way. With a `cache_dir`, the progress saved after the last finished batch lets the next run continue.

**Resumability and repeatability**

- Document ids come from a hash of the document's bytes, so the same document always has the same id, in every run and on every machine.
- Rows are read in a fixed order (sorted files for local folders, the dataset's own order for records and Hugging Face), and progress stores how many rows have been read, so a later run skips exactly those rows.
- The progress file is replaced atomically (written to a temporary file, then swapped in), so it is never half-written.
- Results are processed in a fixed order, so the same input gives the same output regardless of how many workers are used. The benchmark confirmed this: four different worker settings returned exactly the same 5000 documents, failures and duplicates.

**Deduplication**

- Exact duplicates: every kept document's SHA-256 content hash is remembered; a new document with a hash already seen is dropped.
- Near duplicates: the document's text is split into overlapping five-word sequences ("shingles"), a 128-value MinHash signature is computed from them, and an LSH index (locality-sensitive hashing) is asked whether any kept document is likely to be at least `dedup_threshold` similar. LSH answers this without comparing the new document to every kept one.
- The signature is saved inside the document's metadata, so documents loaded from the cache on a later run are added to the index from their saved signature instead of being hashed again (about 15x faster for 1000 cached documents). A saved signature with the wrong number of values is ignored and recomputed.
- A document too short to have any five-word sequence is only checked for exact duplicates.

**Text cleanup**

- Each page's lines have icon-font characters removed, broken characters repaired, and whitespace collapsed.
- Repeated headers and footers are found by looking at the first and last non-empty line of every page: a line (compared in lowercase with all numbers replaced) that appears on at least half of the pages of a document with at least 3 pages is removed everywhere. This removes running titles and "Page n of m" footers while keeping short documents intact.
- Runs of blank lines are reduced to one, empty pages are dropped, and pages are joined with one blank line.
- Cleanup works on plain page strings and knows nothing about PDFs; extracting the page texts is the parser's job.

**Adding a new format**

The parser design is a plug-in pattern: each format is one class that implements `Parser.parse` (raw document in, `Document` out), registered under its document type and library name in `parser.py`. A second library for an existing format is one more class in the same file, one registry entry and one `ParserSettings` field (as was done for pypdfium2). A new format (for example DOCX) needs its parser class in `parsers/`, one registry entry, its own text extraction and property reading, and it reuses the shared cleanup, generic metadata, deduplication, caching and failure handling unchanged. Type detection already recognizes DOCX, PPTX, XLSX, CSV, HTML, Markdown and plain text files. The registry is built inside the lookup function (imported lazily) because the parser classes import the base class from `parser.py`, and importing them at the top of that module would create a circular import.

**Design choices worth knowing**

- **Classes where there is state, functions where there is not.** `IngestEngine` (one run), `RawDataFetcher` (reading position and settings) and `Deduplicator` (seen hashes and the LSH index) are classes; cleanup, metadata, caching, progress, validation and dataset discovery are plain functions.
- **One function in front.** Callers only see `ingest_documents` and a few types; everything else can change without breaking them, the same way `requests.get` wraps a session object.
- **Libraries log, applications decide.** The library only logs through `logging.getLogger(__name__)` with lazy `%s` formatting; only the command line tool configures what is shown and where.
- **Settings grouped by stage, all optional.** Two settings objects instead of a long list of parameters, with all defaults in one module, validated up front like the other inputs.
- **Errors in one place.** `IngestError` separates "you can fix this" from bugs, so the command line tool shows a clean message for the first and a full traceback for the second.
- **No hidden global state.** There are no module-level caches or mutable globals; values that several helpers need (such as the dataset format) are worked out once and passed along, and every run's state lives in its own `IngestEngine`.
- **Format-specific code lives in the parser.** Cleanup and generic metadata take plain values and know nothing about PDFs, so adding a format only touches its own parser file.
- **Explicit, verbose code style** (no comprehensions or `map`/`filter`, one statement per line, short input/output docstrings on every function), chosen for readability.

## 7. Performance Summary

**What was measured**

- The question: how much do download workers and parse workers each speed up a real ingestion run when streaming from Hugging Face?
- Dataset: the first 5000 documents streamed from `pixparse/pdfa-eng-wds` (about 2.16 million English text PDFs, not gated), split `train`.
- Every run used `run.sh`, which deletes its whole cache folder `outputs/` (raw files, processed documents and progress) before starting, so every run streamed and parsed everything from scratch. Same `--size 5000` every time.
- Settings other than the workers were the defaults: 256 rows per batch, 120 s parse time limit, 0.90 near-duplicate threshold.
- Machine: 20 CPU cores, 15 GB RAM, Linux, Python 3.10.12, pypdf 6.16, with a Hugging Face token set (`HF_TOKEN`).
- Each configuration was run once. Times come from the run summary: download time (reading the stream, decoding, saving raw files), parse time (parsing plus duplicate checking and saving processed documents) and total time. The full logs are in `logs/log_5000_download<d>_parse<p>.txt`.

**Results**

| Download workers / parse workers | Total time | Download time | Parse time | Documents per second | Speed-up vs 1/1 |
|---|---|---|---|---|---|
| 1 / 1 | 1754 s (29.2 min) | 406 s* | 1336 s | 2.9 | 1.0x |
| 64 / 1 | 1517 s (25.3 min) | 155 s | 1351 s | 3.3 | 1.2x |
| 1 / 16 | 481 s (8.0 min) | 148 s | 318 s | 10.4 | 3.6x |
| **64 / 16** | **462 s (7.7 min)** | **127 s** | **324 s** | **10.8** | **3.8x** |

\* Probably an outlier rather than an effect of the setting: `1 / 16` used the same single download worker and took 148 s. The 1/1 run was the first of the series, so a slower network or colder Hugging Face caches at that time are the likely cause. It was not rerun.

Every run read the same 5101 rows in 21 batches and produced exactly the same result: **5000 documents kept, 94 skipped as parse failures, 7 dropped as duplicates**, 0 download failures, 0 documents without text. The 94 parse failures were 78 encrypted PDFs (skipped on purpose), 10 rows detected as plain text (no text parser yet, so they are reported as parse failures), and 6 AES-encrypted PDFs (pypdf needs the `cryptography` package to even open them; they would be skipped as encrypted anyway).

**What the numbers show**

- **Parsing is the bottleneck.** With one parse worker, parsing is about 76% of the run (about 0.27 s per document on one core).
- **Parse workers give the big win.** 1 to 16 parse workers cut parse time from about 1340 s to about 320 s, roughly 4.2x, and total time by about 3.6x.
- **Download workers barely matter for this dataset.** At 16 parse workers, 1 to 64 download workers cut download time from 148 s to 127 s (about 20 s). This was expected: `pdfa-eng-wds` carries the PDF bytes inside the streamed rows, the rows are read from the stream one at a time in the main thread, and the download workers only hand over bytes that are already there. Download workers would matter much more for a dataset whose rows only link to files (one HTTP request per document), so the default of 64 is kept. Trying 32 or 128 download workers on this dataset would not be informative.
- **The output does not depend on the settings.** All four configurations returned the same documents, failures and duplicates, so the worker settings can be tuned purely for speed.
- **Download and parse take turns.** Total time is almost exactly download time plus parse time (for 64/16: 127 + 324 = 451 s of 462 s; the rest is startup such as opening the Hugging Face stream), because each batch is fully downloaded before it is parsed, and the parse workers are idle while the next batch downloads.

**Why 16 parse workers give about 4x, not 16x**

The expected speed-up on 16 cores was about 10-14x; the measured parse speed-up is about 4.2x. The likely reasons:

- **Waiting for the slowest document in every batch.** A batch has at most 256 documents. The next batch is only fetched after every document of the current one is done, so near the end of each batch most workers sit idle while the last, slowest PDFs finish. With 21 batches this happens 21 times.
- **Work in the main process is not parallel.** The measured parse time also includes duplicate checking and saving each kept document to disk, which happen in the main process one document at a time.
- **Moving data between processes.** Each document's result (its full text and metadata) is sent back from the worker process to the main process.
- **Parse workers are idle during downloads** (about 127 s per run), which is not counted in parse time but adds to the total.

**Second PDF parser: pypdfium2 (same 5000 streamed documents)**

- The question: how much faster is the run with pypdfium2 instead of pypdf, on exactly the same documents and settings?
- Same 5000 documents streamed from `pixparse/pdfa-eng-wds`, same command and settings as `run.sh` (cache folder `outputs/` emptied before each run, 256 rows per batch, 120 s parse time limit, 0.90 threshold), plus `--pdf_parser pypdfium2` (pypdfium2 5.14.0). Only 1/1 and 64/16 were run, once each.
- Logs: `logs/log_5000_download1_parse1_pypdfium2.txt` and `logs/log_5000_download64_parse16_pypdfium2.txt`.

| Download workers / parse workers | Parser | Total time | Download time | Parse time | Parse time per page |
|---|---|---|---|---|---|
| 1 / 1 | pypdf (above) | 1754 s (29.2 min) | 406 s* | 1336 s | 31.6 ms |
| 1 / 1 | **pypdfium2** | **265 s (4.4 min)** | 124 s | **130 s** | **3.1 ms** |
| 64 / 16 | pypdf (above) | 462 s (7.7 min) | 127 s | 324 s | 7.7 ms |
| 64 / 16 | **pypdfium2** | **203 s (3.4 min)** | 117 s | **77 s** | **1.8 ms** |

\* The download outlier described above. Per-page times use the 42254 pages of these 5000 documents.

- **Same output as pypdf.** Both pypdfium2 runs read the same 5101 rows in 21 batches and returned the same result: 5000 documents kept, 94 parse failures, 7 duplicates, 42254 pages. The 94 failures are 84 encrypted PDFs and 10 rows detected as plain text; pypdfium2 recognizes the 6 AES-encrypted PDFs as encrypted, so all 84 get the same "encrypted PDF" reason (pypdf reported those 6 as needing the `cryptography` package).
- **Parsing is about 10x faster on one core** (130 s versus 1336 s) **and about 4.2x faster with 16 parse workers** (77 s versus 324 s). End to end, the best run went from 462 s to 203 s, about 2.3x.
- **Downloading is now the bottleneck.** At 64/16, download takes 117 s of the 203 s total and parsing 77 s.
- **16 parse workers help much less with pypdfium2** (130 s to 77 s, 1.7x). Parsing is now so fast that the work that is not parallel takes most of the parse time: duplicate checking and saving each document's JSON in the main process (these runs cache, like the pypdf runs), and waiting for the slowest document of each batch.

**Comparison with LangChain `PyPDFLoader` (6000 local PDFs)**

- The question: how does the engine compare with a standard loader on the same documents?
- Documents: the first 6000 rows of `pixparse/pdfa-eng-wds` (split `train`), saved once as 6000 PDF files (2.7 GB) in a local folder, so network speed does not affect either side. Both tools read the same folder.
- LangChain: `benchmarks/langchain/langchain.py` (run with `benchmarks/langchain/run_langchain.sh <folder>`) loads each file with `PyPDFLoader` (langchain-community 0.4.2) in one process, because `PyPDFLoader` has no parallelism of its own. A file that fails is counted and skipped. Log: `logs/log_langchain.txt`.
- The engine: `python -m doc_ingest --size 6000 --input_path <folder> --parse_workers 16`, caching off, all other settings default. Log: `logs/log_local_6000_parse16.txt`.
- Both use the same parser, pypdf 6.16, on the same machine as above. Each was run once.

| | LangChain `PyPDFLoader` | DocIngestEngine |
|---|---|---|
| Parse workers | 1 | 16 |
| Total time | 1512 s (25.2 min) | **389 s (6.5 min)**, 3.9x faster |
| Documents returned | 5959 (as 50131 per-page Documents) | 5890 |
| Pages | 50131 loaded | 49109 parsed |
| Pages per second | 33.2 | **126.3** |
| Time per page | 30.2 ms | **7.9 ms** |
| Failed / skipped | 41 failed | 101 skipped, 9 duplicates removed |

- **The speed-up comes from parallel parsing, not from a faster parser.** Both sides use pypdf. On one core the two are about the same: LangChain took 30.2 ms per page, and the engine's 1/1 streaming run above works out to about 31.6 ms per page (1336 s of parse time over the 42254 pages of those 5000 documents, counted in a later run). A 1-worker run on this local set was not done.
- **The engine's time includes more work**: text cleanup, metadata extraction, duplicate checking, and copying each raw file to its temporary folder.
- **Why the documents differ:**
  - The engine skips every encrypted PDF on purpose (93 files). pypdf can open many of them with an empty password, and LangChain does, so it returned about 54 documents the engine skipped. That also explains most of LangChain's roughly 1000 extra pages.
  - AES-encrypted PDFs need the `cryptography` package, which is not installed: LangChain failed on 39 of them, the engine on 7 (its own encryption check had already skipped the rest).
  - On 2 broken files (`LimitReachedError`, `KeyError: '/DescendantFonts'`) LangChain lost the whole file. The engine catches page extraction errors page by page and kept both documents.
  - Only the engine removes duplicates (9) and empty documents (1); LangChain returns them as ordinary documents.

**Resume speed (separate micro-benchmark)**

- Loading 1000 cached documents into the duplicate checker took 0.10 s when their saved MinHash signatures were reused, versus 1.49 s when the signatures were computed again from the text, about 15x faster. This is the work a resumed run does at startup for every cached document.

**Not measured yet**

- Peak memory use (the returned list holds every document's full text, which matters at 50k documents and more).
- A plain pypdf loop on the same documents (to show the pipeline's own overhead), a larger run (50k), the text quality of pypdf versus pypdfium2 (only speed and metadata were compared), and other loaders (LlamaIndex, unstructured) on the same set.
- Cheap experiments that follow from the results: a larger `--max_batch_rows` (for example 1024) to reduce the "wait for the slowest document" pauses, and overlapping the download of the next batch with parsing of the current one.

## 8. Repo Structure

```
DocIngestEngine/
├── README.md               this file
├── CLAUDE.md               project instructions and conventions (code style, environment, file layout)
├── pyproject.toml          package definition: name, Python version, the four dependencies, the optional pdfium extra, the doc-ingest command
├── run.sh                  benchmark/run script (see Usage)
├── .editorconfig           tabs everywhere, spaces only for YAML
├── .gitignore              keeps .env, config.py, logs/ and Python caches out of git
├── .claude/skills/         a git-commit helper used while developing with Claude Code
├── .vscode/settings.json   editor settings
├── benchmarks/
│   └── langchain/          LangChain PyPDFLoader baseline: langchain.py and run_langchain.sh (benchmark only, not a dependency)
├── src/
│   └── doc_ingest/         the package
│       ├── __init__.py         public API: ingest_documents, IngestResult, IngestError, Document, DownloadSettings, ProcessSettings, ParserSettings
│       ├── __main__.py         command line tool (python -m doc_ingest / doc-ingest)
│       ├── ingest.py           ingest_documents, IngestEngine (the run, step by step), IngestResult
│       ├── settings.py         DownloadSettings, ProcessSettings and ParserSettings, and every default value
│       ├── validate.py         all up-front checks of inputs, settings and the cache folder
│       ├── error.py            IngestError and describe_error
│       ├── schema.py           Pydantic output models: Document, Metadata, DocumentType
│       ├── dataset_config.py   builds the DatasetConfig; record content field and encoding
│       ├── dataset_local.py    local files, folders and JSONL/JSON containers
│       ├── dataset_hf.py       Hugging Face names, page URLs, first row, row count, file downloads
│       ├── document_type.py    document type from file extension or from the first bytes
│       ├── raw_data.py         RawDataFetcher: reads rows in batches, downloads/decodes, saves raw files
│       ├── parser.py           Parser base class, parser registry, parse_document (runs in the workers)
│       ├── text_cleanup.py     format-independent text cleanup
│       ├── metadata.py         generic metadata and helpers for property values
│       ├── dedup.py            Deduplicator: exact (hash) and near (MinHash/LSH) duplicates
│       ├── cache.py            saving/loading processed documents
│       ├── progress.py         Progress record; loading/saving progress.json
│       ├── summary.py          Summary counters and the run summary log
│       └── parsers/            one parser per format
│           ├── pdf.py              PyPdfParser and PyPdfium2Parser: native text PDFs (the only format implemented)
│           ├── scanned_pdf.py      placeholder: OCR for scanned/image PDFs
│           ├── docx.py             placeholder: Word documents
│           ├── pptx.py             placeholder: PowerPoint slides and speaker notes
│           ├── xlsx.py             placeholder: Excel workbooks
│           ├── csv.py              placeholder: CSV files
│           ├── html.py             placeholder: web pages
│           ├── md.py               placeholder: Markdown
│           └── txt.py              placeholder: plain text, logs, code files
├── tests/                  offline test suite (66 tests, unittest style, run with pytest or unittest)
│   ├── helpers.py              builds small PDFs in memory (normal, multi-page reports, encrypted) and writes test files
│   ├── test_validate.py        input, settings and cache folder checks
│   ├── test_dataset_config.py  dataset kinds, formats, names, sizes, content field/encoding, Hugging Face helpers, type detection
│   ├── test_raw_data.py        reading rows, per-document type and source, batch counts, resuming from a row count
│   ├── test_pdf.py             PDF parsing with both parsers (same output), properties, dates, page failures, parse_document failures, generic metadata
│   ├── test_text_cleanup.py    header/footer removal, whitespace, icon characters, page joining
│   ├── test_dedup.py           exact and near duplicates, cached documents, saved signature reuse
│   ├── test_cache_progress.py  processed document cache and progress files
│   └── test_ingest.py          full end-to-end runs, resuming from the cache, continuing after rows read, caching off
├── logs/                   benchmark logs written by run.sh (not in git)
└── outputs/                run.sh's cache folder (raw, processed, progress; deleted before every run; not committed)
```

Notes:

- The package code is about 4000 lines including the tests, most of it docstrings and explicit step-by-step code.
- The placeholder parser files are empty; they mark the formats planned next (see Work in Progress). Only `pdf` is registered as a parser.
- `logs/` is listed in `.gitignore`, so the benchmark logs referred to in the Performance Summary exist only locally; the numbers in this README are copied from them.
- `.env` (Hugging Face token) and `config.py` (local settings) are also git-ignored and never committed.

## 9. Known Issues & Work in Progress

**Known issues and limitations**

*Formats*

- **Only native text PDFs are parsed.** The other parser files in `parsers/` are empty placeholders, and only `pdf` is registered.
- **Unsupported formats are counted as parse failures, not as unsupported.** Type detection recognizes DOCX, PPTX, XLSX, CSV, HTML, Markdown and plain text, so such documents are downloaded, saved to `raw/` and sent to a parse worker, and only fail there ("Unknown doc_type"). In the benchmark this was 10 of the 94 parse failures (rows whose bytes were detected as plain text). They should really be skipped before downloading and counted under "unsupported type", with the parser registry as the single list of what is supported.
- **Scanned (image-only) PDFs** have no OCR yet; they produce no text and are skipped as "no text".
- **Encrypted PDFs are skipped.** AES-encrypted ones fail even earlier with "cryptography>=3.1 is required for AES algorithm" (6 in the benchmark), because pypdf needs the `cryptography` package just to open them; installing it would only change the reason, as they would then be skipped as encrypted. pypdfium2 recognizes them as encrypted directly.
- **Web URLs are not supported** as input, and web links inside records are rejected; only Hugging Face dataset pages and Hugging Face file links are accepted.

*Platform and process behavior*

- **The parse time limit only works on Linux/macOS.** It uses the Unix `SIGALRM` signal; on Windows `--parse_timeout_seconds` is accepted but silently has no effect, so one PDF that makes pypdf loop forever would hang its worker and the run. The alarm also cannot interrupt code stuck inside a C extension until control returns to Python (not a problem for pypdf, which is pure Python; with pypdfium2, which runs in C++, a page that hangs inside PDFium is only stopped once it returns, and the same would apply to a future OCR parser). A cross-platform fix would enforce the limit from the main process and restart the worker pool on a time-out, reusing the existing crash recovery.
- **Warnings from parse worker processes bypass the caller's logging setup.** Spawned workers do not inherit the application's logging configuration, so their warnings (for example "Parse failed for document ... : <reason>") are written to standard error by Python's fallback handler. Silencing the `doc_ingest` logger in your application silences everything except these. Each parse failure is also reported twice: once by the worker with the reason, once by the main process as "Skipping document ...: parse failed".
- **The command line tool ends with `os._exit(0)`.** The Hugging Face `datasets`/`fsspec` libraries leave a background thread running after streaming, which crashes normal interpreter shutdown ("Fatal Python error: PyGILState_Release", upstream issue huggingface/datasets#7357). Skipping normal shutdown avoids it, but it also means `main()` cannot be called from a test in the same process; the command line tool has no automated tests of its own yet.
- `--help` shows the program as `__main__.py` instead of `python -m doc_ingest`.

*Performance*

- **Parallel parsing scales sub-linearly**: 16 parse workers gave about 4.2x, not the 10-14x expected. Every batch waits for its slowest document before the next batch is fetched, duplicate checking and saving happen in the main process one document at a time, and downloading and parsing take turns instead of overlapping (see Performance Summary).
- **All returned documents are held in memory** until the run ends, and the caller only gets them at the end. Fine at thousands of documents; at hundreds of thousands or millions memory becomes the limit.
- **Resuming deep into a Hugging Face stream may be slow**: the rows read by earlier runs are skipped on the stream, and skipping a streamed dataset most likely still reads through those rows.
- **A local folder is walked twice** when the dataset is described (once for its format, once to count its documents).
- **The cache folder only grows**: `raw/` keeps a copy of every downloaded document, which matters for large runs. There is no cleanup option; delete the dataset's folder to start over. With caching off, the temporary folder still holds every raw document of the run until the run ends.

*Correctness and robustness edge cases*

- **Errors while loading the cache are hidden as skips.** When a cached document cannot be added to the duplicate checker, it is logged as a warning and marked as skipped, and the run continues. That is the intended behavior for a damaged file, but it also means a bug in that step would make documents silently drop out of the cache instead of failing loudly. (During development, a MinHash rebuild error was caught by the unit tests but did not stop an end-to-end run for this reason.)
- **Changing the shingle size would silently reuse old signatures.** Saved MinHash signatures are only checked for their length (128 values); a different shingle size cannot be detected, so it would require clearing the processed cache.
- **Near-duplicate detection is probabilistic.** MinHash/LSH estimates similarity; a pair just around the threshold can occasionally be missed or caught. Duplicates are also only detected within one dataset folder, not across different datasets.
- **Header/footer removal is a heuristic.** Documents with fewer than 3 pages are never checked, only the first and last line of each page are considered, and a genuine line that happens to start or end most pages would be removed.
- **Dataset size can be unknown** (-1) for JSONL/JSON files and for Hugging Face datasets that do not publish a row count, and whether a Hugging Face split exists is only found out when the dataset is opened.

*Code and repository housekeeping*

- Some type hints are loose (for example functions declared to return just `tuple` or `list`, and parameters such as `path` without a type).
- A few unused imports remain (`re` in `raw_data.py`, `json` in `cache.py`, `hashlib` and `time` in `parser.py`).
- `run.sh` log file names only contain the size and the two worker counts, so runs that differ only in another setting overwrite each other's log.
- `logs/` is git-ignored, so the benchmark logs are only local; `outputs/` is not git-ignored, so it shows up as an untracked folder.
- Each benchmark configuration was run once, and the 1/1 download time looks like a network outlier that was not rerun.

**Work in progress / planned**

- **More formats**: parsers for DOCX, PPTX (slides and speaker notes), XLSX (multi-sheet workbooks), CSV, HTML, Markdown and plain text/log/code files, added one at a time, and OCR for scanned PDFs. Each one only needs its parser class and a registry entry; cleanup, metadata, dedup, caching and failure handling are shared.
- **Count unsupported types correctly** once formats are being added: skip types without a registered parser before downloading them.
- **A batch-by-batch API (`lazy_ingest`)**, planned after the RAG project that will use this library: instead of one list at the end, return one `IngestResult` per batch (that batch's kept documents and that batch's summary, for example 498 documents from a 500-row batch), saving progress before each batch is handed over so stopping early is safe. It will be a separate function next to `ingest_documents`, leaving the current API unchanged.
- **Windows support for the parse time limit**, or at least a clear warning when it cannot be enforced.
- **Benchmark plan**: add peak memory to the measurements, benchmark a plain pypdf loop on the same documents to show the pipeline's overhead, run at 50k documents with the best setting (memory, disk, resume after an interruption, Hugging Face throttling), compare the extracted text of pypdf and pypdfium2 (their speed is measured), and compare with other loaders (LlamaIndex `SimpleDirectoryReader`, `unstructured`) on the same set, as was done for LangChain `PyPDFLoader`.
- **Performance experiments** suggested by the results: a larger `max_batch_rows` (for example 1024) to reduce the waiting at the end of each batch, and overlapping the download of the next batch with the parsing of the current one.
- **A RAG project built on top of this library**, where cleaned, deduplicated documents with source metadata feed chunking, embedding and retrieval. Its results will show which ingestion settings (for example the near-duplicate threshold) matter for answer quality.

## 10. License
