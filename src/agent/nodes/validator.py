"""Validator node — checks schema consistency using the actual JSON Schema specs.

Validates ``schema_model`` and ``ui_diagram`` from the agent state against
the JSON Schema files in ``/docs/<level>/``.  Also runs generic structural
checks (duplicate names, dangling references, etc.).

All blocking I/O (file reads, ``jsonschema`` import) is wrapped in
``asyncio.to_thread`` so the LangGraph ASGI event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage

from agent.state import AgentState

# ── Paths ────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # dbflow-ai/
_DOCS_DIR = _PROJECT_ROOT / "docs"

# Map schema level -> directory name
_LEVEL_DIR = {
    "conceptual": "conceptual",
    "logical": "logical",
    "physical": "physical",
}


def _load_json_schema(level: str, kind: str) -> Optional[dict]:
    """Load a JSON Schema file for the given level and kind (model/diagram).

    Returns ``None`` if the schema file does not exist.
    """
    dir_name = _LEVEL_DIR.get(level)
    if not dir_name:
        return None

    schema_file = _DOCS_DIR / dir_name / f"{kind}.schema.json"
    if not schema_file.exists():
        return None

    return json.loads(schema_file.read_text(encoding="utf-8"))


# ── JSON Schema validation ──────────────────────────────────────────────────

def _validate_with_json_schema(
    data: dict, json_schema: dict, label: str
) -> List[str]:
    """Validate *data* against *json_schema* and return human-readable issues."""
    try:
        import jsonschema  # already installed (chromadb dependency)
    except ImportError:
        return [f" `jsonschema` package not installed — skipping {label} validation."]

    issues: List[str] = []
    validator = jsonschema.Draft201909Validator(json_schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        issues.append(f" **{label}** `{path}`: {error.message}")

    return issues


# ── Generic structural checks ───────────────────────────────────────────────

def _generic_checks(data: dict, level: str) -> List[str]:
    """Level-agnostic sanity checks on the model data."""
    issues: List[str] = []

    if level == "conceptual":
        _check_conceptual(data, issues)
    elif level == "logical":
        _check_logical(data, issues)
    elif level == "physical":
        _check_physical(data, issues)

    return issues


def _check_conceptual(data: dict, issues: List[str]) -> None:
    entities = data.get("entities", [])
    if not isinstance(entities, list):
        entities = []
    relationships = data.get("relationships", [])
    if not isinstance(relationships, list):
        relationships = []

    # Duplicate entity names
    names = [e.get("name", "") for e in entities if isinstance(e, dict)]
    for name in set(n for n in names if names.count(n) > 1):
        issues.append(f" Duplicate entity name: `{name}`.")

    # Every entity should have at least one key attribute
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        attrs = ent.get("attributes", [])
        if not isinstance(attrs, list):
            attrs = []
        has_key = any(a.get("isKey") for a in attrs if isinstance(a, dict))
        if not has_key and ent.get("kind", "strong") == "strong":
            issues.append(
                f" Entity `{ent.get('name')}` (strong) has no key attribute."
            )

    # Relationship ends reference valid entity IDs
    entity_ids = {e.get("id") for e in entities if isinstance(e, dict)}
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        for end in rel.get("ends", []):
            if not isinstance(end, dict):
                continue
            eid = end.get("entityId")
            if eid and eid not in entity_ids:
                issues.append(
                    f" Relationship `{rel.get('name')}` references "
                    f"non-existent entity `{eid}`."
                )


def _check_logical(data: dict, issues: List[str]) -> None:
    tables = data.get("tables", [])
    if not isinstance(tables, list):
        tables = []

    # Duplicate table names
    names = [t.get("name", "") for t in tables if isinstance(t, dict)]
    for name in set(n for n in names if names.count(n) > 1):
        issues.append(f" Duplicate table name: `{name}`.")

    table_ids = {t.get("id") for t in tables if isinstance(t, dict)}
    col_index: Dict[str, set] = {}
    for t in tables:
        if not isinstance(t, dict):
            continue
        cols = t.get("columns", [])
        if not isinstance(cols, list):
            cols = []
        col_index[t.get("id", "")] = {
            c.get("id") for c in cols if isinstance(c, dict)
        }

    for table in tables:
        if not isinstance(table, dict):
            continue
        columns = table.get("columns", [])
        if not isinstance(columns, list):
            columns = []
        tname = table.get("name", "?")

        # Every table should have at least one PK column
        has_pk = any(
            c.get("roles", {}).get("primaryKey") for c in columns if isinstance(c, dict)
        )
        if not has_pk:
            issues.append(f" Table `{tname}` has no primary key column.")

        # FK references must point to valid tables/columns
        for col in columns:
            if not isinstance(col, dict):
                continue
            fk = col.get("roles", {}).get("foreignKey")
            if fk and isinstance(fk, dict):
                ref_tid = fk.get("refTableId")
                ref_cid = fk.get("refColumnId")
                if ref_tid and ref_tid not in table_ids:
                    issues.append(
                        f" FK `{tname}.{col.get('name')}` references "
                        f"non-existent table `{ref_tid}`."
                    )
                elif ref_cid and ref_cid not in col_index.get(ref_tid, set()):
                    issues.append(
                        f" FK `{tname}.{col.get('name')}` references "
                        f"non-existent column `{ref_cid}` in `{ref_tid}`."
                    )


def _check_physical(data: dict, issues: List[str]) -> None:
    databases = data.get("databases", [])
    if not isinstance(databases, list):
        databases = []
    for db in databases:
        if not isinstance(db, dict):
            continue
        for schema in db.get("schemas", []):
            if not isinstance(schema, dict):
                continue
            tables = schema.get("tables", [])
            if not isinstance(tables, list):
                tables = []
            names = [t.get("name", "") for t in tables if isinstance(t, dict)]
            for name in set(n for n in names if names.count(n) > 1):
                issues.append(
                    f" Duplicate table name in schema "
                    f"`{schema.get('name')}`: `{name}`."
                )


# ── Node ─────────────────────────────────────────────────────────────────────


def _run_validation(
    raw_model: dict,
    raw_diagram: Optional[dict],
    level: str,
) -> List[str]:
    """Synchronous validation — runs inside ``asyncio.to_thread``.

    This keeps all blocking I/O (file reads, ``import jsonschema``) off
    the async event loop.
    """
    all_issues: List[str] = []

    # 1) JSON Schema validation — model
    model_schema = _load_json_schema(level, "model")
    if model_schema:
        all_issues.extend(
            _validate_with_json_schema(raw_model, model_schema, "model.json")
        )

    # 2) Diagram validation is skipped — diagram is built by the front-end.

    # 3) Generic structural checks
    all_issues.extend(_generic_checks(raw_model, level))

    return all_issues


async def validator_node(state: AgentState) -> Dict[str, Any]:
    """Validate the current schema_model (and optionally ui_diagram).

    Runs both JSON Schema validation (if the spec file exists) and generic
    structural checks.  All blocking work is offloaded to a thread.

    Returns ``validation_issues`` in state so the graph can route back to
    the generating node for a self-correction retry when issues are found.
    """
    raw_model = state.get("schema_model")
    level = state.get("current_level", "conceptual")

    if not raw_model:
        return {
            "messages": [AIMessage(content="No schema to validate.")],
            "validation_issues": [],
            "retry_count": 0,
        }

    # Run all blocking validation in a separate thread
    all_issues = await asyncio.to_thread(
        _run_validation, raw_model, None, level
    )

    if not all_issues:
        # Validation passed — no message needed, the schema node already sent one.
        return {
            "validation_issues": [],
            "retry_count": 0,
        }

    current_retry = state.get("retry_count", 0)
    new_retry_count = current_retry + 1
    max_retries = int(os.getenv("VALIDATION_MAX_RETRIES", "2"))

    if new_retry_count > max_retries:
        # Retries exhausted — show full issue list as a warning.
        details = "\n".join(f"- {issue}" for issue in all_issues)
        msg = (
            f"Schema has {len(all_issues)} validation issue(s) that could not be "
            f"auto-corrected after {max_retries} attempt(s):\n\n{details}"
        )
    else:
        # Will retry — show brief message only, not the full error list.
        msg = (
            f"Found {len(all_issues)} validation issue(s), "
            f"auto-correcting schema (attempt {new_retry_count}/{max_retries})..."
        )

    return {
        "messages": [AIMessage(content=msg)],
        "validation_issues": all_issues,
        "retry_count": new_retry_count,
    }
