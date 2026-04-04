"""Retriever node — query ChromaDB for relevant schema specification docs.

All ChromaDB I/O is async (runs in a background thread) so the LangGraph
ASGI event loop is never blocked.
"""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.messages import HumanMessage

from agent.models import UserIntent
from agent.rag import aretrieve, format_retrieved_context
from agent.state import AgentState


def _pick_filters(state: AgentState) -> dict:
    """Determine which doc_type / level to filter by based on intent + current_level."""
    level = state.get("current_level", "conceptual")
    intent = state.get("user_intent", "create")

    # For create/edit we need both model + diagram specs
    # For convert we might need the target level too — but for now keep it simple
    return {"level": level, "doc_type": None}


async def retriever_node(state: AgentState) -> Dict[str, Any]:
    """Retrieve relevant schema specification docs from the vector store.

    Uses the latest user message + intent + current level to build the query.
    Sets ``state["retrieval_context"]`` with the formatted reference text.
    """
    # Build a rich query from the last user message
    last_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_message = msg.content
            break

    intent = state.get("user_intent", "create")
    level = state.get("current_level", "conceptual")

    # Compose a query that captures what the user wants + the schema level
    query = f"[{level} level] [{intent}] {last_message}"

    filters = _pick_filters(state)

    # Retrieve model + diagram schema docs (async — runs in thread)
    model_docs = await aretrieve(
        query=query,
        level=filters["level"],
        doc_type="model",
        k=4,
    )

    diagram_docs = await aretrieve(
        query=query,
        level=filters["level"],
        doc_type="diagram",
        k=3,
    )

    all_docs = model_docs + diagram_docs
    context = format_retrieved_context(all_docs)

    return {"retrieval_context": context}
