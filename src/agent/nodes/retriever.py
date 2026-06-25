"""Retriever node — reads full spec files + fetches project-doc candidates for re-ranking.

Spec (schema_docs): always read full file per level — no size threshold, no ChromaDB fallback.
  Rationale: spec is the source of truth for output format; any truncation risks wrong output.

Project docs: fetch top-N candidates (N = RERANK_CANDIDATES_K, default 12) with cosine scores
  so the downstream reranker_node can apply hybrid BM25 + semantic scoring before final selection.
  Skipped entirely when project has no documents.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage

from agent.rag import aretrieve_project_docs_with_score
from agent.state import AgentState

logger = logging.getLogger(__name__)

# ── Paths & config ───────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # dbflow-ai/
_DOCS_DIR = _PROJECT_ROOT / "docs"

# Number of project-doc candidates to fetch for re-ranking (3× the final top-k)
_RERANK_CANDIDATES_K = 12


def _read_full_specs(level: str) -> Optional[str]:
    """Read full model-schema.md + model.schema.json for *level*.

    Always returns full content — no size threshold.
    Returns None only if the level directory or files are missing.
    """
    level_dir = _DOCS_DIR / level
    if not level_dir.is_dir():
        logger.warning("Spec directory not found for level '%s': %s", level, level_dir)
        return None

    spec_files: List[Path] = []
    for name in ("model-schema.md", "model.schema.json"):
        f = level_dir / name
        if f.exists():
            spec_files.append(f)

    if not spec_files:
        logger.warning("No spec files found for level '%s'", level)
        return None

    sections: List[str] = []
    for f in spec_files:
        header = f"### {f.name}"
        content = f.read_text(encoding="utf-8")
        sections.append(f"{header}\n\n{content}")

    return "\n\n---\n\n".join(sections)


def _extract_last_message(state: AgentState) -> str:
    """Extract plain text from the last HumanMessage in state."""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            raw = msg.content
            if isinstance(raw, str):
                return raw
            if isinstance(raw, list):
                return " ".join(
                    part["text"] for part in raw
                    if isinstance(part, dict) and part.get("type") == "text"
                )
    return ""


async def retriever_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve spec docs (full) and project-doc candidates (with scores).

    Spec retrieval:
      - Always reads full spec files for the active level (no ChromaDB fallback).

    Project-doc retrieval:
      - Fetches top-N candidates with cosine scores.
      - Stored in ``project_docs_candidates`` for reranker_node to process.
      - Skipped (candidates = None) when no project_id is present.
    """
    level = state.get("current_level", "conceptual")

    last_message = _extract_last_message(state)

    # ── Spec: always full read, no fallback ──────────────────────────────
    retrieval_context = await asyncio.to_thread(_read_full_specs, level) or ""

    # ── Project docs: fetch candidates with scores for reranker ──────────
    project_docs_candidates = None
    project_id = state.get("project_id")
    if project_id:
        query = last_message or "database schema design"
        raw_results = await aretrieve_project_docs_with_score(
            query=query,
            project_id=project_id,
            k=_RERANK_CANDIDATES_K,
        )
        # Serialize to plain dicts so state remains JSON-serializable
        project_docs_candidates = [
            {
                "page_content": doc.page_content,
                "metadata": doc.metadata,
                "score": float(score),
            }
            for doc, score in raw_results
        ]

    return {
        "retrieval_context": retrieval_context,
        "project_docs_context": "",           # filled by reranker_node
        "project_docs_candidates": project_docs_candidates,
    }
