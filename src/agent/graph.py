"""Main LangGraph definition for DBFlow AI — Database Design Assistant.

Graph Flow:
    START -> router -> conditional_edge:
        "create" -> retriever -> reranker -> schema_generator -> validator -> END
        "edit"   -> retriever -> reranker -> schema_editor    -> validator -> END
        "chat"   -> chatbot                                               -> END
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from agent.models import UserIntent
from agent.nodes.reranker import reranker_node
from agent.nodes.retriever import retriever_node
from agent.nodes.router import route_intent, router_node
from agent.nodes.schema_generator import schema_editor_node, schema_generator_node
from agent.nodes.validator import validator_node
from agent.state import AgentState
from agent.utils import resolve_image_urls

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

    context_parts = [system]

    if state.get("schema_model"):
        context_parts.append(
            f"\nCurrent schema:\n```json\n"
            f"{json.dumps(state['schema_model'], indent=2)}\n```"
        )

    # Retrieve project docs for this chat turn
    project_id = state.get("project_id")
    if project_id:
        from langchain_core.messages import HumanMessage as LCHumanMessage

        from agent.rag import aretrieve_project_docs, format_project_docs_context

        last_message = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, LCHumanMessage):
                raw = msg.content
                if isinstance(raw, str):
                    last_message = raw
                elif isinstance(raw, list):
                    last_message = " ".join(
                        p["text"] for p in raw
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                break

        query = last_message or "database project information"
        project_docs = await aretrieve_project_docs(query=query, project_id=project_id, k=4)
        project_docs_context = format_project_docs_context(project_docs)
        if project_docs_context:
            context_parts.append(
                f"\n## Project Documents\n"
                f"The following content was extracted from the user's uploaded project documents. "
                f"Use it to answer questions about the project.\n\n{project_docs_context}"
            )

    messages = [SystemMessage(content="\n".join(context_parts)), *state["messages"]]
    messages = await resolve_image_urls(messages)
    response = await llm.ainvoke(messages)
    return {"messages": [response]}


# ── Build the graph ─────────────────────────────────────────────────────────


def _route_after_retriever(state: AgentState) -> str:
    """After retrieval, route to the correct generation node."""
    intent = state.get("user_intent", "create")
    if intent == "edit":
        return "schema_editor"
    return "schema_generator"


def _route_after_validator(state: AgentState) -> str:
    """After validation, either end or retry the generating node."""
    issues = state.get("validation_issues") or []
    retries = state.get("retry_count", 0)

    if not issues or retries > _MAX_VALIDATION_RETRIES:
        return "__end__"

    intent = state.get("user_intent", "create")
    mapping = {
        UserIntent.CREATE.value: "schema_generator",
        UserIntent.EDIT.value: "schema_editor",
    }
    return mapping.get(intent, "__end__")


def build_graph() -> StateGraph:
    """Construct and compile the DBFlow AI StateGraph."""
    builder = StateGraph(AgentState)

    # Add all nodes
    builder.add_node("router", router_node)
    builder.add_node("retriever", retriever_node)
    builder.add_node("reranker", reranker_node)
    builder.add_node("schema_generator", schema_generator_node)
    builder.add_node("schema_editor", schema_editor_node)
    builder.add_node("validator", validator_node)
    builder.add_node("chatbot", chatbot_node)

    # Entry point
    builder.add_edge("__start__", "router")

    # Router -> conditional dispatch
    builder.add_conditional_edges(
        "router",
        route_intent,
        {
            "schema_generator": "retriever",
            "schema_editor": "retriever",
            "chatbot": "chatbot",
        },
    )

    # Retriever -> reranker (always — reranker is a no-op when no project docs)
    builder.add_edge("retriever", "reranker")

    # Reranker -> conditional: route to the correct generation node
    builder.add_conditional_edges(
        "reranker",
        _route_after_retriever,
        {
            "schema_generator": "schema_generator",
            "schema_editor": "schema_editor",
        },
    )

    # schema_generator / schema_editor -> validator -> conditional retry or END
    builder.add_edge("schema_generator", "validator")
    builder.add_edge("schema_editor", "validator")
    builder.add_conditional_edges(
        "validator",
        _route_after_validator,
        {
            "schema_generator": "schema_generator",
            "schema_editor": "schema_editor",
            "__end__": END,
        },
    )

    # Other nodes -> END directly
    builder.add_edge("chatbot", END)

    return builder


graph = build_graph().compile(name="DBFlow AI")
