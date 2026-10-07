"""
dedup.py

Finds exact duplicates (same content hash) and near-duplicates (MinHash
signatures with LSH) among the documents kept in a run.
"""

import datasketch
from doc_ingest.schema import Document
from doc_ingest.settings import DEFAULT_DEDUP_THRESHOLD

NUM_PERM = 128
_SHINGLE_SIZE = 5

class Deduplicator:
	"""
	Holds the content hashes and MinHash LSH index of every document kept
	so far in a run, so each new document can be checked against all of
	them.
	"""

	def __init__(self, threshold: float = DEFAULT_DEDUP_THRESHOLD):
		"""
		Input: threshold - Jaccard similarity at or above which two
			documents are near-duplicates (see make_lsh_index).
		Output: none.
		What it does: starts with no seen content hashes and an empty LSH
			index.
		"""
		self.seen_content_hashes = set()
		self.lsh_index = self.make_lsh_index(threshold)

	def make_minhash(self, shingles: set) -> datasketch.MinHash:
		"""
		Input: shingles - a document's shingle set (see make_shingles).
		Output: the MinHash signature of the shingles.
		What it does: builds a MinHash signature summarizing shingles, using
			NUM_PERM hash permutations. A MinHash signature is a fixed-size
			approximation of a shingle set that preserves Jaccard
			similarity: comparing two signatures estimates the Jaccard
			similarity of the two original shingle sets without needing to
			store or scan either set directly.
		"""
		minhash = datasketch.MinHash(num_perm=NUM_PERM)
		for shingle in shingles:
			shingle_bytes = shingle.encode("utf-8")
			minhash.update(shingle_bytes)
		return minhash

	def make_lsh_index(self, threshold: float) -> datasketch.MinHashLSH:
		"""
		Input: threshold - the Jaccard similarity at or above which two
			documents are considered near-duplicates.
		Output: a new, empty MinHashLSH index configured for NUM_PERM-sized
			MinHash signatures and threshold.
		What it does: passes threshold straight through to MinHashLSH,
			which picks banding parameters internally so that pairs at or
			above threshold are very likely to be found as candidates, and
			pairs below it are increasingly unlikely to be.
		"""
		return datasketch.MinHashLSH(threshold=threshold, num_perm=NUM_PERM)

	def make_shingles(self, text: str) -> set[str]:
		"""
		Input: text - a document's extracted text content.
		Output: the set of shingle strings.
		What it does: splits text into whitespace-separated words and builds
			the set of overlapping word n-grams (shingles) of length
			_SHINGLE_SIZE. Two documents can share many shingles, and so be
			near duplicates, even when their content_hash values differ.
		"""
		words = text.split()

		shingles = set()
		index = 0
		while index + _SHINGLE_SIZE <= len(words):
			shingle_words = words[index:index + _SHINGLE_SIZE]
			shingle = " ".join(shingle_words)
			shingles.add(shingle)
			index += 1

		return shingles

	def is_exact_duplicate(self, content_hash: str) -> bool:
		"""
		Input: content_hash - the content_hash of the document being
			checked.
		Output: True if content_hash was already seen, else False.
		What it does: checks whether a kept document has the same content
			hash, meaning this document is an exact duplicate of it.
		"""
		return content_hash in self.seen_content_hashes

	def is_near_duplicate(self, minhash: datasketch.MinHash) -> bool:
		"""
		Input: minhash - the MinHash signature (see make_minhash) of the
			document being checked.
		Output: True if the index returns any candidate match, else False.
		What it does: queries the LSH index for any kept document whose
			MinHash signature LSH estimates to be at or above the configured
			similarity threshold. Does not insert minhash into the index.
		"""
		candidate_doc_ids = self.lsh_index.query(minhash)
		return len(candidate_doc_ids) > 0

	def add(self, document: Document) -> None:
		"""
		Input: document - a Document already known to be kept.
		Output: none.
		What it does: records the document's content hash and MinHash
			without checking it. Used for documents loaded from the cache.
		"""
		self.seen_content_hashes.add(document.metadata.content_hash)
		shingles = self.make_shingles(document.text)
		if len(shingles) > 0:
			self.lsh_index.insert(document.id, self.make_minhash(shingles))

	def add_if_new(self, document: Document) -> bool:
		"""
		Input: document - a newly parsed Document.
		Output: True if the document was new and recorded, or False if it
			is a duplicate.
		What it does: checks the document against every kept document. If
			it is not an exact or near duplicate, records it as kept and
			stores its MinHash signature in
			document.metadata.minhash_signature.
		"""
		if self.is_exact_duplicate(document.metadata.content_hash):
			return False

		shingles = self.make_shingles(document.text)
		minhash = None
		if len(shingles) > 0:
			minhash = self.make_minhash(shingles)
			if self.is_near_duplicate(minhash):
				return False

		self.seen_content_hashes.add(document.metadata.content_hash)
		if minhash is not None:
			self.lsh_index.insert(document.id, minhash)
			self.store_minhash_signature(document, minhash)
		return True

	def store_minhash_signature(self, document: Document, minhash: datasketch.MinHash) -> None:
		"""
		Input: document - the Document whose signature is stored;
			minhash - that document's MinHash signature (see make_minhash).
		Output: none.
		What it does: copies the signature's NUM_PERM hash values into
			document.metadata.minhash_signature as plain Python ints, so
			they can be saved to JSON.
		"""
		signature_values = []
		for hash_value in minhash.hashvalues:
			signature_values.append(int(hash_value))
		document.metadata.minhash_signature = signature_values
