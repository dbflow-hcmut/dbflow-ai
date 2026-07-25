"""SQL Generator node — generates SQL from natural language.

Shared by two intents: ``text_to_sql`` (single query) and ``seed_data``
(multiple INSERT statements) — they use the same retrieval context, retry
loop, and ```sql extraction, differing only in which prompt template is used.

Grounded in the project's physical schema ``model.json`` (the diagram's saved
schema), not a live DB connection.  Read-only with respect to the schema —
unlike ``schema_generator``/``schema_editor``, this node never mutates
``schema_model``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from agent.models import UserIntent
from agent.nodes.seed_data_postprocess import postprocess_seed_sql
from agent.prompts import SEED_DATA_GENERATOR_PROMPT, SQL_GENERATOR_PROMPT
from agent.state import AgentState
from agent.utils import resolve_image_urls

load_dotenv()
logger = logging.getLogger(__name__)

# Maximum retry attempts when output has no parseable ```sql block
_MAX_RETRIES = int(os.getenv("SCHEMA_GEN_MAX_RETRIES", "2"))

# Mirrors sql_validator.py's dialect map — sqlglot needs its own dialect names.
_DIALECT_MAP = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "sqlserver": "tsql",
}


def _make_llm(
    user_intent: str | None, model_name: str
) -> ChatGoogleGenerativeAI:
    """Create a Gemini model for SQL generation — deterministic output.

    ``seed_data`` gets a larger token budget since it produces many INSERT
    statements across tables, vs. ``text_to_sql``'s single statement. Both
    intents run at temperature 0: keeping PK/unique values collision-free and
    INSERTs in FK order no longer depends on the model's own output (see
    ``postprocess_seed_sql``, called below), so there's nothing to gain from a
    higher temperature — only a higher risk of it breaking the required
    ```sql fence or column-list format.
    """
    is_seed_data = user_intent == UserIntent.SEED_DATA.value
    default_tokens = "8192" if is_seed_data else "4096"
    max_tokens = int(os.getenv("SQL_GEN_MAX_OUTPUT_TOKENS", default_tokens))
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0,
        max_output_tokens=max_tokens,
    )


def _normalize_content(content: Any) -> str:
    """Ensure LLM response content is a plain string (Gemini may return blocks)."""
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


def _extract_text_before_sql(text: str) -> str:
    """Extract the human-readable sentence that appears before the ```sql block."""
    pattern = r"```(?:\w+)?\s*\n[\s\S]*?```"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        before = text[:match.start()].strip()
        return before if before else ""
    return ""


def _extract_sql(text: str) -> str | None:
    """Extract the SQL query from a fenced ```sql code block in LLM output."""
    pattern = r"```sql\s*\n([\s\S]*?)```"
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        return candidate or None

    # Fallback: any fenced block, in case the model forgets the "sql" label
    fallback = r"```(?:\w+)?\s*\n([\s\S]*?)```"
    m2 = re.search(fallback, text)
    if m2:
        candidate = m2.group(1).strip()
        return candidate or None

    # Fallback: an OPENING fence with no closing one — the response was cut
    # off mid-generation (hit max_output_tokens) before the model could close
    # the block. Recover whatever complete statements exist rather than
    # discarding the entire (often mostly-usable) batch.
    m3 = re.search(r"```(?:sql)?\s*\n", text, re.IGNORECASE)
    if m3:
        candidate = text[m3.end():].strip()
        last_semicolon = candidate.rfind(";")
        if last_semicolon != -1:
            return candidate[: last_semicolon + 1]

    return None


async def sql_generator_node(state: AgentState) -> Dict[str, Any]:
    """Generate SQL grounded in the current physical schema_model.

    Produces a single query for ``text_to_sql`` or a batch of INSERT
    statements for ``seed_data``, depending on ``state["user_intent"]``.
    Retries automatically if output has no parseable ```sql block.
    """
    schema_model = state.get("schema_model")
    if not schema_model:
        message = AIMessage(
            content="No physical schema is loaded — open a physical schema before generating."
        )
        return {"generated_sql": None, "messages": [message]}

    user_intent = state.get("user_intent")
    is_seed_data = user_intent == UserIntent.SEED_DATA.value
    llm = _make_llm(user_intent, state["model_name"])

    retrieval_context = state.get("retrieval_context") or "(No physical schema specification available)"
    target_dbms = state.get("target_dbms") or (schema_model.get("model") or {}).get("dbms") or "postgresql"
    schema_json = json.dumps(schema_model, indent=2, ensure_ascii=False)

    prompt_template = SEED_DATA_GENERATOR_PROMPT if is_seed_data else SQL_GENERATOR_PROMPT
    prompt = prompt_template.format(
        retrieval_context=retrieval_context,
        schema_model_json=schema_json,
        target_dbms=target_dbms,
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
                    f"Your previous SQL failed validation with {len(validation_issues)} "
                    f"issue(s). Regenerate the COMPLETE query fixing ALL of the following:\n\n{issues_text}"
                )
            )
        )

    sql: str | None = None
    response_text = ""

    for attempt in range(_MAX_RETRIES + 1):
        response = await llm.ainvoke(messages)
        response_text = _normalize_content(response.content)
        sql = _extract_sql(response_text)

        if sql is not None:
            break  # Valid SQL extracted — done

        if attempt < _MAX_RETRIES:
            logger.warning(
                "Failed to extract SQL from response. Retry %d/%d",
                attempt + 1, _MAX_RETRIES,
            )
            messages = [
                SystemMessage(content=prompt),
                *state["messages"],
                AIMessage(content=response_text),
                HumanMessage(
                    content=(
                        "Your response did not contain a valid SQL query in a fenced "
                        "```sql code block. Please regenerate — output ONLY the SQL "
                        "query inside a single ```sql code block."
                    )
                ),
            ]
        else:
            logger.warning("Still failed to extract SQL after %d retries.", _MAX_RETRIES)

    cyclic_tables: set[str] = set()
    if sql and is_seed_data:
        # Don't rely on the LLM to keep PK/unique values distinct and INSERTs
        # in FK dependency order — re-derive both deterministically from
        # schema_model instead of hoping the prompt's rules were followed.
        dialect = _DIALECT_MAP.get(target_dbms, "postgres")
        sql, cyclic_tables = postprocess_seed_sql(sql, schema_model, dialect)

    if sql:
        ai_description = _extract_text_before_sql(response_text) or "Here's the SQL query for your request."
        summary = f"{ai_description}\n\n```sql\n{sql}\n```"
        if cyclic_tables:
            # No INSERT order can satisfy a genuine FK cycle — surface it as an
            # explicit warning (shown to the user via the frontend's textDescription)
            # instead of letting them hit a bare "FOREIGN KEY constraint failed" at
            # execution time with no clue why.
            tables_list = ", ".join(f"`{t}`" for t in sorted(cyclic_tables))
            summary += (
                f"\n\nCircular foreign-key dependency detected between {tables_list} — "
                "each table has a column referencing the other, so no INSERT order can "
                "satisfy both at once and this SQL may fail with a foreign key constraint "
                "error. This is usually a schema-modeling mistake (e.g. a foreign key drawn "
                "between the wrong columns) — review the relationships between these tables."
            )
    else:
        summary = f"Could not parse a SQL query from the response. Raw response:\n\n{response_text}"

    # Suppress message during validation retries — sql_validator already emitted
    # an "auto-correcting..." notice; show the query only after validation passes.
    outgoing_messages = [] if validation_issues else [AIMessage(content=summary)]

    return {
        "generated_sql": sql,
        "messages": outgoing_messages,
    }
