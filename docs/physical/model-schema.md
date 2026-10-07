# Physical Relational Schema — Model Format

This document describes the JSON model format for **physical relational schemas**.
The AI must produce output that conforms **exactly** to this specification.

> The format extends the logical schema with `dataType`, `length`, `autoIncrement`, `defaultValue`, `indexes`, and FK constraint actions (`onDelete`, `onUpdate`).

## Root structure

```json
{
  "model": { "id": "pid_...", "name": "...", "version": 1 },
  "tables": [ ... ]
}
```

- `model.id`: non-empty identifier for the schema; preserve existing IDs, including UUIDs.
- `model.name`: human-readable name.
- `model.version`: integer, start at `1`.
- `model.dbms`: optional target, exactly `postgresql`, `mysql`, or `sqlserver`.
- `model.description`, `model.notes`: optional metadata; preserve on edits.
- `tables`: array of table objects; may be empty for an empty canvas.

---

## `table`

| Field     | Type   | Required | Description                                      |
|-----------|--------|----------|--------------------------------------------------|
| `id`      | string | ✅       | Non-empty ID; new IDs use `pid_` (e.g. `pid_customer`).  |
| `name`    | string | ✅       | Table name in **snake_case**.                    |
| `columns` | array  | ✅       | Ordered columns; may be empty while editing.                               |
| `indexes` | array  |          | Optional array of index definitions.             |
| `functionalDependencies` | array | | Functional dependencies; see below. |
| `showFunctionalDependencies` | boolean | | Whether to display FDs; default `false`. |
| `comment` | string | | Table description. |
| `notes`   | string |          | Optional notes.                                  |

---

## `column`

| Field           | Type    | Required | Description                                                                |
|-----------------|---------|----------|----------------------------------------------------------------------------|
| `id`            | string  | ✅       | Non-empty ID; new IDs use `pid_` (e.g. `pid_customer_email`).                     |
| `name`          | string  | ✅       | Column name in **snake_case**.                                             |
| `dataType`      | string  |          | Base SQL data type **without length** (e.g. `varchar`, `integer`, `decimal`). |
| `length`        | string  |          | Length or precision (e.g. `"255"` for varchar(255), `"10,2"` for decimal). |
| `nullable`      | boolean | ✅       | Allow NULL (default `true`).                                               |
| `unique`        | boolean | ✅       | UNIQUE constraint (default `false`).                                       |
| `autoIncrement` | boolean |          | Auto-increment / identity column (default `false`).                        |
| `defaultValue`  | string  |          | SQL default expression (e.g. `"NOW()"`, `"0"`, `"true"`).                 |
| `roles`         | object  |          | Key roles (see below).                                                     |
| `comment`       | string  |          | Column description. |
| `notes`         | string  |          | Optional notes.                                                            |

### IMPORTANT: `dataType` vs `length` separation

The `dataType` field stores ONLY the base type name. Length/precision goes in the separate `length` field:

| ❌ Old way (DO NOT USE)   | ✅ New way                                    |
|--------------------------|-----------------------------------------------|
| `"dataType": "varchar(255)"` | `"dataType": "varchar", "length": "255"`   |
| `"dataType": "decimal(10,2)"` | `"dataType": "decimal", "length": "10,2"` |
| `"dataType": "char(1)"`  | `"dataType": "char", "length": "1"`          |
| `"dataType": "integer"`  | `"dataType": "integer"` (no length needed)   |
| `"dataType": "text"`     | `"dataType": "text"` (no length needed)      |

### `roles` object

| Field          | Type    | Description                                              |
|----------------|---------|----------------------------------------------------------|
| `primaryKey`   | boolean | `true` if column is part of the primary key.             |
| `foreignKey`   | object  | FK reference with constraint actions.                    |
| `candidateKey` | boolean | `true` if column participates in a candidate key.        |

### `foreignKey` object

| Field        | Type   | Required | Description                                            |
|--------------|--------|----------|--------------------------------------------------------|
| `refTableId` | string | ✅       | Exact existing table ID.            |
| `refColumnId`| string | ✅       | Exact existing column ID.           |
| `onDelete`   | string |          | Action on delete: `NO ACTION`, `CASCADE`, `SET NULL`, `SET DEFAULT`, `RESTRICT`. Default: `NO ACTION`. |
| `onUpdate`   | string |          | Action on update: `NO ACTION`, `CASCADE`, `SET NULL`, `SET DEFAULT`, `RESTRICT`. Default: `NO ACTION`. |

---

## `index`

| Field     | Type    | Required | Description                                              |
|-----------|---------|----------|----------------------------------------------------------|
| `id`      | string  | ✅       | Unique ID for the index.                                 |
| `name`    | string  | ✅       | Index name (e.g. `idx_customer_email`).                  |
| `type`    | string  | ✅       | Index type: `BTREE`, `HASH`, `GIN`, `GIST`, `BRIN`, `CLUSTERED`, `NONCLUSTERED`.     |
| `columns` | array   | ✅       | Ordered list of columns in the index.                    |
| `isUnique`| boolean |          | Whether this is a unique index (default `false`).        |

### `index.columns[]` items

| Field        | Type   | Required | Description                            |
|--------------|--------|----------|----------------------------------------|
| `columnName` | string | ✅       | Name of the column in the index.       |
| `order`      | string | ✅       | Sort order: `ASC` or `DESC`.           |

---

## ID Naming Conventions (CRITICAL)

All persisted IDs and references are non-empty strings. Preserve existing IDs (including UUIDs); use `pid_` for newly generated table/column/FD IDs. Index IDs may use `idx_`.

- Table IDs: `pid_{table_name}` (e.g. `pid_customer`, `pid_order`).
- Column IDs: `pid_{table_name}_{column_name}` (e.g. `pid_customer_email`, `pid_order_id`).
  - **Every newly generated column ID MUST include the table name** to guarantee global uniqueness.
- Index IDs: `idx_{table_name}_{description}` (e.g. `idx_customer_email`).

---

## Common Data Types

| Type              | Usage                              |
|-------------------|------------------------------------|
| `integer`         | Standard integer (4 bytes)         |
| `bigint`          | Large integer (8 bytes)            |
| `serial`          | Auto-increment integer             |
| `uuid`            | UUID primary keys                  |
| `varchar`         | Variable-length string (use with `length`) |
| `char`            | Fixed-length string (use with `length`)    |
| `text`            | Unbounded text                     |
| `boolean`         | True/false                         |
| `decimal`         | Fixed-point number (use with `length` e.g. `"10,2"`) |
| `float`           | Floating-point number              |
| `date`            | Date only                          |
| `timestamp`       | Date + time                        |
| `timestamptz`     | Date + time with timezone          |
| `jsonb`           | JSON binary (PostgreSQL)           |

---

## Design Rules for Physical Schema

1. **Every table MUST have a primary key** — at least one column with `roles.primaryKey: true`.
2. **Composite primary keys**: multiple columns can have `roles.primaryKey: true` in the same table.
3. **Every column MUST have a `dataType`** — use appropriate SQL types.
4. **Separate dataType and length** — `dataType` is the base type, `length` is a separate field.
5. **Foreign keys MUST reference existing tables/columns** — `refTableId` and `refColumnId` must match actual IDs.
6. **FK constraint actions**: use `onDelete` and `onUpdate` on foreign keys where appropriate:
   - Parent deletion with dependent children → `CASCADE` or `SET NULL`
   - Reference integrity → `RESTRICT`
   - Default: `NO ACTION` (can be omitted)
7. **Auto-increment**: set `autoIncrement: true` for serial/identity PK columns.
8. **Default values**: use `defaultValue` for columns with sensible defaults (e.g. `"NOW()"` for timestamps, `"true"` for booleans).
9. **Indexes**: add indexes for columns frequently used in WHERE/JOIN/ORDER BY clauses.
   - FK columns should typically have an index.
   - Use `BTREE` for general purpose, `HASH` for equality-only, `GIN` for JSONB/array (PostgreSQL).
10. **PK columns**: set `nullable: false`, `unique: true`, use `autoIncrement: true` or `uuid`.
11. **Timestamps**: include `created_at` and `updated_at` with type `timestamptz` and `defaultValue: "NOW()"` where appropriate.
12. **Naming**: use clear, descriptive **snake_case** names.

---

## `functionalDependency`

| Field | Type | Required for new output | Description |
|---|---|---|---|
| `id` | string | Yes | Stable, non-empty FD identifier. |
| `left` | array of strings | Yes | Determinant column IDs or names. |
| `right` | array of strings | Yes | Dependent column IDs or names. |
| `name` | string | No | Descriptive name. |
| `notes` | string | No | Additional notes. |

FD sides may be empty in a partially edited model. FDs describe dependencies; they do not define SQL constraints.

## Output rules

- Include `nullable` and `unique` on every new column and `id` on every new FD. Older payloads may omit these fields.
- A complete physical design must give every column a non-empty `dataType`.
- Use exactly `postgresql`, `mysql`, or `sqlserver` for `model.dbms`.
- Use column `roles` for PK/FK constraints and separate `dataType`/`length` for types.
- Preserve existing IDs, FD arrays, FD visibility, comments, notes, and model metadata unless the requested edit changes them.
- Emit only fields defined in the accompanying `model.schema.json`.

---

## Example

```json
{
  "model": {
    "id": "pid_ecommerce_db",
    "name": "E-Commerce Database",
    "version": 1
  },
  "tables": [
    {
      "id": "pid_customer",
      "name": "customer",
      "columns": [
        {
          "id": "pid_customer_id",
          "name": "id",
          "dataType": "serial",
          "nullable": false,
          "unique": true,
          "autoIncrement": true,
          "roles": { "primaryKey": true }
        },
        {
          "id": "pid_customer_email",
          "name": "email",
          "dataType": "varchar",
          "length": "255",
          "nullable": false,
          "unique": true
        },
        {
          "id": "pid_customer_full_name",
          "name": "full_name",
          "dataType": "varchar",
          "length": "100",
          "nullable": false
        },
        {
          "id": "pid_customer_status",
          "name": "status",
          "dataType": "varchar",
          "length": "20",
          "nullable": false,
          "defaultValue": "'active'"
        },
        {
          "id": "pid_customer_created_at",
          "name": "created_at",
          "dataType": "timestamptz",
          "nullable": false,
          "defaultValue": "NOW()"
        }
      ],
      "indexes": [
        {
          "id": "idx_customer_email",
          "name": "idx_customer_email",
          "type": "BTREE",
          "columns": [{ "columnName": "email", "order": "ASC" }],
          "isUnique": true
        }
      ]
    },
    {
      "id": "pid_order",
      "name": "order",
      "columns": [
        {
          "id": "pid_order_id",
          "name": "id",
          "dataType": "serial",
          "nullable": false,
          "unique": true,
          "autoIncrement": true,
          "roles": { "primaryKey": true }
        },
        {
          "id": "pid_order_customer_id",
          "name": "customer_id",
          "dataType": "integer",
          "nullable": false,
          "roles": {
            "foreignKey": {
              "refTableId": "pid_customer",
              "refColumnId": "pid_customer_id",
              "onDelete": "CASCADE",
              "onUpdate": "NO ACTION"
            }
          }
        },
        {
          "id": "pid_order_total_amount",
          "name": "total_amount",
          "dataType": "decimal",
          "length": "10,2",
          "nullable": false
        },
        {
          "id": "pid_order_status",
          "name": "status",
          "dataType": "varchar",
          "length": "20",
          "nullable": false,
          "defaultValue": "'pending'"
        },
        {
          "id": "pid_order_created_at",
          "name": "created_at",
          "dataType": "timestamptz",
          "nullable": false,
          "defaultValue": "NOW()"
        }
      ],
      "indexes": [
        {
          "id": "idx_order_customer_id",
          "name": "idx_order_customer_id",
          "type": "BTREE",
          "columns": [{ "columnName": "customer_id", "order": "ASC" }],
          "isUnique": false
        },
        {
          "id": "idx_order_status",
          "name": "idx_order_status",
          "type": "BTREE",
          "columns": [{ "columnName": "status", "order": "ASC" }],
          "isUnique": false
        }
      ]
    },
    {
      "id": "pid_order_item",
      "name": "order_item",
      "columns": [
        {
          "id": "pid_order_item_id",
          "name": "id",
          "dataType": "serial",
          "nullable": false,
          "unique": true,
          "autoIncrement": true,
          "roles": { "primaryKey": true }
        },
        {
          "id": "pid_order_item_order_id",
          "name": "order_id",
          "dataType": "integer",
          "nullable": false,
          "roles": {
            "foreignKey": {
              "refTableId": "pid_order",
              "refColumnId": "pid_order_id",
              "onDelete": "CASCADE",
              "onUpdate": "NO ACTION"
            }
          }
        },
        {
          "id": "pid_order_item_product_name",
          "name": "product_name",
          "dataType": "varchar",
          "length": "200",
          "nullable": false
        },
        {
          "id": "pid_order_item_quantity",
          "name": "quantity",
          "dataType": "integer",
          "nullable": false,
          "defaultValue": "1"
        },
        {
          "id": "pid_order_item_unit_price",
          "name": "unit_price",
          "dataType": "decimal",
          "length": "10,2",
          "nullable": false
        }
      ],
      "indexes": [
        {
          "id": "idx_order_item_order_id",
          "name": "idx_order_item_order_id",
          "type": "BTREE",
          "columns": [{ "columnName": "order_id", "order": "ASC" }],
          "isUnique": false
        }
      ]
    }
  ]
}
```
