"""Re-ranker node — hybrid BM25 + semantic scoring for project_docs candidates.

Runs after retriever_node for all schema intents (create / edit).  Takes the raw
candidates (with cosine scores) stored by the
retriever and produces a ranked ``project_docs_context`` for the LLM prompt.

Scoring:
    final_score = 0.6 × semantic_score + 0.4 × bm25_score_normalized

No external ranking library needed — BM25 is computed inline over the
candidate texts using the user's last message as the query.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, List

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

from agent.rag import format_project_docs_context
from agent.state import AgentState

logger = logging.getLogger(__name__)

_RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "4"))
_SEMANTIC_WEIGHT = 0.6
_BM25_WEIGHT = 0.4

# BM25 hyper-params (standard values)
_BM25_K1 = 1.5
_BM25_B = 0.75
# Empirical cap for normalising BM25 raw score to [0, 1]
_BM25_NORM_CAP = 3.0


def _tokenize(text: str) -> List[str]:
    return text.lower().split()


def _bm25_score(query_tokens: List[str], doc_tokens: List[str], avg_dl: float) -> float:
    """Compute a BM25 score for one document against a query.

    Returns a non-negative float; higher = more relevant.
    IDF is simplified (per-document binary presence) since we have no corpus
    statistics — this is intentional to keep it dependency-free.
    """
    if not query_tokens or not doc_tokens:
        return 0.0

    doc_len = len(doc_tokens)
    score = 0.0
    for token in query_tokens:
        tf = doc_tokens.count(token)
        if tf == 0:
            continue
        # Simplified IDF: log(2) ≈ 0.693 for a token present in 1 of 1 doc
        idf = math.log(2.0)
        tf_norm = (tf * (_BM25_K1 + 1)) / (
            tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_len / max(avg_dl, 1))
        )
        score += idf * tf_norm

    return score / max(len(query_tokens), 1)


def _extract_last_message(state: AgentState) -> str:
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            raw = msg.content
            if isinstance(raw, str):
                return raw
            if isinstance(raw, list):
                return " ".join(
                    p["text"] for p in raw
                    if isinstance(p, dict) and p.get("type") == "text"
                )
    return ""


async def reranker_node(state: AgentState) -> Dict[str, Any]:
    """Re-rank project_docs candidates using hybrid scoring and emit project_docs_context.

    If no candidates are present (project has no docs), immediately returns an
    empty context without any computation.
    """
    candidates = state.get("project_docs_candidates")
    if not candidates:
        return {
            "project_docs_context": "",
            "project_docs_candidates": [],
        }

    query = _extract_last_message(state) or "database schema design"
    query_tokens = _tokenize(query)

    # Pre-tokenise all docs once
    doc_token_lists = [_tokenize(c["page_content"]) for c in candidates]
    avg_dl = sum(len(t) for t in doc_token_lists) / len(doc_token_lists)

    scored: List[Dict[str, Any]] = []
    for candidate, doc_tokens in zip(candidates, doc_token_lists):
        # Cosine score from ChromaDB is already in roughly [0, 1] for cosine similarity
        semantic = max(0.0, float(candidate["score"]))

        bm25_raw = _bm25_score(query_tokens, doc_tokens, avg_dl)
        bm25_norm = min(bm25_raw / _BM25_NORM_CAP, 1.0)

        final = _SEMANTIC_WEIGHT * semantic + _BM25_WEIGHT * bm25_norm
        scored.append({**candidate, "rerank_score": round(final, 4)})

    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    top_k = scored[:_RERANK_TOP_K]

    logger.debug(
        "Re-ranked %d candidates → top-%d scores: %s",
        len(candidates),
        _RERANK_TOP_K,
        [c["rerank_score"] for c in top_k],
    )

    docs = [
        Document(
            page_content=c["page_content"],
            metadata={**c["metadata"], "rerank_score": c["rerank_score"]},
        )
        for c in top_k
    ]

    return {
        "project_docs_context": format_project_docs_context(docs),
        "project_docs_candidates": [],  # clear after use — no longer needed in state
    }
