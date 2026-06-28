"""Schema Generator node — creates / edits DB schema from natural language.

Uses RAG context (retrieved schema specifications from /docs) to ensure
the LLM output conforms to the exact JSON schema defined for each level
(Conceptual, Logical, Physical).

The LLM generates **model.json only**.  The diagram is built separately
by the front-end from the model data.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Set

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from agent.prompts import (
    LEVEL_INSTRUCTIONS,
    SCHEMA_EDITOR_PROMPT,
    SCHEMA_GENERATOR_PROMPT,
)
from agent.state import AgentState
from agent.utils import resolve_image_urls

load_dotenv()
logger = logging.getLogger(__name__)

# Maximum retry attempts when output is truncated / unparseable
_MAX_RETRIES = int(os.getenv("SCHEMA_GEN_MAX_RETRIES", "2"))


def _count_relationships(model_data: Dict[str, Any], level: str) -> int:
    """Count relationships in a model, handling all schema levels.

    Conceptual: top-level `relationships` array.
    Logical/Physical: FK columns inside each table (column.roles.foreignKey).
    """
    if level == "conceptual":
        return len(model_data.get("relationships", []))
    fk_count = 0
    for table in model_data.get("tables", []):
        for col in table.get("columns", []):
            if col.get("roles", {}).get("foreignKey"):
                fk_count += 1
    return fk_count


def _short_uid() -> str:
    """Return a short 8-char hex string for ID uniqueness."""
    return uuid.uuid().hex[:8]


def _ensure_unique_ids(model_data: Dict[str, Any]) -> Dict[str, Any]:
    """Post-process model JSON to guarantee every `id` is globally unique.

    The LLM often generates IDs based on names (e.g. ``cid_name``), causing
    duplicates when multiple entities share attributes with the same name.
    This function detects all duplicate IDs and renames them with a unique
    suffix, updating every cross-reference (relationship ends, generalisations,
    categories) accordingly.
    """
    # --- Phase 1: collect every ID and detect duplicates -------------------
    id_occurrences: Dict[str, List[dict]] = {}  # id -> list of obj refs

    def _register(obj: dict) -> None:
        oid = obj.get("id")
        if oid:
            id_occurrences.setdefault(oid, []).append(obj)

    # Model root
    if "model" in model_data and isinstance(model_data["model"], dict):
        _register(model_data["model"])

    # Entities & their attributes (+ component sub-attributes)
    for entity in model_data.get("entities", []) or model_data.get("tables", []):
        _register(entity)
        for attr in entity.get("attributes", []):
            _register(attr)
            for comp in attr.get("components", []) or []:
                _register(comp)

    # Relationships & their attributes
    for rel in model_data.get("relationships", []):
        _register(rel)
        for attr in rel.get("attributes", []) or []:
            _register(attr)
            for comp in attr.get("components", []) or []:
                _register(comp)

    # Generalisations
    for gen in model_data.get("generalizations", []) or []:
        _register(gen)

    # Categories
    for cat in model_data.get("categories", []) or []:
        _register(cat)

    # --- Phase 2: rename duplicates ---------------------------------------
    seen: Set[str] = set()

    for oid, objs in id_occurrences.items():
        if len(objs) <= 1:
            seen.add(oid)
            continue
        # First occurrence keeps original ID; subsequent ones get a suffix
        first = True
        for obj in objs:
            if first:
                seen.add(oid)
                first = False
                continue
            # Generate a new unique ID preserving the prefix
            new_id = f"{oid}_{_short_uid()}"
            while new_id in seen:
                new_id = f"{oid}_{_short_uid()}"
            seen.add(new_id)
            # We need to remember the mapping at object level, not globally,
            # because the same old ID maps to *different* new IDs for each
            # duplicate.  We patch in-place.
            obj["id"] = new_id
            logger.info("Deduplicated ID: %s -> %s", oid, new_id)

    # --- Phase 3: update cross-references ---------------------------------
    # Build a global set of all *current* entity IDs for reference fixing.
    entity_ids: Set[str] = set()
    for entity in model_data.get("entities", []) or model_data.get("tables", []):
        entity_ids.add(entity["id"])

    # Relationship ends -> entityId
    for rel in model_data.get("relationships", []):
        for end in rel.get("ends", []):
            eid = end.get("entityId", "")
            if eid and eid not in entity_ids:
                # Try to find the closest match (same base ID)
                for real_id in entity_ids:
                    if real_id.startswith(eid) or eid.startswith(real_id.rsplit("_", 1)[0]):
                        end["entityId"] = real_id
                        break

    # Generalisations -> parentEntityId, childEntityIds
    for gen in model_data.get("generalizations", []) or []:
        pid = gen.get("parentEntityId", "")
        if pid and pid not in entity_ids:
            for real_id in entity_ids:
                if real_id.startswith(pid) or pid.startswith(real_id.rsplit("_", 1)[0]):
                    gen["parentEntityId"] = real_id
                    break
        new_children = []
        for cid in gen.get("childEntityIds", []):
            if cid in entity_ids:
                new_children.append(cid)
            else:
                for real_id in entity_ids:
                    if real_id.startswith(cid) or cid.startswith(real_id.rsplit("_", 1)[0]):
                        new_children.append(real_id)
                        break
                else:
                    new_children.append(cid)
        gen["childEntityIds"] = new_children

    # Categories -> categoryEntityId, superclassEntityIds
    for cat in model_data.get("categories", []) or []:
        ceid = cat.get("categoryEntityId", "")
        if ceid and ceid not in entity_ids:
            for real_id in entity_ids:
                if real_id.startswith(ceid) or ceid.startswith(real_id.rsplit("_", 1)[0]):
                    cat["categoryEntityId"] = real_id
                    break
        new_supers = []
        for sid in cat.get("superclassEntityIds", []):
            if sid in entity_ids:
                new_supers.append(sid)
            else:
                for real_id in entity_ids:
                    if real_id.startswith(sid) or sid.startswith(real_id.rsplit("_", 1)[0]):
                        new_supers.append(real_id)
                        break
                else:
                    new_supers.append(sid)
        cat["superclassEntityIds"] = new_supers

    return model_data


def _normalize_content(content: Any) -> str:
    """Ensure LLM response content is a plain string.

    Some providers (e.g. Gemini) may return a list of content blocks
    instead of a single string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _make_llm() -> ChatGoogleGenerativeAI:
    """Create a Gemini model for schema generation with high output token limit.

    Uses SCHEMA_MAX_OUTPUT_TOKENS env var (default 131072) so operators
    can tune the limit without code changes.
    """
    max_tokens = int(os.getenv("SCHEMA_MAX_OUTPUT_TOKENS", "131072"))
    return ChatGoogleGenerativeAI(
        model=os.getenv("API_MODEL"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.1,
        max_output_tokens=max_tokens,
    )


def _extract_text_before_json(text: str) -> str:
    """Extract the human-readable text that appears before the first JSON code block.
    
    Returns the text summary (what the AI wants to say to the user) stripped of
    the JSON code block.
    """
    # Find the first code block
    pattern = r"```(?:\w+)?\s*(?:model\.json)?\s*\n[\s\S]*?```"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        before = text[:match.start()].strip()
        return before if before else ""
    # No code block found — return empty (will fall back to summary)
    return ""


def _extract_model_json(text: str) -> Dict[str, Any] | None:
    """Extract model.json from fenced code blocks in LLM output.

    Looks for patterns like:
        ```model.json
        { ... }
        ```
    or any JSON block containing model-like keys.
    """
    # Try labelled block first
    pattern = r"```(?:\w+)?\s*model\.json\s*\n([\s\S]*?)```"
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Fallback: find any JSON block that looks like a model
    json_pattern = r"```(?:json)?\s*\n([\s\S]*?)```"
    for m in re.finditer(json_pattern, text):
        try:
            parsed = json.loads(m.group(1).strip())
            if isinstance(parsed, dict) and (
                "entities" in parsed
                or "tables" in parsed
                or "model" in parsed
            ):
                return parsed
        except json.JSONDecodeError:
            continue

    return None


async def schema_generator_node(state: AgentState) -> Dict[str, Any]:
    """Generate a brand-new schema (model.json only) from natural language.

    Retries automatically if output is truncated (JSON fails to parse).
    """
    llm = _make_llm()

    retrieval_context = state.get("retrieval_context") or "(No schema specification available)"
    level = state.get("current_level", "conceptual")
    level_instructions = LEVEL_INSTRUCTIONS.get(level, "")
    target_dbms = state.get("target_dbms")
    if level == "physical" and target_dbms:
        level_instructions += f"\n\n**Target DBMS: {target_dbms}** — set `model.dbms` to `\"{target_dbms}\"` and use {target_dbms}-appropriate data types and index types.\n"
    prompt = SCHEMA_GENERATOR_PROMPT.format(
        retrieval_context=retrieval_context,
        current_level=level,
        level_specific_instructions=level_instructions,
        project_docs_context=state.get("project_docs_context") or "",
    )

    messages = [SystemMessage(content=prompt), *state["messages"]]
    messages = await resolve_image_urls(messages)

    # If this is a validation retry, prepend the issues so the LLM self-corrects.
    validation_issues = state.get("validation_issues") or []
    if validation_issues:
        issues_text = "\n".join(f"- {i}" for i in validation_issues)
        messages.append(
            HumanMessage(
                content=(
                    f"Your previous output failed schema validation with "
                    f"{len(validation_issues)} issue(s). Regenerate the COMPLETE "
                    f"model.json fixing ALL of the following:\n\n{issues_text}"
                )
            )
        )

    model_data: Dict[str, Any] | None = None
    response_text = ""

    for attempt in range(_MAX_RETRIES + 1):
        response = await llm.ainvoke(messages)
        response_text = _normalize_content(response.content)
        model_data = _extract_model_json(response_text)

        if model_data is not None:
            break  # Valid JSON parsed — done

        if attempt < _MAX_RETRIES:
            logger.warning(
                "Failed to parse model JSON (truncated?). Retry %d/%d",
                attempt + 1, _MAX_RETRIES,
            )
            messages = [
                SystemMessage(content=prompt),
                *state["messages"],
                AIMessage(content=response_text),
                HumanMessage(
                    content=(
                        "Your output was truncated or malformed — I could not "
                        "parse valid JSON. Please regenerate the COMPLETE "
                        "model.json from the start. Output the full JSON in a "
                        "single fenced code block. Do NOT shorten or skip any "
                        "entity or attribute."
                    )
                ),
            ]
        else:
            logger.warning(
                "Still failed to parse model JSON after %d retries.",
                _MAX_RETRIES,
            )

    # Deduplicate IDs to prevent collisions from LLM output
    if model_data:
        model_data = _ensure_unique_ids(model_data)

    # Snapshot history
    history = list(state.get("history") or [])
    if state.get("schema_model"):
        history.append({"schema_model": state["schema_model"]})

    level = state.get("current_level", "conceptual")
    if model_data:
        entities = model_data.get("entities", []) or model_data.get("tables", [])
        entity_names = [e.get("name", "?") for e in entities]
        rel_count = _count_relationships(model_data, level)

        # Extract the human-readable description from the LLM response
        ai_description = _extract_text_before_json(response_text)
        if not ai_description:
            ai_description = (
                f"I've designed a {level} schema with {len(entity_names)} "
                f"entities ({', '.join(entity_names[:5])}"
                f"{'...' if len(entity_names) > 5 else ''}) "
                f"and {rel_count} relationships."
            )

        summary = (
            f"{ai_description}\n\n"
            f"```model.json\n{json.dumps(model_data, indent=2, ensure_ascii=False)}\n```\n\n"
            f"Schema generated with {len(entity_names)} {'entities' if level == 'conceptual' else 'tables'} "
            f"and {rel_count} relationships."
        )
    else:
        summary = (
            f"Could not parse structured output. Raw response:\n\n{response_text}"
        )

    # Suppress message during validation retries — the validator already emitted
    # a "auto-correcting..." notice; show the schema only after validation passes.
    outgoing_messages = [] if validation_issues else [AIMessage(content=summary)]

    return {
        "schema_model": model_data,
        "history": history,
        "current_level": level,
        "messages": outgoing_messages,
    }


async def schema_editor_node(state: AgentState) -> Dict[str, Any]:
    """Edit an existing schema (model.json only) based on modification request.

    Retries automatically if output is truncated (JSON fails to parse).
    """
    llm = _make_llm()

    retrieval_context = state.get("retrieval_context") or "(No schema specification available)"
    level = state.get("current_level", "conceptual")
    level_instructions = LEVEL_INSTRUCTIONS.get(level, "")
    target_dbms = state.get("target_dbms")
    if level == "physical" and target_dbms:
        level_instructions += f"\n\n**Target DBMS: {target_dbms}** — set `model.dbms` to `\"{target_dbms}\"` and use {target_dbms}-appropriate data types and index types.\n"
    prompt = SCHEMA_EDITOR_PROMPT.format(
        retrieval_context=retrieval_context,
        current_level=level,
        level_specific_instructions=level_instructions,
        project_docs_context=state.get("project_docs_context") or "",
    )

    current_model_json = json.dumps(
        state.get("schema_model", {}), indent=2, ensure_ascii=False
    )

    messages = [
        SystemMessage(content=prompt),
        SystemMessage(
            content=f"Current model.json:\n```json\n{current_model_json}\n```"
        ),
        *state["messages"],
    ]
    messages = await resolve_image_urls(messages)

    # If this is a validation retry, prepend the issues so the LLM self-corrects.
    validation_issues = state.get("validation_issues") or []
    if validation_issues:
        issues_text = "\n".join(f"- {i}" for i in validation_issues)
        messages.append(
            HumanMessage(
                content=(
                    f"Your previous output failed schema validation with "
                    f"{len(validation_issues)} issue(s). Regenerate the COMPLETE "
                    f"updated model.json fixing ALL of the following:\n\n{issues_text}"
                )
            )
        )

    model_data: Dict[str, Any] | None = None
    response_text = ""

    for attempt in range(_MAX_RETRIES + 1):
        response = await llm.ainvoke(messages)
        response_text = _normalize_content(response.content)
        model_data = _extract_model_json(response_text)

        if model_data is not None:
            break  # Valid JSON parsed — done

        if attempt < _MAX_RETRIES:
            logger.warning(
                "Editor: failed to parse model JSON (truncated?). Retry %d/%d",
                attempt + 1, _MAX_RETRIES,
            )
            messages = [
                SystemMessage(content=prompt),
                SystemMessage(
                    content=f"Current model.json:\n```json\n{current_model_json}\n```"
                ),
                *state["messages"],
                AIMessage(content=response_text),
                HumanMessage(
                    content=(
                        "Your output was truncated or malformed — I could not "
                        "parse valid JSON. Please regenerate the COMPLETE "
                        "updated model.json from the start. Do NOT shorten or "
                        "skip any entity or attribute."
                    )
                ),
            ]
        else:
            logger.warning(
                "Editor: still failed to parse model JSON after %d retries.",
                _MAX_RETRIES,
            )

    # Deduplicate IDs to prevent collisions from LLM output
    if model_data:
        model_data = _ensure_unique_ids(model_data)

    # Snapshot history
    history = list(state.get("history") or [])
    if state.get("schema_model"):
        history.append({"schema_model": state["schema_model"]})

    level = state.get("current_level", "conceptual")
    if model_data:
        entities = model_data.get("entities", []) or model_data.get("tables", [])
        entity_names = [e.get("name", "?") for e in entities]
        rel_count = _count_relationships(model_data, level)

        # Extract the human-readable description from the LLM response
        ai_description = _extract_text_before_json(response_text)
        if not ai_description:
            ai_description = (
                f"I've updated the {level} schema. It now has {len(entity_names)} "
                f"entities and {rel_count} relationships."
            )

        summary = (
            f"{ai_description}\n\n"
            f"```model.json\n{json.dumps(model_data, indent=2, ensure_ascii=False)}\n```\n\n"
            f"Schema updated with {len(entity_names)} {'entities' if level == 'conceptual' else 'tables'} "
            f"and {rel_count} relationships."
        )
    else:
        summary = (
            f"Could not parse structured output. Raw response:\n\n{response_text}"
        )

    # Suppress message during validation retries — validator already shows "auto-correcting..."
    outgoing_messages = [] if validation_issues else [AIMessage(content=summary)]

    return {
        "schema_model": model_data or state.get("schema_model"),
        "history": history,
        "current_level": level,
        "messages": outgoing_messages,
    }
