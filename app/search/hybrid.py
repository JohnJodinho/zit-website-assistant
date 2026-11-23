from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.content.snapshot import ContentSnapshot

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "can",
    "do",
    "does",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "much",
    "of",
    "on",
    "please",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_key: str
    doc_key: str
    score: float
    text: str
    vector_score: float
    bm25_score: float


class InMemoryHybridSearch:
    def __init__(self, snapshot: ContentSnapshot) -> None:
        self.snapshot = snapshot
        self._documents = [chunk for chunk in snapshot.chunks]
        self._doc_freq: Counter[str] = Counter()
        self._doc_lengths: dict[str, int] = {}
        self._term_counts: dict[str, Counter[str]] = {}
        for chunk in self._documents:
            term_counts = Counter(_tokens(f"{chunk.embed_text or ''} {chunk.text} {chunk.doc_key}"))
            self._term_counts[chunk.chunk_key] = term_counts
            self._doc_lengths[chunk.chunk_key] = sum(term_counts.values())
            self._doc_freq.update(term_counts.keys())
        self.average_length = (
            sum(self._doc_lengths.values()) / len(self._doc_lengths) if self._doc_lengths else 1.0
        )

    def retrieve(
        self,
        query_vector: tuple[float, ...] | None,
        question: str,
        *,
        vector_top: int = 20,
        bm25_top: int = 20,
        rrf_k: int = 60,
        limit: int = 10,
    ) -> tuple[list[SearchHit], dict[str, object]]:
        vector_scores = self._vector_scores(query_vector)
        bm25_scores = self._bm25_scores(question)
        vector_ranked = sorted(
            (key for key, score in vector_scores.items() if score > 0),
            key=lambda key: vector_scores[key],
            reverse=True,
        )[:vector_top]
        bm25_ranked = sorted(
            (key for key, score in bm25_scores.items() if score > 0),
            key=lambda key: bm25_scores[key],
            reverse=True,
        )[:bm25_top]
        combined: dict[str, float] = {}
        vector_seen: dict[str, float] = {}
        bm25_seen: dict[str, float] = {}
        for rank, chunk_key in enumerate(vector_ranked, start=1):
            combined[chunk_key] = combined.get(chunk_key, 0.0) + 1.0 / (rrf_k + rank)
            vector_seen[chunk_key] = vector_scores.get(chunk_key, 0.0)
        for rank, chunk_key in enumerate(bm25_ranked, start=1):
            combined[chunk_key] = combined.get(chunk_key, 0.0) + 1.0 / (rrf_k + rank)
            bm25_seen[chunk_key] = bm25_scores.get(chunk_key, 0.0)
        keys = sorted(combined, key=lambda key: combined[key], reverse=True)[:limit]
        chunks = {chunk.chunk_key: chunk for chunk in self._documents}
        hits = [
            SearchHit(
                chunk_key=key,
                doc_key=chunks[key].doc_key,
                score=combined[key],
                text=chunks[key].text,
                vector_score=vector_seen.get(key, 0.0),
                bm25_score=bm25_seen.get(key, 0.0),
            )
            for key in keys
        ]
        gate: dict[str, object] = {
            "best_vector": max(vector_scores.values(), default=0.0),
            "best_bm25": max(bm25_scores.values(), default=0.0),
            "degraded": query_vector is None,
        }
        return hits, gate

    def _vector_scores(
        self,
        query_vector: tuple[float, ...] | None,
    ) -> dict[str, float]:
        if query_vector is None:
            return {chunk.chunk_key: 0.0 for chunk in self._documents}
        scores: dict[str, float] = {}
        for chunk in self._documents:
            if len(chunk.embedding) != len(query_vector):
                scores[chunk.chunk_key] = 0.0
                continue
            scores[chunk.chunk_key] = sum(
                left * right for left, right in zip(query_vector, chunk.embedding, strict=True)
            )
        return scores

    def _bm25_scores(self, question: str) -> dict[str, float]:
        query_terms = _tokens(question)
        query_counts = Counter(query_terms)
        scores: dict[str, float] = {}
        total_docs = len(self._documents) or 1
        query_weight = sum(
            frequency
            * (
                math.log(
                    1.0
                    + (total_docs - self._doc_freq.get(term, 0) + 0.5)
                    / (self._doc_freq.get(term, 0) + 0.5)
                )
            )
            * 2.2
            for term, frequency in query_counts.items()
        )
        for chunk in self._documents:
            score = 0.0
            term_counts = self._term_counts[chunk.chunk_key]
            length = self._doc_lengths[chunk.chunk_key]
            for term, query_frequency in query_counts.items():
                document_frequency = self._doc_freq.get(term, 0)
                if document_frequency == 0:
                    continue
                frequency = term_counts.get(term, 0)
                if frequency == 0:
                    continue
                inverse_document_frequency = math.log(
                    1.0 + (total_docs - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                normalized_frequency = (
                    frequency
                    * 2.2
                    / (frequency + 1.2 * (0.25 + 0.75 * length / self.average_length))
                )
                score += query_frequency * inverse_document_frequency * normalized_frequency
            scores[chunk.chunk_key] = score / query_weight if query_weight else 0.0
        return scores


def _tokens(value: str) -> list[str]:
    return [token for token in _TOKEN.findall(value.lower()) if token not in _STOPWORDS]
