"""Pydantic data models for Database Schema (model.json) and Diagram (diagram.json).

These models define the data contract between the AI agent and the UI.
Supports three schema levels: Conceptual, Logical, Physical.
"""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field

# ── Enums ────────────────────────────────────────────────────────────────────


class SchemaLevel(str, Enum):
    """Database design abstraction level."""

    CONCEPTUAL = "conceptual"
    LOGICAL = "logical"
    PHYSICAL = "physical"


class RelationType(str, Enum):
    """Cardinality between two tables/entities."""

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_MANY = "many_to_many"


class UserIntent(str, Enum):
    """Classified intent of the user request."""

    CREATE = "create"
    EDIT = "edit"
    CHAT = "chat"


# ── Schema Model (model.json) ───────────────────────────────────────────────


class ForeignKeyRef(BaseModel):
    """Reference to a field in another table (Foreign Key)."""

    table_id: str = Field(description="ID of the referenced table")
    field_id: str = Field(description="ID of the referenced field (usually PK)")


class SchemaField(BaseModel):
    """A single field / column in a table."""

    id: str = Field(description="Unique identifier for this field, e.g. 'users_id'")
    name: str = Field(description="Column name, e.g. 'id', 'email'")
    type: str = Field(
        default="",
        description="Data type. Empty for Conceptual level. "
        "e.g. 'INTEGER', 'VARCHAR(255)', 'TIMESTAMP'",
    )
    primary_key: bool = Field(default=False, description="Whether this is a PK")
    nullable: bool = Field(default=True, description="Whether NULL is allowed")
    unique: bool = Field(default=False, description="Whether values must be unique")
    default: str | None = Field(
        default=None, description="Default value expression"
    )
    foreign_key: ForeignKeyRef | None = Field(
        default=None, description="FK reference, if any"
    )


class Table(BaseModel):
    """A database table / entity."""

    id: str = Field(description="Unique identifier for this table, e.g. 'tbl_users'")
    name: str = Field(description="Table name, e.g. 'users'")
    fields: List[SchemaField] = Field(
        default_factory=list, description="Ordered list of columns"
    )


class Relationship(BaseModel):
    """A relationship / association between two tables."""

    id: str = Field(
        description="Unique identifier, e.g. 'rel_users_orders'"
    )
    name: str = Field(description="Human-readable name, e.g. 'user has many orders'")
    source_table_id: str = Field(description="ID of the source (parent) table")
    target_table_id: str = Field(description="ID of the target (child) table")
    source_field_id: str = Field(
        default="",
        description="ID of the source field (FK origin). Can be empty for conceptual.",
    )
    target_field_id: str = Field(
        default="",
        description="ID of the target field (FK destination). Can be empty for conceptual.",
    )
    type: RelationType = Field(description="Cardinality of the relationship")


class SchemaModel(BaseModel):
    """Complete database schema — the content of model.json."""

    tables: List[Table] = Field(default_factory=list, description="All tables")
    relationships: List[Relationship] = Field(
        default_factory=list, description="All relationships"
    )
    level: SchemaLevel = Field(
        default=SchemaLevel.LOGICAL, description="Current abstraction level"
    )


# ── Diagram Model (diagram.json) ────────────────────────────────────────────


class Position(BaseModel):
    """2-D coordinate for a diagram node."""

    x: float = 0.0
    y: float = 0.0


class DiagramNode(BaseModel):
    """Visual representation of a table on the diagram canvas."""

    id: str = Field(description="Same as corresponding Table.id")
    position: Position = Field(default_factory=Position)
    width: float = Field(default=220, description="Node width in px")
    height: float = Field(default=0, description="Auto-calculated from field count")


class DiagramEdge(BaseModel):
    """Visual representation of a relationship on the diagram canvas."""

    id: str = Field(description="Same as corresponding Relationship.id")
    source: str = Field(description="Source table ID")
    target: str = Field(description="Target table ID")
    source_handle: str = Field(
        default="", description="Source field ID (for handle positioning)"
    )
    target_handle: str = Field(
        default="", description="Target field ID (for handle positioning)"
    )
    label: str = Field(default="", description="Edge label (e.g. '1:N')")


class Viewport(BaseModel):
    """Camera / viewport state of the diagram canvas."""

    x: float = 0.0
    y: float = 0.0
    zoom: float = 1.0


class DiagramModel(BaseModel):
    """Complete diagram layout — the content of diagram.json."""

    nodes: List[DiagramNode] = Field(default_factory=list)
    edges: List[DiagramEdge] = Field(default_factory=list)
    viewport: Viewport = Field(default_factory=Viewport)


# ── Router output ────────────────────────────────────────────────────────────


class RouterOutput(BaseModel):
    """Structured output from the Router node."""

    intent: UserIntent = Field(description="Detected user intent")
    detected_level: str | None = Field(
        default=None,
        description=(
            "Schema level detected from the user message. "
            "One of: 'conceptual', 'logical', 'physical', or null if not mentioned."
        ),
    )
    detected_dbms: str | None = Field(
        default=None,
        description=(
            "Target DBMS detected from the user message. "
            "One of: 'postgresql', 'mysql', 'sqlserver', or null if not mentioned. "
            "Map common aliases: 'postgres'/'pg' -> 'postgresql', "
            "'sql server'/'mssql' -> 'sqlserver'."
        ),
    )
    reasoning: str = Field(description="Brief explanation of why this intent was chosen")
