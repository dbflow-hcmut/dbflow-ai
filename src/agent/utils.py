"""Utility functions — diagram layout, helpers, etc."""

from __future__ import annotations

import math

from agent.models import (
    DiagramEdge,
    DiagramModel,
    DiagramNode,
    Position,
    RelationType,
    SchemaModel,
    Viewport,
)

# Layout constants
NODE_WIDTH = 220
FIELD_ROW_HEIGHT = 28
NODE_HEADER_HEIGHT = 44
NODE_PADDING = 16
GAP_X = 300
GAP_Y = 60


def _compute_node_height(field_count: int) -> float:
    """Calculate the pixel height of a table node based on its field count."""
    return NODE_HEADER_HEIGHT + NODE_PADDING + max(field_count, 1) * FIELD_ROW_HEIGHT


def _cardinality_label(rel_type: RelationType) -> str:
    """Return a human-readable label for a relationship type."""
    return {
        RelationType.ONE_TO_ONE: "1:1",
        RelationType.ONE_TO_MANY: "1:N",
        RelationType.MANY_TO_MANY: "N:N",
    }.get(rel_type, "")


def compute_diagram_layout(schema: SchemaModel) -> DiagramModel:
    """Compute a grid-based auto-layout for the given schema.

    Tables are arranged in a grid with ``cols`` columns, distributing
    them as evenly as possible to keep the layout roughly square.
    """
    tables = schema.tables
    n = len(tables)
    if n == 0:
        return DiagramModel()

    cols = max(1, math.ceil(math.sqrt(n)))

    nodes: list[DiagramNode] = []
    for idx, table in enumerate(tables):
        row, col = divmod(idx, cols)
        height = _compute_node_height(len(table.fields))
        nodes.append(
            DiagramNode(
                id=table.id,
                position=Position(
                    x=col * (NODE_WIDTH + GAP_X),
                    y=row * (height + GAP_Y),
                ),
                width=NODE_WIDTH,
                height=height,
            )
        )

    edges: list[DiagramEdge] = []
    for rel in schema.relationships:
        edges.append(
            DiagramEdge(
                id=rel.id,
                source=rel.source_table_id,
                target=rel.target_table_id,
                source_handle=rel.source_field_id,
                target_handle=rel.target_field_id,
                label=_cardinality_label(rel.type),
            )
        )

    return DiagramModel(
        nodes=nodes,
        edges=edges,
        viewport=Viewport(x=0, y=0, zoom=1.0),
    )
