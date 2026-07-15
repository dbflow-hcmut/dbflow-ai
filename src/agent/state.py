"""LangGraph State definition for DBFlow AI agent."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Sequence

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Central state managed by the LangGraph StateGraph.

    Attributes:
        messages: Conversation history (auto-merged via ``add_messages``).
        schema_model: Current DB schema (model.json).
        input_model: Optional schema model sent from the frontend to sync
                     with the AI thread state (used for forward/reverse engineering).
        history: Previous snapshots of ``schema_model`` for revert.
        current_level: Active abstraction level of the current schema (Conceptual / Logical / Physical).
        target_level: Explicit target level requested for forward/reverse engineering.
                      Set by router; does NOT overwrite current_level.
        user_intent: Classified intent from the latest user message.
        retrieval_context: Retrieved schema spec documentation from RAG (injected into LLM prompts).
        validation_issues: List of issues from the most recent validator run.
                           Empty list means validation passed.
        retry_count: How many times the validator has triggered a retry for
                     the current user request. Reset to 0 by the router on
                     each new message.
        input_intent: Explicit intent override sent by the frontend for this
                      turn (e.g. "text_to_sql"). Consumed and cleared by
                      router_node, which then skips LLM classification.
        generated_sql: SQL text produced by sql_generator_node for the
                       "text_to_sql" intent.
    """

    messages: Annotated[Sequence[AnyMessage], add_messages]
    schema_model: Dict[str, Any] | None
    input_model: Dict[str, Any] | None
    history: List[Dict[str, Any]]
    current_level: str  # default "conceptual" — set in graph entry
    target_level: str | None  # explicit engineering target, set by router
    user_intent: str | None
    retrieval_context: str | None
    validation_issues: List[str]  # issues from last validator run (empty = passed)
    retry_count: int  # number of validator-triggered retries for this request
    project_id: str | None
    project_docs_context: str | None
    project_docs_candidates: List[Dict[str, Any]] | None  # [{page_content, metadata, score}] before reranking
    target_dbms: str | None  # "postgresql" | "mysql" | "sqlserver" | None
    input_intent: str | None  # explicit intent override from frontend, e.g. "text_to_sql"
    generated_sql: str | None  # SQL produced by sql_generator_node
