"""Retriever node — hybrid: read full spec files when small, fallback to RAG.

For each schema level the spec files (model-schema.md + diagram-schema.md) are
tiny (~5 KB).  Reading them in full guarantees the LLM sees 100 % of the format
rules.  If specs ever grow beyond a configurable threshold, we fall back to
ChromaDB RAG retrieval automatically.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage

from agent.models import UserIntent
from agent.rag import aretrieve, format_retrieved_context
from agent.state import AgentState

# ── Paths & config ───────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # dbflow-ai/
_DOCS_DIR = _PROJECT_ROOT / "docs"

# If total spec size exceeds this, fall back to RAG chunked retrieval
_FULL_READ_THRESHOLD_BYTES = 30_000  # 30 KB


def _read_full_specs(level: str) -> str | None:
    """Read full model-schema.md + diagram-schema.md for *level*.

    Returns the combined text if total size is below the threshold,
    otherwise returns ``None`` to signal that RAG should be used.
    """
    level_dir = _DOCS_DIR / level
    if not level_dir.is_dir():
        return None

    spec_files: List[Path] = []
    for name in ("model-schema.md", "model.schema.json"):
        f = level_dir / name
        if f.exists():
            spec_files.append(f)

    if not spec_files:
        return None

    total_size = sum(f.stat().st_size for f in spec_files)
    if total_size > _FULL_READ_THRESHOLD_BYTES:
        return None  # too large → fall back to RAG

    sections: List[str] = []
    for f in spec_files:
        header = f"### {f.name}"
        content = f.read_text(encoding="utf-8")
        sections.append(f"{header}\n\n{content}")

    return "\n\n---\n\n".join(sections)


def _pick_filters(state: AgentState) -> dict:
    """Determine which doc_type / level to filter by based on intent + current_level."""
    level = state.get("current_level", "conceptual")
    intent = state.get("user_intent", "create")
    return {"level": level, "doc_type": None}


async def retriever_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve schema specification docs — hybrid strategy.

    For forward/reverse engineering, fetches specs for the **target level**
    (where the output will land), not the source level.
    For create/edit, fetches specs for the current level.

    1. Try reading the full spec files for the level.
       If total size < 30 KB → use the full text (guarantees 100 % coverage).
    2. If files are too large or missing → fall back to ChromaDB RAG.
    """
    intent = state.get("user_intent", "create")
    # For engineering intents, retrieve spec for target level so the LLM
    # knows the exact output format it must produce.
    if intent in ("forward_engineer", "reverse_engineer") and state.get("target_level"):
        level = state["target_level"]
    else:
        level = state.get("current_level", "conceptual")

    # ── Strategy 1: full file read (preferred for small specs) ───────────
    full_context = await asyncio.to_thread(_read_full_specs, level)
    if full_context:
        return {"retrieval_context": full_context}

    # ── Strategy 2: RAG fallback ─────────────────────────────────────────
    last_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_message = msg.content
            break

    intent = state.get("user_intent", "create")
    query = f"[{level} level] [{intent}] {last_message}"
    filters = _pick_filters(state)

    model_docs = await aretrieve(
        query=query,
        level=filters["level"],
        doc_type="model",
        k=6,
    )

    context = format_retrieved_context(model_docs)

    return {"retrieval_context": context}
