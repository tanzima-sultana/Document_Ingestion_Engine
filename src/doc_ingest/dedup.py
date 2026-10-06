"""
dedup.py
"""

import datasketch
from doc_ingest.schema import Document

NUM_PERM = 128
_SHINGLE_SIZE = 5

class Deduplicator:
	"""
	Holds the content hashes and MinHash LSH index of every document kept
	so far in a run, so each new document can be checked against all of
	them.
	"""

	def __init__(self, threshold: float = 0.90):
		"""
		threshold: Jaccard similarity at or above which two documents are
			near-duplicates (see make_lsh_index).

		Starts with no seen content hashes and an empty LSH index.

		Returns nothing.
		"""
		self.seen_content_hashes = set()
		self.lsh_index = self.make_lsh_index(threshold)

	def make_minhash(self, shingles: set) -> datasketch.MinHash:
		"""
		shingles: a document's shingle set (see make_shingles).

		Builds a MinHash signature summarizing shingles, using NUM_PERM hash
		permutations. A MinHash signature is a fixed-size approximation of a
		shingle set that preserves Jaccard similarity: comparing two
		signatures estimates the Jaccard similarity of the two original
		shingle sets without needing to store or scan either set directly.

		Returns the MinHash signature.
		"""
		minhash = datasketch.MinHash(num_perm=NUM_PERM)
		for shingle in shingles:
			shingle_bytes = shingle.encode("utf-8")
			minhash.update(shingle_bytes)
		return minhash

	def make_lsh_index(self, threshold: float) -> datasketch.MinHashLSH:
		"""
		threshold: the Jaccard similarity at or above which two documents
			are considered near-duplicates. Passed straight through to
			MinHashLSH, which picks banding parameters internally so that
			pairs at or above threshold are very likely to be found as
			candidates, and pairs below it are increasingly unlikely to be.

		Returns a new, empty MinHashLSH index configured for NUM_PERM-sized
		MinHash signatures and threshold.
		"""
		return datasketch.MinHashLSH(threshold=threshold, num_perm=NUM_PERM)

	def make_shingles(self, text: str) -> set[str]:
		"""
		text: a document's extracted text content.

		Splits text into whitespace-separated words and builds the set of
		overlapping word n-grams (shingles) of length _SHINGLE_SIZE. Two
		documents can share many shingles, and so be near duplicates, even
		when their content_hash values differ.

		Returns the set of shingle strings.
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
		content_hash: the content_hash of the document being checked.

		Returns True if content_hash was already seen (the text is an exact
		duplicate of a kept document), else False.
		"""
		return content_hash in self.seen_content_hashes

	def is_near_duplicate(self, minhash: datasketch.MinHash) -> bool:
		"""
		minhash: the MinHash signature (see make_minhash) of the document
			being checked.

		Queries the LSH index for any kept document whose MinHash signature
		LSH estimates to be at or above the configured similarity
		threshold. Does not insert minhash into the index.

		Returns True if the index returns any candidate match, else False.
		"""
		candidate_doc_ids = self.lsh_index.query(minhash)
		return len(candidate_doc_ids) > 0

	def add(self, document: Document) -> None:
		"""
		document: a Document already known to be kept.

		Records the document's content hash and MinHash without checking
		it. Used for documents loaded from disk.

		Returns nothing.
		"""
		self.seen_content_hashes.add(document.metadata.content_hash)
		shingles = self.make_shingles(document.text)
		if len(shingles) > 0:
			self.lsh_index.insert(document.id, self.make_minhash(shingles))

	def add_if_new(self, document: Document) -> bool:
		"""
		document: a newly parsed Document.

		Checks the document against every kept document. If it is not an
		exact or near duplicate, records it as kept and stores its MinHash
		signature in document.metadata.minhash_signature.

		Returns True if the document was new and recorded, or False if it
		is a duplicate.
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
		document: the Document whose signature is stored.
		minhash: that document's MinHash signature (see make_minhash).

		Copies the signature's NUM_PERM hash values into
		document.metadata.minhash_signature as plain Python ints, so they
		can be saved to JSON.

		Returns nothing.
		"""
		signature_values = []
		for hash_value in minhash.hashvalues:
			signature_values.append(int(hash_value))
		document.metadata.minhash_signature = signature_values
