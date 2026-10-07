"""Deterministic post-processing for AI-generated seed-data SQL.

The LLM is good at inventing realistic-looking values but unreliable at the
mechanical parts of a seed-data batch: keeping every primary key/unique value
distinct, and inserting parent-table rows before the child rows whose foreign
keys reference them. Both are fully determined by ``schema_model`` (which
columns are ``roles.primaryKey``/``unique``, which are ``roles.foreignKey``),
so this module re-derives them in code after generation instead of hoping the
model's own text obeys the prompt's rules:

1. Walks tables in foreign-key dependency order (parents before children) and,
   for each row, either (a) copies a foreign-key value or composite tuple from
   whatever its referenced parent row was just reassigned to, or (b) assigns
   standalone unique keys and the local portion of a primary key fresh values
   (sequential ints for numeric columns, deduped-with-suffix for text columns).
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
from typing import Any, Dict, List, NamedTuple, Set, Tuple

logger = logging.getLogger(__name__)

# (is_string, literal value) — cheap hashable identity for a sqlglot Literal.
LiteralKey = Tuple[bool, str]
KeyGroup = Tuple[str, ...]


class ForeignKeyGroup(NamedTuple):
    """One single- or multi-column FK, ordered by the parent key columns."""

    source_columns: KeyGroup
    parent_table: str
    parent_columns: KeyGroup


def _index_schema(
    schema_model: dict,
) -> Tuple[
    Dict[str, KeyGroup],
    Dict[str, List[KeyGroup]],
    Dict[str, Set[str]],
    Dict[str, List[ForeignKeyGroup]],
]:
    """Index primary/unique keys and infer composite FK groups.

    Physical model metadata lives on individual columns. Several columns that
    reference every distinct column of the same parent composite key represent
    one composite FK. Repeated references to one target column remain separate
    single-column FKs (for example ``created_by`` and ``updated_by``).
    """
    id_to_column: Dict[str, Tuple[str, str]] = {}
    primary_keys: Dict[str, KeyGroup] = {}
    key_groups: Dict[str, List[KeyGroup]] = {}
    single_unique_columns: Dict[str, Set[str]] = {}
    raw_foreign_keys: Dict[str, List[Tuple[str, str, str]]] = {}

    for table in schema_model.get("tables", []) or []:
        if not isinstance(table, dict):
            continue
        tname = (table.get("name") or "").lower()
        if not tname:
            continue
        for col in table.get("columns", []) or []:
            if isinstance(col, dict) and col.get("id") and col.get("name"):
                id_to_column[col["id"]] = (tname, col["name"].lower())

    for table in schema_model.get("tables", []) or []:
        if not isinstance(table, dict):
            continue
        tname = (table.get("name") or "").lower()
        if not tname:
            continue
        primary_key: List[str] = []
        for col in table.get("columns", []) or []:
            if not isinstance(col, dict):
                continue
            cname = (col.get("name") or "").lower()
            if not cname:
                continue
            roles = col.get("roles") or {}
            if roles.get("primaryKey"):
                primary_key.append(cname)
            if col.get("unique"):
                single_unique_columns.setdefault(tname, set()).add(cname)
            fk = roles.get("foreignKey")
            if fk:
                parent = id_to_column.get(fk.get("refColumnId"))
                if parent:
                    parent_table, parent_column = parent
                    raw_foreign_keys.setdefault(tname, []).append(
                        (cname, parent_table, parent_column)
                    )

        if primary_key:
            primary_keys[tname] = tuple(primary_key)
            key_groups.setdefault(tname, []).append(tuple(primary_key))

        for idx in table.get("indexes", []) or []:
            if not isinstance(idx, dict) or not idx.get("isUnique"):
                continue
            idx_columns = idx.get("columns", []) or []
            column_names = tuple(
                (item.get("columnName") or "").lower()
                for item in idx_columns
                if isinstance(item, dict) and item.get("columnName")
            )
            if not column_names:
                continue
            if column_names not in key_groups.setdefault(tname, []):
                key_groups[tname].append(column_names)
            if len(column_names) == 1:
                single_unique_columns.setdefault(tname, set()).add(
                    column_names[0]
                )

        for column_name in single_unique_columns.get(tname, set()):
            group = (column_name,)
            if group not in key_groups.setdefault(tname, []):
                key_groups[tname].append(group)

    foreign_key_groups: Dict[str, List[ForeignKeyGroup]] = {}
    for child_table, references in raw_foreign_keys.items():
        references_by_parent: Dict[str, List[Tuple[str, str]]] = {}
        for source_column, parent_table, parent_column in references:
            references_by_parent.setdefault(parent_table, []).append(
                (source_column, parent_column)
            )

        for parent_table, parent_references in references_by_parent.items():
            candidate_groups: List[List[Tuple[str, str]]] = []
            for reference in parent_references:
                _source_column, parent_column = reference
                candidate = next(
                    (
                        group
                        for group in candidate_groups
                        if all(item[1] != parent_column for item in group)
                    ),
                    None,
                )
                if candidate is None:
                    candidate_groups.append([reference])
                else:
                    candidate.append(reference)

            for candidate in candidate_groups:
                referenced_columns = {item[1] for item in candidate}
                matching_parent_key = next(
                    (
                        group
                        for group in key_groups.get(parent_table, [])
                        if len(group) > 1
                        and len(group) == len(candidate)
                        and set(group) == referenced_columns
                    ),
                    None,
                )
                if matching_parent_key:
                    source_by_parent = {
                        parent_column: source_column
                        for source_column, parent_column in candidate
                    }
                    foreign_key_groups.setdefault(child_table, []).append(
                        ForeignKeyGroup(
                            tuple(
                                source_by_parent[column]
                                for column in matching_parent_key
                            ),
                            parent_table,
                            matching_parent_key,
                        )
                    )
                    continue

                for source_column, parent_column in candidate:
                    foreign_key_groups.setdefault(child_table, []).append(
                        ForeignKeyGroup(
                            (source_column,), parent_table, (parent_column,)
                        )
                    )

    return (
        primary_keys,
        key_groups,
        single_unique_columns,
        foreign_key_groups,
    )


def _table_parent_map(
    foreign_key_groups: Dict[str, List[ForeignKeyGroup]],
) -> Dict[str, Set[str]]:
    parents: Dict[str, Set[str]] = {}
    for child_table, groups in foreign_key_groups.items():
        for group in groups:
            if group.parent_table != child_table:
                parents.setdefault(child_table, set()).add(group.parent_table)
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

    (
        primary_keys,
        key_groups,
        single_unique_columns,
        foreign_key_groups,
    ) = _index_schema(schema_model)

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

    table_order, cyclic_tables = _topo_sort_tables(
        tables_present, _table_parent_map(foreign_key_groups), first_seen
    )

    # --- Reassign values, walking tables in parent-first order so a child's
    # FK columns can always find their parent's already-decided new value. ---
    random_base = random.randint(100_000, 999_999)
    counters: Dict[Tuple[str, str], int] = {}
    seen_text: Dict[Tuple[str, str], Set[str]] = {}
    # (table, ordered key columns) -> {old tuple: new tuple}. Composite keys
    # must be mapped as tuples: mapping each component independently loses the
    # association when a component value repeats in several parent rows.
    key_remaps: Dict[
        Tuple[str, KeyGroup], Dict[Tuple[LiteralKey, ...], Tuple[LiteralKey, ...]]
    ] = {}

    rows_by_table: Dict[str, List[Dict[str, Any]]] = {}
    for p in parsed:
        if p["table"]:
            rows_by_table.setdefault(p["table"], []).append(p)

    for table in table_order:
        table_fk_groups = foreign_key_groups.get(table, [])
        foreign_key_columns = {
            column
            for group in table_fk_groups
            for column in group.source_columns
        }
        columns_to_regenerate = set(single_unique_columns.get(table, set()))
        local_primary_key_columns = [
            column
            for column in primary_keys.get(table, ())
            if column not in foreign_key_columns
        ]
        if local_primary_key_columns:
            # One fresh local component is sufficient to make a composite PK
            # tuple fresh. Regenerating every component would incorrectly
            # impose per-column uniqueness on a composite key.
            columns_to_regenerate.add(local_primary_key_columns[0])
        columns_to_regenerate.difference_update(foreign_key_columns)

        for p in rows_by_table.get(table, []):
            cols = p["columns"]
            for row in p["rows"]:
                if not isinstance(row, exp.Tuple):
                    continue
                expressions = {
                    column: row.expressions[index]
                    for index, column in enumerate(cols)
                    if index < len(row.expressions)
                    and isinstance(row.expressions[index], exp.Literal)
                }
                original_values: Dict[str, LiteralKey] = {
                    column: (literal.is_string, literal.this)
                    for column, literal in expressions.items()
                }

                # Propagate parent key changes one FK tuple at a time.
                for group in table_fk_groups:
                    if not all(
                        column in original_values
                        for column in group.source_columns
                    ):
                        continue
                    old_tuple = tuple(
                        original_values[column]
                        for column in group.source_columns
                    )
                    new_tuple = key_remaps.get(
                        (group.parent_table, group.parent_columns), {}
                    ).get(old_tuple)
                    if new_tuple is None:
                        continue  # likely references a pre-existing parent row
                    for column, new_value in zip(
                        group.source_columns, new_tuple
                    ):
                        literal = expressions[column]
                        literal.set("is_string", new_value[0])
                        literal.set("this", new_value[1])

                # Regenerate standalone unique keys and only the non-FK parts
                # of a PK. For a composite PK this deliberately permits one
                # component to repeat; uniqueness belongs to the whole tuple.
                for column in columns_to_regenerate:
                    literal = expressions.get(column)
                    if literal is None:
                        continue
                    counter_key = (table, column)
                    if not literal.is_string:
                        n = counters.get(counter_key, random_base)
                        counters[counter_key] = n + 1
                        new_value = (False, str(n))
                    else:
                        bucket = seen_text.setdefault(counter_key, set())
                        candidate = f"{literal.this}-{uuid.uuid4().hex[:6]}"
                        while candidate in bucket:
                            candidate = f"{literal.this}-{uuid.uuid4().hex[:6]}"
                        bucket.add(candidate)
                        new_value = (True, candidate)
                    literal.set("is_string", new_value[0])
                    literal.set("this", new_value[1])

                # Publish tuple mappings after FK propagation and local-key
                # generation so dependent tables receive the final values.
                for key_group in key_groups.get(table, []):
                    if not all(column in original_values for column in key_group):
                        continue
                    old_tuple = tuple(
                        original_values[column] for column in key_group
                    )
                    new_tuple = tuple(
                        (expressions[column].is_string, expressions[column].this)
                        for column in key_group
                    )
                    key_remaps.setdefault((table, key_group), {})[
                        old_tuple
                    ] = new_tuple

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
