# Physical Relational Schema — Model Format

This document describes the JSON model format for **physical relational schemas**.
The AI must produce output that conforms **exactly** to this specification.

> The format is the **same** as the logical schema but with an additional `dataType` field on each column.

## Root structure

```json
{
  "model": { "id": "pid_...", "name": "...", "version": 1 },
  "tables": [ ... ]
}
```

- `model.id`: identifier for the schema (prefix `pid_`).
- `model.name`: human-readable name.
- `model.version`: integer, start at `1`.
- `tables`: array of table objects (at least 1).

---

## `table`

| Field    | Type   | Required | Description                                      |
|----------|--------|----------|--------------------------------------------------|
| `id`     | string | ✅       | Unique ID, prefix `pid_` (e.g. `pid_customer`).  |
| `name`   | string | ✅       | Table name in **snake_case**.                    |
| `columns`| array  | ✅       | At least 1 column.                               |
| `notes`  | string |          | Optional notes.                                  |

---

## `column`

| Field      | Type    | Required | Description                                                 |
|------------|---------|----------|-------------------------------------------------------------|
| `id`       | string  | ✅       | Unique ID, prefix `pid_` (e.g. `pid_customer_email`).      |
| `name`     | string  | ✅       | Column name in **snake_case**.                              |
| `dataType` | string  | ✅       | SQL data type (e.g. `integer`, `varchar(255)`, `timestamp`).|
| `nullable` | boolean |          | Allow NULL (default `true`).                                |
| `unique`   | boolean |          | UNIQUE constraint (default `false`).                        |
| `roles`    | object  |          | Key roles (see below).                                      |
| `notes`    | string  |          | Optional notes.                                             |

### `roles` object

| Field          | Type    | Description                                              |
|----------------|---------|----------------------------------------------------------|
| `primaryKey`   | boolean | `true` if column is part of the primary key.             |
| `foreignKey`   | object  | FK reference: `{ refTableId, refColumnId }`.             |
| `candidateKey` | boolean | `true` if column participates in a candidate key.        |

### `foreignKey` object

| Field        | Type   | Description                                         |
|--------------|--------|-----------------------------------------------------|
| `refTableId` | string | ID of the referenced table (prefix `pid_`).         |
| `refColumnId`| string | ID of the referenced column (prefix `pid_`).        |

---

## ID Naming Conventions (CRITICAL)

All IDs **MUST** start with `pid_` (physical ID prefix).

- Table IDs: `pid_{table_name}` (e.g. `pid_customer`, `pid_order`).
- Column IDs: `pid_{table_name}_{column_name}` (e.g. `pid_customer_email`, `pid_order_id`).
  - **Every column ID MUST include the table name** to guarantee global uniqueness.

---

## Common Data Types

| Type              | Usage                              |
|-------------------|------------------------------------|
| `integer`         | Standard integer (4 bytes)         |
| `bigint`          | Large integer (8 bytes)            |
| `serial`          | Auto-increment integer             |
| `uuid`            | UUID primary keys                  |
| `varchar(N)`      | Variable-length string (max N)     |
| `text`            | Unbounded text                     |
| `boolean`         | True/false                         |
| `decimal(p,s)`    | Fixed-point number                 |
| `float`           | Floating-point number              |
| `date`            | Date only                          |
| `timestamp`       | Date + time                        |
| `timestamptz`     | Date + time with timezone          |
| `jsonb`           | JSON binary (PostgreSQL)           |

---

## Design Rules for Physical Schema

1. **Every table MUST have a primary key** — at least one column with `roles.primaryKey: true`.
2. **Every column MUST have a `dataType`** — use appropriate SQL types.
3. **Foreign keys MUST reference existing tables/columns** — `refTableId` and `refColumnId` must match actual IDs.
4. **PK columns**: set `nullable: false`, `unique: true`, use `serial` or `integer` or `uuid`.
5. **FK columns**: set `nullable: false` for mandatory relationships; use same `dataType` as the referenced PK.
6. **Timestamps**: include `created_at` and `updated_at` with type `timestamptz` where appropriate.
7. **Naming**: use clear, descriptive **snake_case** names.

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
          "roles": { "primaryKey": true }
        },
        {
          "id": "pid_customer_email",
          "name": "email",
          "dataType": "varchar(255)",
          "nullable": false,
          "unique": true
        },
        {
          "id": "pid_customer_full_name",
          "name": "full_name",
          "dataType": "varchar(100)",
          "nullable": false
        },
        {
          "id": "pid_customer_created_at",
          "name": "created_at",
          "dataType": "timestamptz",
          "nullable": false
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
              "refColumnId": "pid_customer_id"
            }
          }
        },
        {
          "id": "pid_order_total_amount",
          "name": "total_amount",
          "dataType": "decimal(10,2)",
          "nullable": false
        },
        {
          "id": "pid_order_status",
          "name": "status",
          "dataType": "varchar(20)",
          "nullable": false
        },
        {
          "id": "pid_order_created_at",
          "name": "created_at",
          "dataType": "timestamptz",
          "nullable": false
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
              "refColumnId": "pid_order_id"
            }
          }
        },
        {
          "id": "pid_order_item_product_name",
          "name": "product_name",
          "dataType": "varchar(200)",
          "nullable": false
        },
        {
          "id": "pid_order_item_quantity",
          "name": "quantity",
          "dataType": "integer",
          "nullable": false
        },
        {
          "id": "pid_order_item_unit_price",
          "name": "unit_price",
          "dataType": "decimal(10,2)",
          "nullable": false
        }
      ]
    }
  ]
}
```
