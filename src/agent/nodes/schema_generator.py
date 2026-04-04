"""Schema Generator node — creates / edits DB schema from natural language.

Now uses RAG context (retrieved schema specifications from /docs) to ensure
the LLM output conforms to the exact JSON schema defined for each level
(Conceptual, Logical, Physical).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from agent.prompts import SCHEMA_EDITOR_PROMPT, SCHEMA_GENERATOR_PROMPT
from agent.state import AgentState

load_dotenv()


def _make_llm() -> ChatGoogleGenerativeAI:
    """Create a Gemini model for schema generation (raw text output)."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-lite",
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.4,
    )


def _extract_json_blocks(text: str) -> Dict[str, Any]:
    """Extract model.json and diagram.json from fenced code blocks in LLM output.

    Looks for patterns like:
        ```model.json  or  ```json model.json
        { ... }
        ```
    Returns {"model": {...}, "diagram": {...}}
    """
    result: Dict[str, Any] = {}

    # Pattern: ```<optional lang> <filename>\n<json>\n```
    pattern = r"```(?:\w+)?\s*(model\.json|diagram\.json)\s*\n([\s\S]*?)```"
    matches = re.findall(pattern, text, re.IGNORECASE)

    for label, content in matches:
        key = "model" if "model" in label.lower() else "diagram"
        try:
            result[key] = json.loads(content.strip())
        except json.JSONDecodeError:
            continue

    # Fallback: try to find any two JSON blocks if labels weren't matched
    if len(result) < 2:
        json_pattern = r"```(?:json)?\s*\n([\s\S]*?)```"
        json_matches = re.findall(json_pattern, text)
        for content in json_matches:
            try:
                parsed = json.loads(content.strip())
                # Guess whether it's model or diagram by looking at keys
                if "model" not in result and (
                    "entities" in parsed
                    or "tables" in parsed
                    or "model" in parsed
                ):
                    result["model"] = parsed
                elif "diagram" not in result and (
                    "diagram" in parsed or "nodes" in parsed
                ):
                    result["diagram"] = parsed
            except json.JSONDecodeError:
                continue

    return result


async def schema_generator_node(state: AgentState) -> Dict[str, Any]:
    """Generate a brand-new schema from the user's natural-language request.

    Uses RAG context to ensure output matches the exact schema specification.
    """
    llm = _make_llm()

    # Inject retrieved schema spec into the prompt
    retrieval_context = state.get("retrieval_context") or "(No schema specification available)"
    prompt = SCHEMA_GENERATOR_PROMPT.format(retrieval_context=retrieval_context)

    messages = [
        SystemMessage(content=prompt),
        *state["messages"],
    ]

    response = await llm.ainvoke(messages)
    response_text = response.content

    # Extract structured JSON from the LLM response
    extracted = _extract_json_blocks(response_text)

    model_data = extracted.get("model")
    diagram_data = extracted.get("diagram")

    # Snapshot history (push current before overwriting)
    history = list(state.get("history") or [])
    if state.get("schema_model"):
        history.append(
            {
                "schema_model": state["schema_model"],
                "ui_diagram": state["ui_diagram"],
            }
        )

    # Build a friendly summary for the user
    level = state.get("current_level", "conceptual")
    if model_data:
        # Count entities/tables depending on level
        entities = (
            model_data.get("entities", [])
            or model_data.get("tables", [])
        )
        entity_names = [e.get("name", "?") for e in entities]
        rels = (
            model_data.get("relationships", [])
        )

        summary = (
            f"✅ **Schema created successfully!** (Level: {level})\n\n"
            f"**Entities/Tables ({len(entity_names)}):** {', '.join(entity_names)}\n"
            f"**Relationships:** {len(rels)}\n\n"
            f"<details><summary>📋 model.json</summary>\n\n"
            f"```json\n{json.dumps(model_data, indent=2, ensure_ascii=False)}\n```\n\n"
            f"</details>\n\n"
        )
        if diagram_data:
            summary += (
                f"<details><summary>🗺️ diagram.json</summary>\n\n"
                f"```json\n{json.dumps(diagram_data, indent=2, ensure_ascii=False)}\n```\n\n"
                f"</details>"
            )
    else:
        # Fallback: return raw LLM response if extraction failed
        summary = (
            f"⚠️ Could not parse structured output. Raw response:\n\n{response_text}"
        )

    return {
        "schema_model": model_data,
        "ui_diagram": diagram_data,
        "history": history,
        "current_level": level,
        "messages": [AIMessage(content=summary)],
    }


async def schema_editor_node(state: AgentState) -> Dict[str, Any]:
    """Edit an existing schema based on the user's modification request.

    Uses RAG context to ensure output stays conformant to schema spec.
    """
    llm = _make_llm()

    retrieval_context = state.get("retrieval_context") or "(No schema specification available)"
    prompt = SCHEMA_EDITOR_PROMPT.format(retrieval_context=retrieval_context)

    current_model_json = json.dumps(
        state.get("schema_model", {}), indent=2, ensure_ascii=False
    )
    current_diagram_json = json.dumps(
        state.get("ui_diagram", {}), indent=2, ensure_ascii=False
    )

    messages = [
        SystemMessage(content=prompt),
        SystemMessage(
            content=(
                f"Current model.json:\n```json\n{current_model_json}\n```\n\n"
                f"Current diagram.json:\n```json\n{current_diagram_json}\n```"
            )
        ),
        *state["messages"],
    ]

    response = await llm.ainvoke(messages)
    response_text = response.content

    extracted = _extract_json_blocks(response_text)
    model_data = extracted.get("model")
    diagram_data = extracted.get("diagram")

    # Push current state to history before applying edits
    history = list(state.get("history") or [])
    if state.get("schema_model"):
        history.append(
            {
                "schema_model": state["schema_model"],
                "ui_diagram": state["ui_diagram"],
            }
        )

    level = state.get("current_level", "conceptual")
    if model_data:
        entities = model_data.get("entities", []) or model_data.get("tables", [])
        entity_names = [e.get("name", "?") for e in entities]

        summary = (
            f"✏️ **Schema updated successfully!** (Level: {level})\n\n"
            f"**Entities/Tables ({len(entity_names)}):** {', '.join(entity_names)}\n"
            f"**Relationships:** {len(model_data.get('relationships', []))}\n\n"
            f"<details><summary>📋 model.json</summary>\n\n"
            f"```json\n{json.dumps(model_data, indent=2, ensure_ascii=False)}\n```\n\n"
            f"</details>\n\n"
        )
        if diagram_data:
            summary += (
                f"<details><summary>🗺️ diagram.json</summary>\n\n"
                f"```json\n{json.dumps(diagram_data, indent=2, ensure_ascii=False)}\n```\n\n"
                f"</details>"
            )
    else:
        summary = (
            f"⚠️ Could not parse structured output. Raw response:\n\n{response_text}"
        )

    return {
        "schema_model": model_data or state.get("schema_model"),
        "ui_diagram": diagram_data or state.get("ui_diagram"),
        "history": history,
        "current_level": level,
        "messages": [AIMessage(content=summary)],
    }
