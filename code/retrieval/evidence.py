"""BM25 retrieval with evidence grading for citation-safe grounding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from issue_parser import combined_user_text, parse_issue
from paths import REPO_ROOT
from safety import classify_ticket
from retrieval.bm25 import BM25Index
from retrieval.indexer import build_index, verify_index_paths
from retrieval.models import CorpusChunk, CorpusIndex
from retrieval.query import RetrievalQuery, build_retrieval_query
from retrieval.ranking import domain_boost, path_penalty, specificity_boost
from ticket_categories import is_hub_path
from retrieval.tokenize import tokenize

EvidenceGrade = str  # strong | weak | conflicting | insufficient

STRONG_SCORE_THRESHOLD = 7.5
WEAK_SCORE_THRESHOLD = 2.0
CONFLICT_SCORE_MARGIN = 1.25

_CACHE: tuple[CorpusIndex, BM25Index] | None = None


def _get_cached(corpus: CorpusIndex | None, bm25: BM25Index | None) -> tuple[CorpusIndex, BM25Index]:
    global _CACHE
    if corpus is not None and bm25 is not None:
        return corpus, bm25
    if _CACHE is None:
        built = corpus or build_index()
        _CACHE = (built, BM25Index.from_corpus(built))
    return _CACHE


@dataclass(frozen=True)
class EvidenceItem:
    path: str
    title: str
    score: float
    snippet: str
    domain_hints: tuple[str, ...]
    chunk_id: str


@dataclass(frozen=True)
class RetrievalResult:
    query: RetrievalQuery
    items: tuple[EvidenceItem, ...]
    overall_grade: EvidenceGrade
    notes: tuple[str, ...]


def _snippet_for_chunk(chunk: CorpusChunk, query_terms: list[str], max_len: int = 240) -> str:
    if not chunk.body.strip():
        return chunk.title[:max_len]

    query_set = set(query_terms)
    best_para = ""
    best_hits = -1
    for para in chunk.body.split("\n\n"):
        plain = para.strip()
        if not plain or plain.startswith("#"):
            continue
        hits = sum(1 for t in query_set if t in plain.lower())
        if hits > best_hits:
            best_hits = hits
            best_para = plain

    text = best_para or chunk.body.strip().split("\n", 1)[0]
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _aggregate_by_path(
    scored: list[tuple[float, CorpusChunk]],
) -> list[tuple[float, CorpusChunk]]:
    best: dict[str, tuple[float, CorpusChunk]] = {}
    for score, chunk in scored:
        prev = best.get(chunk.path)
        if prev is None or score > prev[0]:
            best[chunk.path] = (score, chunk)
    aggregated = list(best.values())
    aggregated.sort(key=lambda item: (-item[0], item[1].path, item[1].chunk_id))
    return aggregated


def grade_evidence(
    items: list[EvidenceItem],
    query: RetrievalQuery,
) -> tuple[EvidenceGrade, tuple[str, ...]]:
    if not items or items[0].score < WEAK_SCORE_THRESHOLD:
        return "insufficient", ("No corpus chunk exceeded minimum BM25 threshold.",)

    notes: list[str] = []
    top = items[0]
    second_score = items[1].score if len(items) > 1 else 0.0

    top_domains = {d for d in top.domain_hints if d != "unknown"}
    runner_domains: set[str] = set()
    if len(items) > 1:
        runner_domains = {d for d in items[1].domain_hints if d != "unknown"}

    text_domains = {d for d, _ in query.text_domain_scores}
    if (
        top_domains
        and runner_domains
        and not top_domains.intersection(runner_domains)
        and abs(top.score - second_score) <= CONFLICT_SCORE_MARGIN
    ):
        notes.append("Top hits span different product domains with similar scores.")
        return "conflicting", tuple(notes)

    if top.path.endswith("/index.md") or Path(top.path).name == "index.md":
        notes.append("Best match is a broad index page; prefer a specific article.")
        if top.score < STRONG_SCORE_THRESHOLD:
            return "weak", tuple(notes)

    if top.score >= STRONG_SCORE_THRESHOLD:
        if text_domains and top_domains and text_domains.intersection(top_domains):
            notes.append("Strong lexical match aligned with text-inferred domain.")
        else:
            notes.append("Strong lexical match.")
        return "strong", tuple(notes)

    notes.append("Evidence present but below strong confidence threshold.")
    return "weak", tuple(notes)


def retrieve_evidence(
    *,
    issue: str,
    subject: str = "",
    company: str = "",
    index: CorpusIndex | None = None,
    bm25: BM25Index | None = None,
    top_k: int = 5,
) -> RetrievalResult:
    """
    Retrieve top corpus evidence with BM25, domain-aware boosts, and grading.

    All returned paths are verified to exist under the repository root.
    """
    corpus, bm25_index = _get_cached(index, bm25)
    parsed = parse_issue(issue)
    raw_ticket_text = "\n".join(
        p for p in (subject, combined_user_text(parsed), parsed.raw if parsed.parse_error else "") if p
    )
    safety = classify_ticket(raw_ticket_text)
    query = build_retrieval_query(issue=issue, subject=subject, company=company)
    if safety.is_adversarial:
        return RetrievalResult(
            query=query,
            items=(),
            overall_grade="insufficient",
            notes=("Adversarial patterns detected; corpus retrieval skipped.",),
        )

    query_terms = list(query.tokens)

    scored: list[tuple[float, CorpusChunk]] = []
    for idx, chunk in enumerate(corpus.chunks):
        raw = bm25_index.score_chunk(query_terms, idx)
        if raw <= 0:
            continue
        adjusted = (
            raw
            * path_penalty(chunk.path)
            * domain_boost(chunk, query)
            * specificity_boost(chunk)
        )
        if adjusted > 0:
            scored.append((adjusted, chunk))

    aggregated = _aggregate_by_path(scored)
    items: list[EvidenceItem] = []
    for score, chunk in aggregated[:top_k]:
        if not (REPO_ROOT / chunk.path).is_file():
            continue
        items.append(
            EvidenceItem(
                path=chunk.path,
                title=chunk.title or Path(chunk.path).stem,
                score=round(score, 4),
                snippet=_snippet_for_chunk(chunk, query_terms),
                domain_hints=chunk.domain_hints,
                chunk_id=chunk.chunk_id,
            )
        )

    grade, notes = grade_evidence(items, query)
    return RetrievalResult(
        query=query,
        items=tuple(items),
        overall_grade=grade,
        notes=notes,
    )


def source_document_paths(result: RetrievalResult, *, exclude_hubs: bool = False) -> str:
    """Pipe-separated unique paths for output CSV (existing files only)."""
    seen: set[str] = set()
    articles: list[str] = []
    hubs: list[str] = []

    for item in result.items:
        if item.path in seen:
            continue
        if not (REPO_ROOT / item.path).is_file():
            continue
        seen.add(item.path)
        if is_hub_path(item.path):
            hubs.append(item.path)
        else:
            articles.append(item.path)

    if exclude_hubs and articles:
        return "|".join(articles)
    return "|".join(articles + hubs)
