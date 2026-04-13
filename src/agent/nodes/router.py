"""Router node — classifies user intent to direct the graph flow."""

from __future__ import annotations

import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from agent.models import RouterOutput, UserIntent
from agent.prompts import ROUTER_PROMPT
from agent.state import AgentState

load_dotenv()


def _make_router_model() -> ChatGoogleGenerativeAI:
    """Create a fast Gemini model wired to return ``RouterOutput``."""
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("API_MODEL"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0,
    )
    return llm.with_structured_output(RouterOutput)


async def router_node(state: AgentState) -> Dict[str, Any]:
    """Analyse the latest user message and classify the intent.

    Sets ``state["user_intent"]`` so downstream conditional edges can route.
    """
    model = _make_router_model()

    # Build context: include info about whether a schema already exists
    context_parts: list[str] = []
    if state.get("schema_model"):
        context_parts.append("A schema already exists in the current session.")
    else:
        context_parts.append("No schema exists yet in the current session.")
    context_parts.append(f"Current level: {state.get('current_level', 'conceptual')}")

    context_msg = SystemMessage(content="\n".join(context_parts))

    messages = [
        SystemMessage(content=ROUTER_PROMPT),
        context_msg,
        *state["messages"],
    ]

    result: RouterOutput = await model.ainvoke(messages)

    updates: Dict[str, Any] = {"user_intent": result.intent.value}

    # Update current_level if the user explicitly mentioned a level
    if result.detected_level and result.detected_level in (
        "conceptual", "logical", "physical"
    ):
        updates["current_level"] = result.detected_level

    return updates


def route_intent(state: AgentState) -> str:
    """Conditional edge function — returns the next node name based on intent."""
    intent = state.get("user_intent", UserIntent.CHAT.value)
    mapping = {
        UserIntent.CREATE.value: "schema_generator",
        UserIntent.EDIT.value: "schema_editor",
        UserIntent.CONVERT.value: "schema_converter",
        UserIntent.REVERT.value: "reverter",
        UserIntent.CHAT.value: "chatbot",
    }
    return mapping.get(intent, "chatbot")
