"""Okapi BM25 scoring over corpus chunks (deterministic, in-memory)."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from retrieval.models import CorpusIndex
from retrieval.tokenize import counter_from_tokens, tokenize_weighted_fields

# Robertson/Spark Jones BM25 parameters (fixed for reproducibility).
K1 = 1.5
B = 0.75


@dataclass
class BM25Index:
    """Precomputed corpus statistics for BM25."""

    chunk_term_freqs: list[Counter[str]]
    chunk_lengths: list[int]
    avg_doc_length: float
    doc_freq: Counter[str]
    num_docs: int
    idf: dict[str, float]

    @classmethod
    def from_corpus(cls, corpus: CorpusIndex) -> BM25Index:
        chunk_term_freqs: list[Counter[str]] = []
        chunk_lengths: list[int] = []
        doc_freq: Counter[str] = Counter()

        for chunk in corpus.chunks:
            tokens = tokenize_weighted_fields(
                title=chunk.title,
                headings=" ".join(chunk.headings),
                body=chunk.body,
            )
            tf = counter_from_tokens(tokens)
            chunk_term_freqs.append(tf)
            chunk_lengths.append(len(tokens))
            for term in tf:
                doc_freq[term] += 1

        num_docs = max(len(chunk_term_freqs), 1)
        avg_len = sum(chunk_lengths) / num_docs if chunk_lengths else 1.0
        idf = {
            term: math.log((num_docs - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in doc_freq.items()
        }

        return cls(
            chunk_term_freqs=chunk_term_freqs,
            chunk_lengths=chunk_lengths,
            avg_doc_length=avg_len,
            doc_freq=doc_freq,
            num_docs=num_docs,
            idf=idf,
        )

    def score_chunk(self, query_terms: list[str], chunk_index: int) -> float:
        if not query_terms or chunk_index >= len(self.chunk_term_freqs):
            return 0.0

        tf_map = self.chunk_term_freqs[chunk_index]
        doc_len = self.chunk_lengths[chunk_index]
        norm = K1 * (1.0 - B + B * (doc_len / self.avg_doc_length))
        total = 0.0

        seen: set[str] = set()
        for term in query_terms:
            if term in seen:
                continue
            seen.add(term)
            if term not in self.idf:
                continue
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            numerator = tf * (K1 + 1.0)
            denominator = tf + norm
            total += self.idf[term] * (numerator / denominator)

        return total
