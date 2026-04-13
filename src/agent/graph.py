"""Main LangGraph definition for DBFlow AI — Database Design Assistant.

Graph Flow:
    START -> router -> conditional_edge:
        "create"  -> retriever -> schema_generator -> validator -> END
        "edit"    -> retriever -> schema_editor   -> validator -> END
        "chat"    -> chatbot         -> END
        (convert / revert  -> placeholder nodes -> END)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from agent.nodes.retriever import retriever_node
from agent.nodes.router import route_intent, router_node
from agent.nodes.schema_generator import schema_editor_node, schema_generator_node
from agent.nodes.validator import validator_node
from agent.state import AgentState

load_dotenv()


# ── Fallback / placeholder nodes ────────────────────────────────────────────


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


async def placeholder_node(state: AgentState) -> Dict[str, Any]:
    """Placeholder for features not yet implemented (convert, revert)."""
    intent = state.get("user_intent", "unknown")
    return {
        "messages": [
            AIMessage(
                content=(
                    f"🚧 The **{intent}** feature is not yet implemented. "
                    "It will be available in a future update!"
                )
            )
        ]
    }


# ── Build the graph ─────────────────────────────────────────────────────────


def _route_after_retriever(state: AgentState) -> str:
    """After retrieval, route to the correct generation node."""
    intent = state.get("user_intent", "create")
    if intent == "edit":
        return "schema_editor"
    return "schema_generator"


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
    builder.add_node("schema_converter", placeholder_node)
    builder.add_node("reverter", placeholder_node)

    # Entry point
    builder.add_edge("__start__", "router")

    # Router -> conditional dispatch
    # create / edit go through retriever first to fetch schema specs from RAG
    builder.add_conditional_edges(
        "router",
        route_intent,
        {
            "schema_generator": "retriever",  # create -> retriever first
            "schema_editor": "retriever",      # edit -> retriever first
            "schema_converter": "schema_converter",
            "reverter": "reverter",
            "chatbot": "chatbot",
        },
    )

    # Retriever -> conditional: schema_generator or schema_editor
    builder.add_conditional_edges(
        "retriever",
        _route_after_retriever,
        {
            "schema_generator": "schema_generator",
            "schema_editor": "schema_editor",
        },
    )

    # schema_generator / schema_editor -> validator -> END
    builder.add_edge("schema_generator", "validator")
    builder.add_edge("schema_editor", "validator")
    builder.add_edge("validator", END)

    # Other nodes -> END directly
    builder.add_edge("chatbot", END)
    builder.add_edge("schema_converter", END)
    builder.add_edge("reverter", END)

    return builder


graph = build_graph().compile(name="DBFlow AI")
