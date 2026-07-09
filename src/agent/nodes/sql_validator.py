"""SQL Validator node — checks generated SQL against the physical schema_model.

Shared by ``text_to_sql`` (expects exactly one statement) and ``seed_data``
(expects one or more INSERT-only statements). Three layers of validation:
  1. Syntax — each statement parsed with ``sqlglot`` against the target DBMS dialect.
  2. Statement shape — intent-specific constraints (single statement / INSERT-only).
  3. Identifiers — every referenced table/column must exist in ``schema_model``,
     including INSERT's explicit column list (modeled by sqlglot as bare
     ``Identifier`` nodes under ``Insert.this``, not ``exp.Column``).

Column checks are best-effort: unqualified columns in a multi-table query,
``SELECT *``, and expressions are skipped rather than false-flagged, since a
false positive here would waste a retry attempt on valid SQL.

All blocking work (``sqlglot`` parsing) runs in ``asyncio.to_thread`` so the
LangGraph ASGI event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Set

from langchain_core.messages import AIMessage

from agent.models import UserIntent
from agent.state import AgentState

logger = logging.getLogger(__name__)

_DIALECT_MAP = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "sqlserver": "tsql",
}


def _schema_identifiers(schema_model: dict) -> tuple[Set[str], Dict[str, Set[str]]]:
    """Return (lower-cased table names, {table_name_lower: {column_name_lower}})."""
    tables: Set[str] = set()
    columns_by_table: Dict[str, Set[str]] = {}
    for table in schema_model.get("tables", []) or []:
        if not isinstance(table, dict):
            continue
        tname = (table.get("name") or "").lower()
        if not tname:
            continue
        tables.add(tname)
        columns_by_table[tname] = {
            (c.get("name") or "").lower()
            for c in table.get("columns", []) or []
            if isinstance(c, dict) and c.get("name")
        }
    return tables, columns_by_table


def _validate_statement(
    stmt: Any,
    dialect: str,
    tables: Set[str],
    columns_by_table: Dict[str, Set[str]],
    require_insert_only: bool,
    exp: Any,
) -> List[str]:
    """Validate a single parsed statement — shape + identifier checks."""
    issues: List[str] = []

    # sqlglot's parser is lenient — garbled keywords (e.g. "SELEKT ... FORM")
    # can still parse into a generic expression instead of raising. Require
    # the top-level result to actually be a query/DML statement.
    if not isinstance(stmt, (exp.Query, exp.DML)):
        issues.append(f" Not a valid SQL statement for dialect '{dialect}': `{stmt.sql()[:120]}`.")
        return issues

    if require_insert_only and not isinstance(stmt, exp.Insert):
        issues.append(f" Expected an INSERT statement, got: `{stmt.sql()[:120]}`.")
        return issues

    if not tables:
        return issues  # nothing to check identifiers against

    # Collect referenced tables + build an alias -> real-table-name map so
    # `SELECT u.name FROM users u` resolves `u` back to `users`.
    referenced_tables: Set[str] = set()
    alias_map: Dict[str, str] = {}
    for t in stmt.find_all(exp.Table):
        real_name = t.name.lower()
        if not real_name:
            continue
        referenced_tables.add(real_name)
        alias_key = (t.alias_or_name or real_name).lower()
        alias_map[alias_key] = real_name

    for tname in referenced_tables:
        if tname not in tables:
            issues.append(f" References unknown table `{tname}`.")

    single_table = next(iter(referenced_tables)) if len(referenced_tables) == 1 else None

    # INSERT's explicit column list — sqlglot models it as bare `Identifier`
    # nodes under `Insert.this` (a `Schema`), NOT as `exp.Column` nodes, so
    # the general exp.Column walk below never sees them.
    if isinstance(stmt, exp.Insert) and isinstance(stmt.this, exp.Schema):
        insert_table = (
            stmt.this.this.name.lower()
            if isinstance(stmt.this.this, exp.Table)
            else single_table
        )
        if insert_table and insert_table in tables:
            for ident in stmt.this.expressions:
                col_name = ident.name.lower()
                if col_name not in columns_by_table.get(insert_table, set()):
                    issues.append(f" References unknown column `{insert_table}.{col_name}`.")

    for col in stmt.find_all(exp.Column):
        raw_ref = col.table.lower() if col.table else None
        if raw_ref:
            table_ref = alias_map.get(raw_ref, raw_ref)
        elif single_table:
            table_ref = single_table
        else:
            continue  # ambiguous unqualified column in a multi-table query — skip

        if table_ref not in tables:
            continue  # already reported as an unknown table above

        col_name = col.name.lower()
        if col_name not in columns_by_table.get(table_ref, set()):
            issues.append(f" References unknown column `{table_ref}.{col_name}`.")

    return issues


def _validate_sql(
    sql: str,
    dialect: str,
    schema_model: dict,
    require_insert_only: bool,
    expect_single_statement: bool,
) -> List[str]:
    """Run sqlglot syntax parsing + identifier existence checks (blocking)."""
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        return [" `sqlglot` package not installed — skipping SQL validation."]

    try:
        statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    except Exception as e:
        return [f" SQL syntax error for dialect '{dialect}': {e}"]

    if not statements:
        return [" No SQL statement found in the response."]

    issues: List[str] = []
    if expect_single_statement and len(statements) != 1:
        issues.append(f" Expected exactly one SQL statement, found {len(statements)}.")

    tables, columns_by_table = _schema_identifiers(schema_model)
    for stmt in statements:
        issues.extend(
            _validate_statement(stmt, dialect, tables, columns_by_table, require_insert_only, exp)
        )

    return issues


async def sql_validator_node(state: AgentState) -> Dict[str, Any]:
    """Validate the generated SQL against schema_model and target dialect syntax.

    Returns ``validation_issues`` in state so the graph can route back to
    ``sql_generator`` for a self-correction retry when issues are found —
    reuses the same ``validation_issues``/``retry_count`` fields and
    ``VALIDATION_MAX_RETRIES`` cap as the schema validator.
    """
    sql = state.get("generated_sql")
    schema_model = state.get("schema_model") or {}

    if not sql:
        return {
            "messages": [AIMessage(content="No SQL was generated to validate.")],
            "validation_issues": [],
            "retry_count": 0,
        }

    target_dbms = state.get("target_dbms") or (schema_model.get("model") or {}).get("dbms") or "postgresql"
    dialect = _DIALECT_MAP.get(target_dbms, "postgres")
    is_seed_data = state.get("user_intent") == UserIntent.SEED_DATA.value

    all_issues = await asyncio.to_thread(
        _validate_sql,
        sql,
        dialect,
        schema_model,
        is_seed_data,       # require_insert_only
        not is_seed_data,   # expect_single_statement (only for text_to_sql)
    )

    if not all_issues:
        return {
            "validation_issues": [],
            "retry_count": 0,
        }

    current_retry = state.get("retry_count", 0)
    new_retry_count = current_retry + 1
    max_retries = int(os.getenv("VALIDATION_MAX_RETRIES", "2"))

    if new_retry_count > max_retries:
        details = "\n".join(f"- {issue}" for issue in all_issues)
        msg = (
            f"Generated SQL has {len(all_issues)} issue(s) that could not be "
            f"auto-corrected after {max_retries} attempt(s):\n\n{details}"
        )
    else:
        msg = (
            f"Found {len(all_issues)} issue(s) in the generated SQL, "
            f"auto-correcting (attempt {new_retry_count}/{max_retries})..."
        )

    return {
        "messages": [AIMessage(content=msg)],
        "validation_issues": all_issues,
        "retry_count": new_retry_count,
    }
