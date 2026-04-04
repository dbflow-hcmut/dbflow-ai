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
        schema_model: Current DB schema (tables, fields, relationships).
        ui_diagram: Diagram layout synchronised with *schema_model*.
        history: Previous snapshots of ``(schema_model, ui_diagram)`` for revert.
        current_level: Active abstraction level (Conceptual / Logical / Physical).
        user_intent: Classified intent from the latest user message.
        retrieval_context: Retrieved schema spec documentation from RAG (injected into LLM prompts).
    """

    messages: Annotated[Sequence[AnyMessage], add_messages]
    schema_model: Optional[Dict[str, Any]]
    ui_diagram: Optional[Dict[str, Any]]
    history: List[Dict[str, Any]]
    current_level: str  # default "conceptual" — set in graph entry
    user_intent: Optional[str]
    retrieval_context: Optional[str]
