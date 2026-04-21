"""Main LangGraph definition for DBFlow AI — Database Design Assistant.

Graph Flow:
    START -> router -> conditional_edge:
        "create"           -> retriever -> schema_generator  -> validator -> END
        "edit"             -> retriever -> schema_editor     -> validator -> END
        "forward_engineer" -> retriever -> forward_engineer  -> validator -> END
        "reverse_engineer" -> retriever -> reverse_engineer  -> validator -> END
        "chat"             -> chatbot                                     -> END
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from agent.nodes.retriever import retriever_node
from agent.nodes.router import route_intent, router_node
from agent.nodes.schema_generator import schema_editor_node, schema_generator_node
from agent.nodes.engineering import forward_engineer_node, reverse_engineer_node
from agent.nodes.validator import validator_node
from agent.models import UserIntent
from agent.state import AgentState

load_dotenv()

# Maximum number of times the validator can send the LLM back for corrections.
_MAX_VALIDATION_RETRIES = int(os.getenv("VALIDATION_MAX_RETRIES", "2"))


# ── Nodes ────────────────────────────────────────────────────────────────────


async def chatbot_node(state: AgentState) -> Dict[str, Any]:
    """General-purpose chatbot — answers questions about the current schema."""
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("API_MODEL"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.7,
    )

    system = (
        "You are DBFlow AI, a helpful Database Design Assistant. "
        "Answer questions about database design, the current schema, "
        "or general DB concepts. If the user seems to want to create or "
        "edit a schema, suggest they phrase it as a direct request."
    )

    # Include current schema context if available
    context_parts = [system]
    if state.get("schema_model"):
        context_parts.append(
            f"\nCurrent schema:\n```json\n"
            f"{json.dumps(state['schema_model'], indent=2)}\n```"
        )

    messages = [SystemMessage(content="\n".join(context_parts)), *state["messages"]]
    response = await llm.ainvoke(messages)
    return {"messages": [response]}


# ── Build the graph ─────────────────────────────────────────────────────────


def _route_after_retriever(state: AgentState) -> str:
    """After retrieval, route to the correct generation node."""
    intent = state.get("user_intent", "create")
    if intent == "edit":
        return "schema_editor"
    if intent == "forward_engineer":
        return "forward_engineer"
    if intent == "reverse_engineer":
        return "reverse_engineer"
    return "schema_generator"


def _route_after_validator(state: AgentState) -> str:
    """After validation, either end or retry the generating node.

    If validation found issues AND the retry budget is not exhausted,
    route back to the same node that produced the failing schema so the
    LLM can self-correct using the list of issues as feedback.
    Bypasses the retriever on retries (retrieval_context is still in state).
    """
    issues = state.get("validation_issues") or []
    retries = state.get("retry_count", 0)

    if not issues or retries > _MAX_VALIDATION_RETRIES:
        return "__end__"

    intent = state.get("user_intent", "create")
    mapping = {
        UserIntent.CREATE.value: "schema_generator",
        UserIntent.EDIT.value: "schema_editor",
        UserIntent.FORWARD_ENGINEER.value: "forward_engineer",
        UserIntent.REVERSE_ENGINEER.value: "reverse_engineer",
    }
    return mapping.get(intent, "__end__")


def build_graph() -> StateGraph:
    """Construct and compile the DBFlow AI StateGraph."""
    builder = StateGraph(AgentState)

    # Add all nodes
    builder.add_node("router", router_node)
    builder.add_node("retriever", retriever_node)
    builder.add_node("schema_generator", schema_generator_node)
    builder.add_node("schema_editor", schema_editor_node)
    builder.add_node("validator", validator_node)
    builder.add_node("chatbot", chatbot_node)
    builder.add_node("forward_engineer", forward_engineer_node)
    builder.add_node("reverse_engineer", reverse_engineer_node)

    # Entry point
    builder.add_edge("__start__", "router")

    # Router -> conditional dispatch
    # All schema-generating intents go through retriever to fetch target-level specs
    builder.add_conditional_edges(
        "router",
        route_intent,
        {
            "schema_generator": "retriever",
            "schema_editor": "retriever",
            "forward_engineer": "retriever",   # needs target-level spec
            "reverse_engineer": "retriever",   # needs target-level spec
            "chatbot": "chatbot",
        },
    )

    # Retriever -> conditional: route to the correct generation node
    builder.add_conditional_edges(
        "retriever",
        _route_after_retriever,
        {
            "schema_generator": "schema_generator",
            "schema_editor": "schema_editor",
            "forward_engineer": "forward_engineer",
            "reverse_engineer": "reverse_engineer",
        },
    )

    # schema_generator / schema_editor / engineering nodes -> validator -> conditional retry or END
    builder.add_edge("schema_generator", "validator")
    builder.add_edge("schema_editor", "validator")
    builder.add_edge("forward_engineer", "validator")
    builder.add_edge("reverse_engineer", "validator")
    builder.add_conditional_edges(
        "validator",
        _route_after_validator,
        {
            "schema_generator": "schema_generator",
            "schema_editor": "schema_editor",
            "forward_engineer": "forward_engineer",
            "reverse_engineer": "reverse_engineer",
            "__end__": END,
        },
    )

    # Other nodes -> END directly
    builder.add_edge("chatbot", END)

    return builder


graph = build_graph().compile(name="DBFlow AI")
