# DocIngestEngine

## Notes for writing this README later

### Calling the library needs the `__main__` guard (top-level scripts only)

```python
from doc_ingest.ingest import ingest_documents

if __name__ == "__main__":
	ingest_result = ingest_documents(100, "pixparse/pdfa-eng-wds")
	documents = ingest_result.documents
	summary = ingest_result.summary
```

- Needed only when the call sits at the top level of the script being run (`python my_script.py`).
- Not needed when the call is inside a function in an imported module (web app handler, pipeline step), or with `python -c`. Jupyter should also work (not tested yet).
- Why: parse workers are started with `multiprocessing.get_context("spawn")` in `ingest.py`. Each worker is a fresh Python that re-loads the script being run, so unguarded top-level code runs again inside the worker and fails with `RuntimeError: ... bootstrapping phase` and `BrokenProcessPool`.
- Why spawn and not fork: Hugging Face streaming runs background threads, and forking a process with threads can deadlock. Threads instead of processes would avoid the guard but parse on one core (pypdf is pure Python).
- Same requirement as PyTorch's DataLoader and Python's own `multiprocessing` docs.
