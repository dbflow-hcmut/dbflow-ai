"""Forward Engineering and Reverse Engineering nodes for DBFlow AI.

Forward Engineering: Transform a schema to a more concrete/lower-level representation.
  - Conceptual → Logical
  - Logical    → Physical

Reverse Engineering: Transform DDL / physical schema to a higher-level representation.
  - Physical DDL → Logical
  - Physical DDL → Conceptual
  - Logical      → Conceptual
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from agent.nodes.schema_generator import (
    _ensure_unique_ids,
    _extract_model_json,
    _extract_text_before_json,
    _make_llm,
    _normalize_content,
)
from agent.prompts import FORWARD_ENGINEER_PROMPT, LEVEL_INSTRUCTIONS, REVERSE_ENGINEER_PROMPT
from agent.state import AgentState
from agent.utils import resolve_image_urls

load_dotenv()
logger = logging.getLogger(__name__)

_MAX_RETRIES = int(os.getenv("SCHEMA_GEN_MAX_RETRIES", "2"))

# Maps each level to its natural "next" level for forward engineering
_FORWARD_TARGET: Dict[str, str] = {
    "conceptual": "logical",
    "logical": "physical",
    "physical": "physical",  # already at lowest — keep as physical
}

# Maps each level to its natural "previous" level for reverse engineering
_REVERSE_TARGET: Dict[str, str] = {
    "physical": "logical",
    "logical": "conceptual",
    "conceptual": "conceptual",  # already at highest — keep as conceptual
}


async def forward_engineer_node(state: AgentState) -> Dict[str, Any]:
    """Forward-engineer the current schema to the next abstraction level.

    Reads ``state['schema_model']`` as the source and transforms it to
    the target level detected from the user message (or the natural next level).
    """
    llm = _make_llm()

    source_level = state.get("current_level", "conceptual")
    # Use explicit target_level from state (set by router from user's message).
    # Fall back to the natural next level if not specified.
    target_level = state.get("target_level") or _FORWARD_TARGET.get(source_level, "logical")

    source_schema = state.get("schema_model")
    if not source_schema:
        return {
            "messages": [
                AIMessage(
                    content=(
                        " No schema found to forward engineer. "
                        "Please create a schema first, or describe what you'd like to design."
                    )
                )
            ]
        }

    source_schema_str = json.dumps(source_schema, indent=2, ensure_ascii=False)
    level_instructions = LEVEL_INSTRUCTIONS.get(target_level, "")

    prompt = FORWARD_ENGINEER_PROMPT.format(
        source_schema=source_schema_str,
        source_level=source_level,
        target_level=target_level,
    )

    messages_to_send = [
        SystemMessage(content=prompt),
        *state["messages"],
    ]
    messages_to_send = await resolve_image_urls(messages_to_send)

    # Inject validation feedback if this is a self-correction retry.
    validation_issues = state.get("validation_issues") or []
    if validation_issues:
        issues_text = "\n".join(f"- {i}" for i in validation_issues)
        messages_to_send.append(
            HumanMessage(
                content=(
                    f"Your previous output failed schema validation with "
                    f"{len(validation_issues)} issue(s). Regenerate the COMPLETE "
                    f"{target_level} model.json fixing ALL of the following:\n\n"
                    f"{issues_text}"
                )
            )
        )

    model_data: Optional[Dict[str, Any]] = None
    response_text = ""

    for attempt in range(_MAX_RETRIES + 1):
        response = await llm.ainvoke(messages_to_send)
        response_text = _normalize_content(response.content)
        model_data = _extract_model_json(response_text)

        if model_data is not None:
            break

        if attempt < _MAX_RETRIES:
            logger.warning(
                "Forward engineer: failed to parse JSON. Retry %d/%d",
                attempt + 1, _MAX_RETRIES,
            )
            messages_to_send = [
                SystemMessage(content=prompt),
                *state["messages"],
                AIMessage(content=response_text),
                HumanMessage(
                    content=(
                        "Your output was truncated or malformed. Please regenerate "
                        "the COMPLETE transformed model.json in a single valid fenced "
                        "code block. Do NOT shorten or omit any table or column."
                    )
                ),
            ]
        else:
            logger.warning("Forward engineer: still failed after %d retries.", _MAX_RETRIES)

    if model_data:
        model_data = _ensure_unique_ids(model_data)

    # Snapshot current schema into history
    history = list(state.get("history") or [])
    if source_schema:
        history.append({"schema_model": source_schema})

    if model_data:
        tables = model_data.get("entities", []) or model_data.get("tables", [])
        table_names = [t.get("name", "?") for t in tables]

        ai_description = _extract_text_before_json(response_text)
        if not ai_description:
            ai_description = (
                f"I've forward engineered your {source_level} schema into a "
                f"{target_level} schema with {len(table_names)} tables."
            )

        summary = (
            f"{ai_description}\n\n"
            f"```model.json\n{json.dumps(model_data, indent=2, ensure_ascii=False)}\n```\n\n"
            f"I've transformed your {source_level} schema into a {target_level} schema "
            f"with {len(table_names)} {'entities' if target_level == 'conceptual' else 'tables'}."
        )
    else:
        summary = (
            f"Could not generate the forward-engineered schema. "
            f"Raw response:\n\n{response_text}"
        )

    return {
        "schema_model": model_data or source_schema,
        "history": history,
        "current_level": target_level,
        # Suppress message during validation retries — validator already shows "auto-correcting..."
        "messages": [] if validation_issues else [AIMessage(content=summary)],
    }


async def reverse_engineer_node(state: AgentState) -> Dict[str, Any]:
    """Reverse-engineer DDL or a physical schema into a higher-level representation.

    Reads DDL/SQL from the user's latest message, or uses the current
    ``state['schema_model']``, and generates a higher-level schema.
    """
    llm = _make_llm()

    source_level = state.get("current_level", "physical")
    # Use explicit target_level from state (set by router from user's message).
    # Fall back to the natural previous level if not specified.
    target_level = state.get("target_level") or _REVERSE_TARGET.get(source_level, "logical")

    # Load schema spec for the target level from RAG context (if available)
    retrieval_context = state.get("retrieval_context") or "(No schema specification available)"
    level_instructions = LEVEL_INSTRUCTIONS.get(target_level, "")

    prompt = REVERSE_ENGINEER_PROMPT.format(
        target_level=target_level,
        level_specific_instructions=level_instructions,
        retrieval_context=retrieval_context,
    )

    messages_to_send = [
        SystemMessage(content=prompt),
        *state["messages"],
    ]
    messages_to_send = await resolve_image_urls(messages_to_send)

    # Inject validation feedback if this is a self-correction retry.
    validation_issues = state.get("validation_issues") or []
    if validation_issues:
        issues_text = "\n".join(f"- {i}" for i in validation_issues)
        messages_to_send.append(
            HumanMessage(
                content=(
                    f"Your previous output failed schema validation with "
                    f"{len(validation_issues)} issue(s). Regenerate the COMPLETE "
                    f"{target_level} model.json fixing ALL of the following:\n\n"
                    f"{issues_text}"
                )
            )
        )

    # If a current schema_model exists, include it as additional context
    current_schema = state.get("schema_model")
    if current_schema:
        messages_to_send.insert(
            1,
            SystemMessage(
                content=(
                    f"Current schema (for reference):\n"
                    f"```json\n{json.dumps(current_schema, indent=2, ensure_ascii=False)}\n```"
                )
            ),
        )

    model_data: Optional[Dict[str, Any]] = None
    response_text = ""

    for attempt in range(_MAX_RETRIES + 1):
        response = await llm.ainvoke(messages_to_send)
        response_text = _normalize_content(response.content)
        model_data = _extract_model_json(response_text)

        if model_data is not None:
            break

        if attempt < _MAX_RETRIES:
            logger.warning(
                "Reverse engineer: failed to parse JSON. Retry %d/%d",
                attempt + 1, _MAX_RETRIES,
            )
            messages_to_send = [
                SystemMessage(content=prompt),
                *state["messages"],
                AIMessage(content=response_text),
                HumanMessage(
                    content=(
                        "Your output was truncated or malformed. Please regenerate "
                        "the COMPLETE reverse-engineered model.json in a single valid "
                        "fenced code block. Do NOT shorten or omit any table or column."
                    )
                ),
            ]
        else:
            logger.warning("Reverse engineer: still failed after %d retries.", _MAX_RETRIES)

    if model_data:
        model_data = _ensure_unique_ids(model_data)

    # Snapshot current schema into history
    history = list(state.get("history") or [])
    if current_schema:
        history.append({"schema_model": current_schema})

    if model_data:
        tables = model_data.get("entities", []) or model_data.get("tables", [])
        table_names = [t.get("name", "?") for t in tables]

        ai_description = _extract_text_before_json(response_text)
        if not ai_description:
            ai_description = (
                f"I've reverse engineered the DDL into a {target_level} schema "
                f"with {len(table_names)} tables/entities."
            )

        summary = (
            f"{ai_description}\n\n"
            f"```model.json\n{json.dumps(model_data, indent=2, ensure_ascii=False)}\n```\n\n"
            f"I've reverse engineered the input into a {target_level} schema "
            f"with {len(table_names)} {'entities' if target_level == 'conceptual' else 'tables'}."
        )
    else:
        summary = (
            f"Could not parse the reverse-engineered schema. "
            f"Raw response:\n\n{response_text}"
        )

    return {
        "schema_model": model_data,
        "history": history,
        "current_level": target_level,
        # Suppress message during validation retries — validator already shows "auto-correcting..."
        "messages": [] if validation_issues else [AIMessage(content=summary)],
    }
