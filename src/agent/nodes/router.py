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
from agent.utils import resolve_image_urls

load_dotenv()

# Intents set explicitly by the frontend via `input_intent` — never guessed
# by the LLM classifier. Both always target the physical schema.
_EXPLICIT_OVERRIDE_INTENTS = {UserIntent.TEXT_TO_SQL.value, UserIntent.SEED_DATA.value}


def _clean_suggested_title(value: str, max_length: int = 80) -> str:
    """Normalize the model-generated conversation title for UI persistence."""
    title = " ".join((value or "").split()).strip(" \t\r\n\"'“”‘’")
    for prefix in ("ai:", "chat:"):
        if title.lower().startswith(prefix):
            title = title[len(prefix):].lstrip()
            break
    title = title.rstrip(" .,!?:;…-")
    if len(title) <= max_length:
        return title

    shortened = title[: max_length + 1].rsplit(" ", 1)[0].rstrip()
    return shortened or title[:max_length].rstrip()


def _make_router_model(model_name: str) -> ChatGoogleGenerativeAI:
    """Create a fast Gemini model wired to return ``RouterOutput``."""
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0,
        # A classification response is at most a few hundred tokens — cap it
        # so a decoding glitch (e.g. Gemini degenerating into a repeated-token
        # loop) can't run away to tens of thousands of tokens before failing.
        max_output_tokens=1024,
    )
    return llm.with_structured_output(RouterOutput)


async def router_node(state: AgentState) -> Dict[str, Any]:
    """Analyse the latest user message and classify the intent.

    Sets ``state["user_intent"]`` so downstream conditional edges can route.
    Also syncs ``input_model`` → ``schema_model`` if the frontend provided it.
    """
    model = _make_router_model(state["model_name"])

    # Sync input_model from frontend into the schema_model state.
    updates: Dict[str, Any] = {}
    if state.get("input_model"):
        updates["schema_model"] = state["input_model"]
        updates["input_model"] = None  # clear after sync

    effective_schema = updates.get("schema_model") or state.get("schema_model")

    # Explicit intent override from the frontend — skip LLM classification
    # entirely. Always clear input_intent (both branches) so a stale value
    # can't leak into a later turn on the same persisted thread.
    override_intent = state.get("input_intent")
    updates["input_intent"] = None

    if override_intent in _EXPLICIT_OVERRIDE_INTENTS:
        updates["user_intent"] = override_intent
        updates["validation_issues"] = []
        updates["retry_count"] = 0
        updates["current_level"] = "physical"  # both overrides always target the physical model

        target_dbms = None
        if isinstance(effective_schema, dict):
            target_dbms = (effective_schema.get("model") or {}).get("dbms")
        if target_dbms:
            updates["target_dbms"] = target_dbms

        routing_msg = AIMessage(
            content=json.dumps({
                "intent": override_intent,
                "detected_level": None,
                "detected_dbms": target_dbms,
                "effective_level": "physical",
                "reasoning": f"Explicit intent override from frontend: {override_intent}.",
            })
        )
        updates["messages"] = [routing_msg]
        return updates

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
    messages = await resolve_image_urls(messages)

    result: RouterOutput = await model.ainvoke(messages)

    updates["user_intent"] = result.intent.value

    # Reset validation retry state on every new user request.
    updates["validation_issues"] = []
    updates["retry_count"] = 0

    if result.detected_level and result.detected_level in (
        "conceptual", "logical", "physical"
    ):
        updates["current_level"] = result.detected_level

    if result.detected_dbms and result.detected_dbms in (
        "postgresql", "mysql", "sqlserver"
    ):
        updates["target_dbms"] = result.detected_dbms

    effective_level = updates.get("current_level") or state.get("current_level", "conceptual")

    # Emit routing info as an AIMessage so the frontend can read intent,
    # detected_level, AND effective_level through the streaming SSE.
    # Strip whitespace from reasoning — Gemini thinking tokens can bloat this field.
    clean_reasoning = " ".join((result.reasoning or "").split())[:300]
    suggested_title = _clean_suggested_title(result.suggested_title)
    routing_msg = AIMessage(
        content=json.dumps({
            "intent": result.intent.value,
            "detected_level": result.detected_level,
            "detected_dbms": result.detected_dbms,
            "effective_level": effective_level,
            "reasoning": clean_reasoning,
            "suggested_title": suggested_title,
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
        UserIntent.CHAT.value: "chatbot",
        UserIntent.TEXT_TO_SQL.value: "sql_generator",
        UserIntent.SEED_DATA.value: "sql_generator",
    }
    return mapping.get(intent, "chatbot")
