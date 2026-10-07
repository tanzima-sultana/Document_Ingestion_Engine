# Benchmark plan

Goal: show what this library adds on top of existing PDF parsers (pypdf,
pypdfium2) and loaders (LangChain, LlamaIndex, unstructured), with numbers.

## Rules for every run

- Same documents for every comparison (same folder, same `--size`).
- Read from a local copy of the dataset, so network speed does not skew
  parser numbers. Streaming is measured separately, in step 3.
- Empty output folder per run (`run.sh` does this); keep the logs.
- Compare `download_seconds` and `parse_seconds`, not only `total_seconds`
  (total includes one-time startup such as Hugging Face stream setup).
- Report pages per second, not only documents per second.

## Steps

1. **Test set**
   - Dataset: `pixparse/pdfa-eng-wds` (~2.16M English text PDFs, not gated;
     `d4rk3r/resumes-raw-pdf` had only ~1.9k rows, about a third image-only).
   - Download it once into a local folder. The local loader cannot read
     `.tar` shards, so extract the `.pdf` files into a folder.

2. **Measurements to add first**
   - Page count in the summary (for pages/second).
   - Peak memory (RAM). Needed for 50k: the returned list keeps every
     document's full text in memory.

3. **Streaming + parallelism at 5k (Hugging Face)**
   - Stream the same 5k from `pixparse/pdfa-eng-wds` in every run; `run.sh`
     deletes raw, processed and progress before each run.
   - Runs: `./run.sh 1 1`, `./run.sh 64 1`, `./run.sh 1 16`, `./run.sh 64 16`.
   - `1 vs 64` download workers: do download threads help streaming?
     Expected no: rows are read from the stream one at a time in the main
     thread (`raw_data.py` `next(row_iterator)`); download workers only run
     `decode_raw_bytes`, which for this dataset just hands over bytes
     already in the row. Kept to have data backing this.
   - `1 vs 16` parse workers: how much parallel parsing helps.
   - Check `rows_read` and skip counts match across runs (same 5k).
   - Compare `download_seconds` and `parse_seconds` separately. Download and
     parse take turns per batch, so total = download + parse.
   - Network noise: rerun a pair if `download_seconds` differ by >10-20%.

4. **pypdf**
   - Baseline: plain pypdf loop (open, extract text, nothing else), one core.
     Gives the parser's raw speed and the pipeline's overhead.
   - Parallelism at 5k: `./run.sh 1 1`, `./run.sh 64 1`, `./run.sh 1 16`,
     `./run.sh 64 16`.
   - Scale at 50k with the best setting only. Watch memory, disk (raw/ keeps
     every original file), resume after an interruption, Hugging Face throttling.

5. **pypdfium2**
   - Make the PDF parser selectable (pypdf or pypdfium2) behind the same API.
   - Repeat step 4 with pypdfium2.
   - Compare speed and text quality (diff the extracted text on a small sample).

6. **Other loaders, same 5k set**
   - LangChain `PyPDFLoader`, LlamaIndex `SimpleDirectoryReader`, `unstructured`.
   - Compare speed, and which features each lacks (multi-source input, mixed
     types, dedup, resume, cleanup, skip-and-continue, summary).
   - Keep them out of the library's dependencies (benchmark-only).

## Notes

- Expected parallel speedup on 16 cores is about 10-14x, not 16x: each batch
  waits for its slowest documents, and moving data between processes costs time.
- Documents are sent to parse workers one at a time (so a worker that dies
  costs only one document), 256 per batch.
- Claims must be defensible, e.g. "same parser, N times faster end to end on
  M cores", "X% overhead over a plain pypdf loop", "removed Y% duplicates".
  Never claim faster text extraction than the parser itself.
- Check competitor features against their current docs before publishing.
- Without `HF_TOKEN` (in `.env`), Hugging Face startup takes ~1 min and long
  runs may be throttled.
