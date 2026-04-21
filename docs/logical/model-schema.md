# Logical Relational Schema — Model Format

This document describes the JSON model format for **logical relational schemas**.
The AI must produce output that conforms **exactly** to this specification.

## Root structure

```json
{
  "model": { "id": "lid_...", "name": "...", "version": 1 },
  "tables": [ ... ]
}
```

- `model.id`: identifier for the schema (prefix `lid_`).
- `model.name`: human-readable name.
- `model.version`: integer, start at `1`.
- `tables`: array of table objects (at least 1).

---

## `table`

| Field                    | Type     | Required | Description                              |
|--------------------------|----------|----------|------------------------------------------|
| `id`                     | string   | ✅       | Unique ID, prefix `lid_` (e.g. `lid_student`). |
| `name`                   | string   | ✅       | Table name in **snake_case**.            |
| `columns`                | array    | ✅       | At least 1 column.                       |
| `functionalDependencies` | array    |          | Optional FD list.                        |
| `notes`                  | string   |          | Optional notes.                          |

---

## `column`

| Field      | Type    | Required | Description                                        |
|------------|---------|----------|----------------------------------------------------|
| `id`       | string  | ✅       | Unique ID, prefix `lid_` (e.g. `lid_student_name`).|
| `name`     | string  | ✅       | Column name in **snake_case**.                     |
| `type`     | string  |          | Optional logical data type hint (e.g. `VARCHAR`, `INTEGER`). Not DBMS-specific. |
| `nullable` | boolean |          | Allow NULL (default `true`).                       |
| `unique`   | boolean |          | UNIQUE constraint (default `false`).               |
| `roles`    | object  |          | Key roles (see below).                             |
| `notes`    | string  |          | Optional notes.                                    |

### `roles` object

| Field          | Type    | Description                                              |
|----------------|---------|----------------------------------------------------------|
| `primaryKey`   | boolean | `true` if column is part of the primary key.             |
| `foreignKey`   | object  | FK reference: `{ refTableId, refColumnId }`.             |
| `candidateKey` | boolean | `true` if column participates in a candidate key.        |

### `foreignKey` object

| Field        | Type   | Description                                         |
|--------------|--------|-----------------------------------------------------|
| `refTableId` | string | ID of the referenced table (prefix `lid_`).         |
| `refColumnId`| string | ID of the referenced column (prefix `lid_`).        |

---

## `functionalDependency`

| Field   | Type   | Required | Description                            |
|---------|--------|----------|----------------------------------------|
| `id`    | string |          | Unique ID, prefix `lid_`.              |
| `name`  | string |          | Optional descriptive name.             |
| `left`  | array  | ✅       | Determinant column IDs (prefix `lid_`).|
| `right` | array  | ✅       | Dependent column IDs (prefix `lid_`).  |
| `notes` | string |          | Optional notes.                        |

---

## ID Naming Conventions (CRITICAL)

All IDs **MUST** start with `lid_` (logical ID prefix).

- Table IDs: `lid_{table_name}` (e.g. `lid_student`, `lid_course`).
- Column IDs: `lid_{table_name}_{column_name}` (e.g. `lid_student_name`, `lid_course_id`).
  - **Every column ID MUST include the table name** to guarantee global uniqueness.
- FD IDs: `lid_fd_{table_name}_{fd_name}` (e.g. `lid_fd_student_email_determines_name`).

---

## Design Rules for Logical Schema

1. **Every table MUST have a primary key** — at least one column with `roles.primaryKey: true`.
2. **Foreign keys MUST reference existing tables/columns** — `refTableId` and `refColumnId` must match actual IDs in the schema.
3. **Normalisation**: aim for at least 3NF. Avoid redundant columns.
4. **Junction tables**: for M:N relationships, create a junction table with composite PK (both FK columns are PK).
5. **Naming**: use clear, descriptive **snake_case** names.

---

## Example

```json
{
  "model": {
    "id": "lid_university_db",
    "name": "University Database",
    "version": 1
  },
  "tables": [
    {
      "id": "lid_student",
      "name": "student",
      "columns": [
        {
          "id": "lid_student_id",
          "name": "student_id",
          "nullable": false,
          "unique": true,
          "roles": { "primaryKey": true }
        },
        {
          "id": "lid_student_name",
          "name": "name",
          "nullable": false,
          "unique": false
        },
        {
          "id": "lid_student_email",
          "name": "email",
          "nullable": false,
          "unique": true,
          "roles": { "candidateKey": true }
        }
      ]
    },
    {
      "id": "lid_course",
      "name": "course",
      "columns": [
        {
          "id": "lid_course_id",
          "name": "course_id",
          "nullable": false,
          "unique": true,
          "roles": { "primaryKey": true }
        },
        {
          "id": "lid_course_name",
          "name": "name",
          "nullable": false,
          "unique": false
        }
      ]
    },
    {
      "id": "lid_enrollment",
      "name": "enrollment",
      "columns": [
        {
          "id": "lid_enrollment_student_id",
          "name": "student_id",
          "nullable": false,
          "unique": false,
          "roles": {
            "primaryKey": true,
            "foreignKey": {
              "refTableId": "lid_student",
              "refColumnId": "lid_student_id"
            }
          }
        },
        {
          "id": "lid_enrollment_course_id",
          "name": "course_id",
          "nullable": false,
          "unique": false,
          "roles": {
            "primaryKey": true,
            "foreignKey": {
              "refTableId": "lid_course",
              "refColumnId": "lid_course_id"
            }
          }
        },
        {
          "id": "lid_enrollment_enrolled_at",
          "name": "enrolled_at",
          "nullable": false,
          "unique": false
        }
      ]
    }
  ]
}
```

