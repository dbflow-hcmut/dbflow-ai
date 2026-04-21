"""LangGraph State definition for DBFlow AI agent."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, Sequence

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict

from agent.models import DiagramModel, SchemaLevel, SchemaModel, UserIntent


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
    """

    messages: Annotated[Sequence[AnyMessage], add_messages]
    schema_model: Optional[Dict[str, Any]]
    input_model: Optional[Dict[str, Any]]
    history: List[Dict[str, Any]]
    current_level: str  # default "conceptual" — set in graph entry
    target_level: Optional[str]  # explicit engineering target, set by router
    user_intent: Optional[str]
    retrieval_context: Optional[str]
    validation_issues: List[str]  # issues from last validator run (empty = passed)
    retry_count: int  # number of validator-triggered retries for this request
