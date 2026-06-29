# Text-to-SQL Pipeline

Pipeline áp dụng cho tính năng **AI SQL Generator** trong Query Executor.  
User mô tả yêu cầu bằng ngôn ngữ tự nhiên → AI đọc schema thực tế của DB → sinh ra câu SQL → đặt vào Monaco editor để user review trước khi chạy.

Pipeline này **không đi qua LangGraph** — chạy trực tiếp qua FastAPI sidecar (`src/api/ingest.py`) vì là single-shot generation, không cần stateful agent.

---

## Sơ đồ luồng

```
User gõ mô tả NL
  → FE gọi POST /db-connections/:connId/text-to-sql  (backend NestJS)
  → BE introspect live DB → lấy danh sách table + column + FK + index
  → BE gọi POST /api/text-to-sql                     (dbflow-ai FastAPI sidecar)
  → sidecar format schema context (text phẳng, không JSON)
  → sidecar fetch project docs từ ChromaDB (nếu có project_id)
  → sidecar gọi Gemini (temperature=0) → nhận SQL
  → strip markdown fence nếu có
  → trả { sql } về BE → BE trả về FE
  → FE set SQL vào Monaco editor
```

---

## Các bước chi tiết

| Bước | Tên | Mô tả |
|---|---|---|
| 1 | **Nhận request từ FE** | FE gọi `POST /db-connections/:connId/text-to-sql` với body `{ nl_query, schema?, project_id? }`. `schema` là tên PostgreSQL schema (ví dụ `"public"`); `project_id` dùng để lấy project docs từ ChromaDB. |
| 2 | **Introspect live DB** | Backend NestJS gọi `introspectSchema()` để lấy danh sách `IntrospectedTable[]` trực tiếp từ DB thật: tên bảng, tên cột, dataType, nullable, PK, FK, index. Đây là nguồn schema **ưu tiên** vì phản ánh trạng thái thực tế của database, không phụ thuộc vào model diagram trên UI. |
| 3 | **Gọi dbflow-ai sidecar** | BE gửi `POST /api/text-to-sql` (FastAPI) với `{ nl_query, dbms, schema_tables: IntrospectedTable[], project_id? }`. `dbms` được lấy từ entity DBConnection để sinh đúng syntax (PostgreSQL / MySQL / SQL Server). |
| 4 | **Format schema context** | Sidecar gọi `_format_schema_context()` để chuyển `schema_tables` thành text dễ đọc cho LLM: tên bảng, từng cột kèm type + flags (PK / NOT NULL / UNIQUE / DEFAULT), và các FK relationship. Format phẳng, không JSON — giảm token consumption. |
| 5 | **Fetch project docs (RAG)** | Nếu `project_id` có trong request: sidecar gọi `aretrieve_project_docs(nl_query, project_id, k=3)` để lấy top-3 chunks từ ChromaDB collection `project_docs`. Các chunks này thường chứa business context (tên trường nghiệp vụ, quy tắc nghiệp vụ, enum values) giúp AI hiểu đúng ý định user. **Bỏ qua hoàn toàn nếu `project_id` không có** — không raise error, không fallback. |
| 6 | **Xây prompt & gọi Gemini** | Sidecar tổng hợp prompt: `TEXT_TO_SQL_SYSTEM_PROMPT` (system) + schema context + project docs (nếu có) + câu mô tả của user. Gọi Gemini với `temperature=0` (SQL cần deterministic, không creative). System prompt yêu cầu: output chỉ là SQL thuần — không explanation, không markdown fence, không comment thêm. |
| 7 | **Xử lý output** | Nếu model vẫn trả về fenced block (` ```sql ... ``` `), sidecar tự strip fence trước khi trả về. SQL được `.strip()`. **Không có validation** ở bước này — user tự review trong editor rồi mới Execute. |
| 8 | **Trả kết quả** | Sidecar trả `{ sql: string }` về BE, BE forward về FE. FE gọi `setSql(res.sql)` để đặt vào Monaco editor. Log entry "SQL generated successfully." được thêm vào query log panel. |

---

## Input cho AI

```
[System]
TEXT_TO_SQL_SYSTEM_PROMPT:
  - Output ONLY the SQL query, nothing else
  - Use exact table/column names from schema
  - Add LIMIT for SELECT unless user specifies otherwise
  - Use syntax compatible with the specified DBMS
  - If ambiguous, make a reasonable assumption

[Human]
Database Schema:
  Database: PostgreSQL

  Table: users
    - id: integer  [PRIMARY KEY, AUTO INCREMENT, NOT NULL]
    - email: varchar(255)  [UNIQUE, NOT NULL]
    - full_name: varchar(255)
    - created_at: timestamp  [DEFAULT NOW()]
  FK: (...)

  Table: orders
    - id: integer  [PRIMARY KEY, AUTO INCREMENT, NOT NULL]
    - user_id: integer  [NOT NULL]
    - total: decimal
    ...
  FK: (user_id) → users(id)

Additional project documentation:   ← chỉ có nếu project_id hợp lệ và có docs
  [Business Rules]
  ...relevant chunks from ChromaDB...

Generate SQL for: "lấy tất cả order trong tháng này kèm tên khách hàng"
```

---

## So sánh với Schema Generation Pipeline

| Tiêu chí | Schema Gen Pipeline | Text-to-SQL Pipeline |
|---|---|---|
| **Chạy qua** | LangGraph (stateful agent) | FastAPI sidecar (single-shot) |
| **State** | Có — thread lưu schema_model, history, retry_count | Không — stateless, mỗi request độc lập |
| **Schema context** | Spec RAG (model.schema.json theo level) | DBMS introspect (live DB thực tế) |
| **Project docs** | Hybrid re-rank (BM25 + semantic, top-k) | Simple cosine similarity, top-3, không re-rank |
| **Validator** | Có — JSON Schema + structural checks, retry loop | Không — user tự review trong editor |
| **Temperature** | 0.1 (cho phép một chút sáng tạo khi design) | 0 (SQL phải chính xác, không creative) |
| **Output format** | model.json (fenced code block, parsed) | SQL plain text (strip fence nếu có) |
| **Streaming** | Có — SSE stream về FE theo từng token | Không — await toàn bộ rồi trả 1 lần |
| **Retry** | Có — tự động retry nếu validation fail | Không — lỗi trả thẳng về FE |

---

## Thứ tự ưu tiên context

```
1. DBMS schema (primary)   ← từ introspect live DB, luôn có
2. Project docs (secondary) ← từ ChromaDB RAG, chỉ có nếu project_id và đã ingest docs
3. (Physical schema model từ editor KHÔNG được inject — introspect là ground truth)
```

---

## API contracts

**Frontend → Backend (NestJS):**

```ts
POST /db-connections/:connId/text-to-sql
Authorization: Bearer <jwt>

Body:
{
  nl_query: string;      // câu mô tả tự nhiên của user
  schema?: string;       // tên DB schema, ví dụ "public" (PostgreSQL)
  project_id?: string;   // optional, để fetch project docs từ RAG
}

Response:
{
  sql: string;           // SQL thuần, sẵn sàng để paste vào editor
}
```

**Backend (NestJS) → dbflow-ai (FastAPI):**

```python
POST /api/text-to-sql

Body:
{
  "nl_query": str,
  "dbms": str,                    # "postgresql" | "mysql" | "sqlserver"
  "schema_tables": List[dict],    # IntrospectedTable[] từ introspect
  "project_id": str | None
}

Response:
{
  "sql": str
}
```

---

## Giới hạn của v1

| Tính năng | Trạng thái | Ghi chú |
|---|---|---|
| Sinh nhiều câu query cùng lúc | Không hỗ trợ | Mỗi lần Generate = 1 câu |
| Streaming SQL token by token | Không hỗ trợ | Await toàn bộ rồi set vào editor |
| Re-rank project docs (BM25 + semantic) | Không — chỉ cosine | Đủ cho top-3, có thể nâng cấp |
| Validate SQL trước khi trả về | Không | User tự review trong Monaco editor |
| Safeguard (chặn DROP/TRUNCATE từ AI) | Không ở bước này | Safeguard Layer chạy khi user bấm Execute |
| Inject physical schema model từ editor | Không | DBMS introspect là source of truth |
| Cache introspect result | Không | Introspect mỗi lần Generate — có thể cache nếu chậm |

---

## Liên kết với các tính năng khác

| Tính năng | Liên quan |
|---|---|
| **Document Ingestion** (`DOC-document-ingestion.md`) | Project docs được embed vào ChromaDB bởi ingest pipeline — Text-to-SQL dùng lại collection `project_docs` |
| **Query Executor** (`query-executor-implementation-rules.md` trong dbflow-frontend) | Text-to-SQL là sub-feature của Query Executor; SQL sinh ra đặt vào Monaco editor rồi Safeguard Layer + Execute mới chạy |
| **Schema Gen Pipeline** (`DOC-schema-gen-pipeline.md`) | Cùng dùng ChromaDB `project_docs`, nhưng Text-to-SQL không dùng `schema_docs` (spec RAG) |
