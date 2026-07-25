"""Deterministic post-processing for AI-generated seed-data SQL.

The LLM is good at inventing realistic-looking values but unreliable at the
mechanical parts of a seed-data batch: keeping every primary key/unique value
distinct, and inserting parent-table rows before the child rows whose foreign
keys reference them. Both are fully determined by ``schema_model`` (which
columns are ``roles.primaryKey``/``unique``, which are ``roles.foreignKey``),
so this module re-derives them in code after generation instead of hoping the
model's own text obeys the prompt's rules:

1. Walks tables in foreign-key dependency order (parents before children) and,
   for each row, either (a) copies a foreign-key column's value from whatever
   its referenced parent row was just reassigned to, or (b) if the column is
   its own table's primary key/unique column (and not also an FK — covers the
   shared PK/FK "sub-type" pattern, e.g. `student.student_id` referencing
   `users.id`), assigns it a fresh guaranteed-unique value (sequential ints
   for numeric columns, deduped-with-suffix for text columns).
2. Reorders the INSERT statements themselves to match that same dependency
   order, so a referenced (parent) table's rows always precede any table
   whose FK points to it — regardless of what order the LLM wrote them in.

Best-effort throughout: any statement/table/column this can't confidently
interpret (e.g. a non-Insert statement, a bare `INSERT ... SELECT`, an FK
value that doesn't match any row in this batch — presumably referencing a
pre-existing row) is left completely untouched. This only tightens up
seed_data's own INSERT-literal shape; it never invents or drops SQL.
"""

from __future__ import annotations

import heapq
import logging
import random
import uuid
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# (is_string, literal value) — cheap hashable identity for a sqlglot Literal.
LiteralKey = Tuple[bool, str]


def _index_schema(schema_model: dict) -> Tuple[Dict[str, Set[str]], Dict[Tuple[str, str], Tuple[str, str]]]:
    """Derive key and foreign-key column indexes from the schema model.

    - key_columns: {table_lower: {column_lower, ...}} — PK or unique columns.
    - fk_columns: {(child_table_lower, child_column_lower): (parent_table_lower, parent_column_lower)}
    """
    id_to_column: Dict[str, Tuple[str, str]] = {}
    for table in schema_model.get("tables", []) or []:
        if not isinstance(table, dict):
            continue
        tname = (table.get("name") or "").lower()
        if not tname:
            continue
        for col in table.get("columns", []) or []:
            if isinstance(col, dict) and col.get("id") and col.get("name"):
                id_to_column[col["id"]] = (tname, col["name"].lower())

    key_columns: Dict[str, Set[str]] = {}
    fk_columns: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for table in schema_model.get("tables", []) or []:
        if not isinstance(table, dict):
            continue
        tname = (table.get("name") or "").lower()
        if not tname:
            continue
        for col in table.get("columns", []) or []:
            if not isinstance(col, dict):
                continue
            cname = (col.get("name") or "").lower()
            if not cname:
                continue
            roles = col.get("roles") or {}
            if roles.get("primaryKey") or col.get("unique"):
                key_columns.setdefault(tname, set()).add(cname)
            fk = roles.get("foreignKey")
            if fk:
                parent = id_to_column.get(fk.get("refColumnId"))
                if parent:
                    fk_columns[(tname, cname)] = parent

        # Uniqueness can also come from a standalone index (`isUnique: true`)
        # instead of the column's own `unique` flag — e.g. `categories.name`
        # enforced via `CREATE UNIQUE INDEX ... ON categories (name)` rather
        # than an inline column constraint. Only single-column unique indexes
        # are treated as a key column here: for a composite one (e.g.
        # `unique(user_id, product_id)`), forcing each column independently
        # unique would be wrong — it'd break legitimate repeats of one column
        # across different rows, which is exactly what a composite constraint
        # is meant to still allow.
        for idx in table.get("indexes", []) or []:
            if not isinstance(idx, dict) or not idx.get("isUnique"):
                continue
            idx_columns = idx.get("columns", []) or []
            if len(idx_columns) != 1:
                continue
            col_name = (idx_columns[0].get("columnName") or "").lower()
            if col_name:
                key_columns.setdefault(tname, set()).add(col_name)

    return key_columns, fk_columns


def _table_parent_map(fk_columns: Dict[Tuple[str, str], Tuple[str, str]]) -> Dict[str, Set[str]]:
    parents: Dict[str, Set[str]] = {}
    for (child_table, _child_col), (parent_table, _parent_col) in fk_columns.items():
        if parent_table != child_table:
            parents.setdefault(child_table, set()).add(parent_table)
    return parents


def _topo_sort_tables(
    tables: List[str], parent_map: Dict[str, Set[str]], first_seen: Dict[str, int]
) -> Tuple[List[str], Set[str]]:
    """Sort tables stably with parents before children.

    Ties are broken by each table's first occurrence in the original SQL.
    Returns (order, cyclic) —
    ``cyclic`` holds any tables that couldn't be placed at all because they sit
    on a genuine FK cycle (e.g. two tables each with a column FK-ing the
    other) — no INSERT order can satisfy that, so it's surfaced to the caller
    as a likely schema-modeling mistake rather than silently misordered.
    """
    children: Dict[str, Set[str]] = {t: set() for t in tables}
    in_degree: Dict[str, int] = {t: 0 for t in tables}
    for child in tables:
        for parent in parent_map.get(child, set()):
            if parent in children and parent != child:
                children[parent].add(child)

    for parent, kids in children.items():
        for kid in kids:
            in_degree[kid] += 1

    ready = [(first_seen[t], t) for t in tables if in_degree[t] == 0]
    heapq.heapify(ready)

    order: List[str] = []
    remaining_in_degree = dict(in_degree)
    while ready:
        _, t = heapq.heappop(ready)
        order.append(t)
        for kid in children[t]:
            remaining_in_degree[kid] -= 1
            if remaining_in_degree[kid] == 0:
                heapq.heappush(ready, (first_seen[kid], kid))

    cyclic = {t for t in tables if t not in order}
    if cyclic:
        leftover = sorted(cyclic, key=lambda t: first_seen[t])
        order.extend(leftover)

    return order, cyclic


def postprocess_seed_sql(sql: str, schema_model: dict, dialect: str) -> Tuple[str, Set[str]]:
    """Rewrite AI-generated seed-data SQL for valid keys and insert order.

    PK/unique values are made distinct and INSERTs respect FK dependency order.
    Returns ``(sql, cyclic_tables)``
    — ``cyclic_tables`` is non-empty when some tables sit on a genuine FK cycle
    that no insert order can satisfy (a likely schema-modeling mistake, e.g. an
    FK drawn between the wrong columns), so the caller can warn the user instead
    of leaving them to debug a bare "FOREIGN KEY constraint failed" at execution
    time. Returns the original ``sql`` unchanged (with an empty cyclic set) if
    parsing fails or there's nothing to fix — any real problem this can't handle
    still falls through to sql_validator's checks and self-correction retry loop.
    """
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        return sql, set()

    try:
        statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    except Exception:
        return sql, set()

    if not any(isinstance(s, exp.Insert) for s in statements):
        return sql, set()

    key_columns, fk_columns = _index_schema(schema_model)

    parsed: List[Dict[str, Any]] = []
    for idx, stmt in enumerate(statements):
        if not isinstance(stmt, exp.Insert):
            parsed.append({"idx": idx, "stmt": stmt, "table": None, "columns": [], "rows": []})
            continue
        table_node = stmt.this.this if isinstance(stmt.this, exp.Schema) else stmt.this
        table_name = table_node.name.lower() if isinstance(table_node, exp.Table) else None
        columns = (
            [c.name.lower() for c in stmt.this.expressions]
            if isinstance(stmt.this, exp.Schema)
            else []
        )
        values_node = stmt.expression
        rows = list(values_node.expressions) if isinstance(values_node, exp.Values) else []
        parsed.append({"idx": idx, "stmt": stmt, "table": table_name, "columns": columns, "rows": rows})

    tables_present: List[str] = []
    first_seen: Dict[str, int] = {}
    for p in parsed:
        if p["table"] and p["table"] not in first_seen:
            first_seen[p["table"]] = p["idx"]
            tables_present.append(p["table"])

    table_order, cyclic_tables = _topo_sort_tables(tables_present, _table_parent_map(fk_columns), first_seen)

    # --- Reassign values, walking tables in parent-first order so a child's
    # FK columns can always find their parent's already-decided new value. ---
    random_base = random.randint(100_000, 999_999)
    counters: Dict[Tuple[str, str], int] = {}
    seen_text: Dict[Tuple[str, str], Set[str]] = {}
    # (table, column) -> {old_literal_key: new_literal_key} — read by child
    # tables' FK columns to propagate a parent's reassigned value.
    remap: Dict[Tuple[str, str], Dict[LiteralKey, LiteralKey]] = {}

    rows_by_table: Dict[str, List[Dict[str, Any]]] = {}
    for p in parsed:
        if p["table"]:
            rows_by_table.setdefault(p["table"], []).append(p)

    for table in table_order:
        for p in rows_by_table.get(table, []):
            cols = p["columns"]
            for row in p["rows"]:
                if not isinstance(row, exp.Tuple):
                    continue
                for col_idx, col_name in enumerate(cols):
                    if col_idx >= len(row.expressions):
                        continue
                    lit = row.expressions[col_idx]
                    if not isinstance(lit, exp.Literal):
                        continue
                    old_key: LiteralKey = (lit.is_string, lit.this)

                    parent = fk_columns.get((table, col_name))
                    if parent is not None:
                        new_key = remap.get(parent, {}).get(old_key)
                        if new_key is None:
                            continue  # references a row outside this batch — leave as-is
                        is_string, new_val = new_key
                        lit.set("this", new_val)
                        lit.set("is_string", is_string)
                        if table in key_columns and col_name in key_columns[table]:
                            remap.setdefault((table, col_name), {})[old_key] = new_key
                        continue

                    if table in key_columns and col_name in key_columns[table]:
                        key = (table, col_name)
                        if not lit.is_string:
                            n = counters.get(key, random_base)
                            counters[key] = n + 1
                            new_key = (False, str(n))
                        else:
                            # Always append a random suffix — never just when a
                            # duplicate is seen within this batch. This module
                            # has no visibility into rows already sitting in the
                            # sandbox from earlier runs, and small-vocabulary
                            # text columns (surnames, common category names,
                            # etc.) collide with that pre-existing data far more
                            # often than with anything else in the same batch.
                            bucket = seen_text.setdefault(key, set())
                            candidate = f"{lit.this}-{uuid.uuid4().hex[:6]}"
                            while candidate in bucket:
                                candidate = f"{lit.this}-{uuid.uuid4().hex[:6]}"
                            bucket.add(candidate)
                            new_key = (True, candidate)
                        remap.setdefault(key, {})[old_key] = new_key
                        lit.set("this", new_key[1])
                        lit.set("is_string", new_key[0])

    # --- Reorder statements to match the same parent-first table order. ---
    order_rank = {t: i for i, t in enumerate(table_order)}
    # Statements for unrecognized tables keep their original relative order,
    # placed after every recognized table.
    parsed.sort(key=lambda p: (order_rank.get(p["table"], len(table_order)), p["idx"]))

    try:
        return ";\n".join(p["stmt"].sql(dialect=dialect) for p in parsed) + ";", cyclic_tables
    except Exception:
        logger.warning("Failed to regenerate SQL after seed-data postprocessing; returning original.")
        return sql, cyclic_tables
