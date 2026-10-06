# Benchmark plan

Goal: show what this library adds on top of existing PDF parsers (pypdf,
pypdfium2) and loaders (LangChain, LlamaIndex, unstructured), with numbers.

## Rules for every run

- Same documents for every comparison (same folder, same `--size`).
- Read from a local copy of the dataset, so network speed does not skew
  parser numbers. Measure downloading separately, in one Hugging Face run.
- Empty output folder per run (`run.sh` does this); keep the logs.
- Compare `download_seconds` and `parse_seconds`, not only `total_seconds`
  (total includes one-time startup such as Hugging Face stream setup).
- Report pages per second, not only documents per second.

## Steps

1. **Test set**
   - Find a dataset with at least 50k usable PDFs (`d4rk3r/resumes-raw-pdf`
     has only ~1.9k rows, about a third image-only).
   - Download it once into a local folder.

2. **Measurements to add first**
   - Page count in the summary (for pages/second).
   - Peak memory (RAM). Needed for 50k: the returned dict keeps every
     document's full text in memory.

3. **pypdf**
   - Baseline: plain pypdf loop (open, extract text, nothing else), one core.
     Gives the parser's raw speed and the pipeline's overhead.
   - Parallelism at 5k: `./run.sh 1 1`, `./run.sh 64 1`, `./run.sh 1 16`,
     `./run.sh 64 16`.
   - Scale at 50k with the best setting only. Watch memory, disk (raw/ keeps
     every original file), resume after an interruption, Hugging Face throttling.

4. **pypdfium2**
   - Make the PDF parser selectable (pypdf or pypdfium2) behind the same API.
   - Repeat step 3 with pypdfium2.
   - Compare speed and text quality (diff the extracted text on a small sample).

5. **Other loaders, same 5k set**
   - LangChain `PyPDFLoader`, LlamaIndex `SimpleDirectoryReader`, `unstructured`.
   - Compare speed, and which features each lacks (multi-source input, mixed
     types, dedup, resume, cleanup, skip-and-continue, summary).
   - Keep them out of the library's dependencies (benchmark-only).

## Notes

- Expected parallel speedup on 16 cores is about 10-14x, not 16x: each batch
  waits for its slowest documents, and moving data between processes costs time.
- A batch of 256 documents split into pieces of 16 (`PARSE_DOC_COUNT`) gives
  exactly 16 pieces. More than 16 parse workers needs a bigger batch or
  smaller pieces.
- Claims must be defensible, e.g. "same parser, N times faster end to end on
  M cores", "X% overhead over a plain pypdf loop", "removed Y% duplicates".
  Never claim faster text extraction than the parser itself.
- Check competitor features against their current docs before publishing.
- Without `HF_TOKEN` (in `.env`), Hugging Face startup takes ~1 min and long
  runs may be throttled.
