"""Router node — classifies user intent to direct the graph flow."""

from __future__ import annotations

import json
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
    Also syncs ``input_model`` → ``schema_model`` if the frontend provided it.
    """
    model = _make_router_model()

    # Sync input_model from frontend into the schema_model state
    # This ensures forward/reverse engineering always uses the latest diagram.
    updates: Dict[str, Any] = {}
    if state.get("input_model"):
        updates["schema_model"] = state["input_model"]
        updates["input_model"] = None  # clear after sync

    effective_schema = updates.get("schema_model") or state.get("schema_model")

    # Build context: include info about whether a schema already exists
    context_parts: list[str] = []
    if effective_schema:
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

    updates["user_intent"] = result.intent.value

    # Reset validation retry state on every new user request.
    updates["validation_issues"] = []
    updates["retry_count"] = 0
    updates["target_level"] = None

    # For forward/reverse engineering: store the detected target level in
    # `target_level` WITHOUT overwriting `current_level`.  current_level must
    # stay as the level of the *source* schema so the engineering node reads
    # the correct source.
    #
    # For create/edit: update current_level to what the user specified (or keep
    # existing value if the user didn't mention a level).
    if result.detected_level and result.detected_level in (
        "conceptual", "logical", "physical"
    ):
        if result.intent.value in (
            UserIntent.FORWARD_ENGINEER.value,
            UserIntent.REVERSE_ENGINEER.value,
        ):
            updates["target_level"] = result.detected_level
        else:
            updates["current_level"] = result.detected_level

    # Compute the effective schema level the AI will generate.
    # For create/edit: the current_level (possibly just updated above).
    # For forward/reverse engineering: the target_level.
    effective_level = (
        updates.get("target_level")
        or updates.get("current_level")
        or state.get("current_level", "conceptual")
    )

    # Emit routing info as an AIMessage so the frontend can read intent,
    # detected_level, AND effective_level through the streaming SSE.
    routing_msg = AIMessage(
        content=json.dumps({
            "intent": result.intent.value,
            "detected_level": result.detected_level,
            "effective_level": effective_level,
            "reasoning": result.reasoning,
        })
    )
    updates["messages"] = [routing_msg]

    return updates


def route_intent(state: AgentState) -> str:
    """Conditional edge function — returns the next node name based on intent."""
    intent = state.get("user_intent", UserIntent.CHAT.value)
    mapping = {
        UserIntent.CREATE.value: "schema_generator",
        UserIntent.EDIT.value: "schema_editor",
        UserIntent.FORWARD_ENGINEER.value: "forward_engineer",
        UserIntent.REVERSE_ENGINEER.value: "reverse_engineer",
        UserIntent.CHAT.value: "chatbot",
    }
    return mapping.get(intent, "chatbot")
