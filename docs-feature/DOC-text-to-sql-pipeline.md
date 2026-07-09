# Text-to-SQL Pipeline (v2 — LangGraph intent)

Pipeline áp dụng cho intent: `text_to_sql`. Đây là intent thứ 4 của graph chính (`src/agent/graph.py`), bên cạnh `create` / `edit` / `chat`.

User mô tả yêu cầu bằng ngôn ngữ tự nhiên → AI đọc **physical schema `model.json`** hiện tại (không phải DB kết nối thật) → sinh ra một câu SQL → đặt vào Monaco editor để user review trước khi chạy.

Khác với v1 (xem "Lịch sử" ở cuối file), pipeline này **đi qua LangGraph** — dùng chung graph, state, và cơ chế retrieval/retry với Schema Generation Pipeline (`DOC-schema-gen-pipeline.md`), chỉ khác node sinh output cuối (SQL thay vì model.json).

**Node dùng chung với intent `seed_data`**: `sql_generator_node` (`src/agent/nodes/sql_generator.py`) và `sql_validator_node` (`src/agent/nodes/sql_validator.py`) được tái sử dụng nguyên vẹn cho cả 2 intent — chỉ branch prompt (`SQL_GENERATOR_PROMPT` vs `SEED_DATA_GENERATOR_PROMPT`) và validator flags (`require_insert_only`, `expect_single_statement`) dựa theo `state["user_intent"]`. Chi tiết riêng của `seed_data` xem `dbflow-frontend/docs-v2/seed-data-generation-implementation-rules.md`. Phần còn lại của tài liệu này mô tả theo góc nhìn `text_to_sql`, trừ khi ghi chú khác.

---

## Điểm khác biệt cốt lõi: intent không do LLM tự phân loại

`text_to_sql` **không** nằm trong tập intent mà `router_node` cho Gemini tự classify (`ClassifiableIntent` trong `src/agent/models.py` chỉ có `create`/`edit`/`chat`). Frontend set thẳng field `input_intent: "text_to_sql"` trong request — `router_node` đọc field này, set `user_intent` ngay, **bỏ qua hoàn toàn lệnh gọi LLM classifier**. Lý do: ngữ cảnh gọi (từ QueryExecutorModal) đã rõ ràng 100% là sinh SQL, không cần LLM đoán, tránh rủi ro misclassify và tiết kiệm 1 lượt gọi Gemini.

---

## Sơ đồ luồng

```
START
  → router_node
      - sync input_model → schema_model (như các intent khác)
      - đọc input_intent == "text_to_sql" → set user_intent, bỏ qua LLM classify
      - set current_level = "physical" (bắt buộc — text_to_sql chỉ dùng physical schema)
      - suy ra target_dbms từ schema_model.model.dbms
  → retriever_node       — đọc full docs/physical/model-schema.md + model.schema.json (spec)
                            + fetch project_docs candidates (ChromaDB, nếu có project_id)
  → reranker_node        — rerank project_docs (hybrid BM25 + semantic) — spec đi thẳng qua
  → sql_generator_node   — build prompt (spec + schema_model JSON + project docs + user_message)
                            → Gemini (temperature=0) → parse fenced ```sql block
  → sql_validator_node   — sqlglot parse theo dialect target_dbms + check table/column
                            tồn tại trong schema_model
  → [issues?] ──yes──→  sql_generator_node   (retry, tối đa VALIDATION_MAX_RETRIES lần)
              └─ no ──→ END
```

---

## Các bước chi tiết

| Bước | Tên | Mô tả |
|---|---|---|
| 1 | **Nạp state** | Giống schema-gen: lấy `AgentState` từ thread. Vì mỗi lần Generate FE tạo thread mới (ephemeral, không lưu chat history), state luôn "sạch" — không có `schema_model` cũ từ turn trước trong cùng thread. FE gửi `input_model` = physical schema model.json hiện tại của diagram đang mở → router sync vào `schema_model`. |
| 2 | **Set intent (không classify)** | `router_node` đọc `state["input_intent"]`. Nếu bằng `"text_to_sql"`: set `user_intent = "text_to_sql"`, `current_level = "physical"`, suy `target_dbms` từ `schema_model.model.dbms` (không cần LLM detect vì physical model luôn có field `dbms`). Reset `validation_issues = []`, `retry_count = 0`. Emit routing message tối giản (không gọi Gemini). Luôn clear `input_intent` về `None` sau khi đọc (kể cả khi không override) để tránh state cũ rò rỉ sang turn sau nếu thread bị tái sử dụng. |
| 3 | **Hybrid retrieval (song song)** | Giống hệt bước 3 của schema-gen: |
| | └ *Spec RAG* | Đọc full `docs/physical/model-schema.md` + `docs/physical/model.schema.json` — không chunk. Đây là tài liệu giải thích cấu trúc `roles.primaryKey`/`roles.foreignKey`/`refTableId`/`refColumnId` — bắt buộc để LLM hiểu đúng JSON trước khi viết SQL (đọc schema từ file JSON thì phải hiểu định nghĩa JSON đó). |
| | └ *Project RAG* | Top-N candidates từ ChromaDB `project_docs`, filter theo `project_id`. Bỏ qua nếu project chưa có docs. |
| 3.5 | **Re-rank project_docs** | Giống hệt schema-gen: `final_score = 0.6 × semantic + 0.4 × bm25`. |
| 4 | **Merge context** | `retrieval_context` (spec, full) + `project_docs_context` (đã rank) đưa vào state, giống create/edit. |
| 5 | **Xây prompt LLM** | `SQL_GENERATOR_PROMPT` (`src/agent/prompts.py`) + `retrieval_context` (spec physical) + `schema_model` (JSON đầy đủ, không phải text phẳng) + `project_docs_context` + `target_dbms` + `user_message`. Nếu retry: append `validation_issues` vào cuối để LLM tự sửa. |
| 6 | **Gọi LLM & nhận kết quả** | Gemini `temperature=0` (SQL cần deterministic, không sáng tạo — khác `schema_generator` dùng 0.1), `max_output_tokens` nhỏ hơn nhiều (mặc định 4096, env `SQL_GEN_MAX_OUTPUT_TOKENS` — 1 câu SQL không cần budget như model.json). Parse SQL từ fenced ` ```sql ` block. Nếu không tìm thấy block hợp lệ: retry nội bộ tối đa `SCHEMA_GEN_MAX_RETRIES` lần (tái dùng env var có sẵn) với prompt yêu cầu regenerate. |
| 7 | **Guardrails (sql_validator_node)** | Hai lớp check, dùng `sqlglot`: |
| | └ *Syntax* | `sqlglot.parse_one(sql, dialect=<mapped từ target_dbms>)`. Map: `postgresql→postgres`, `mysql→mysql`, `sqlserver→tsql`. Vì `sqlglot` khá lenient (không raise lỗi với một số câu sai cú pháp dạng "SELEKT ... FORM"), validator còn check thêm: kết quả parse phải là `exp.Query`/`exp.DML` thực sự, không phải expression rác. |
| | └ *Identifier existence* | Trích tất cả `exp.Table` + `exp.Column` từ AST, dựng alias map (`u` → `users`), so khớp case-insensitive với table/column names trong `schema_model`. Column không qualify table trong query nhiều bảng bị bỏ qua (tránh false positive) — chỉ check khi có 1 bảng duy nhất hoặc column có prefix rõ ràng. |
| 8 | **Retry loop** | Tái dùng `validation_issues`/`retry_count`/`VALIDATION_MAX_RETRIES` — cùng cơ chế với schema validator. Có issue & còn lượt retry: quay lại bước 5 với issues làm feedback. Hết retry: emit warning kèm SQL hiện có, không chặn. |
| 9 | **Trả kết quả & stream** | Emit AIMessage: 1 câu mô tả ngắn + fenced ` ```sql ` block, stream qua LangGraph SSE giống schema-gen. FE parse bằng `extractSqlFromContent()` (`dbflow-frontend/src/api/ai/client.ts`), lấy phần trong fence đặt vào Monaco editor. State lưu `generated_sql` để debug/test, nhưng FE không đọc field này trực tiếp (chỉ đọc qua message stream). |

---

## Input cho AI (ví dụ prompt)

```
[System — SQL_GENERATOR_PROMPT]
  - Target DBMS: postgresql
  - Physical Schema Specification Reference: <full nội dung model-schema.md + model.schema.json>
  - Current Physical Schema (model.json): { "model": {...}, "tables": [...] }
  - Project Business Context: <project docs đã rerank, nếu có>
  - Rules: chỉ dùng table/column có thật, 1 statement, JOIN theo roles.foreignKey,
           thêm LIMIT hợp lý cho SELECT, output fenced ```sql block

[Human — từ state["messages"]]
lấy tất cả order trong tháng này kèm tên khách hàng
```

---

## So sánh với Schema Generation Pipeline

| Tiêu chí | Schema Gen Pipeline | Text-to-SQL Pipeline (v2) |
|---|---|---|
| **Chạy qua** | LangGraph | LangGraph (cùng graph, node khác) |
| **Intent** | LLM classify (`create`/`edit`) | FE set cứng (`input_intent`), bỏ qua LLM classify |
| **State** | Có — thread lưu schema_model, history, retry_count | Có — nhưng thread ephemeral, tạo mới mỗi lần Generate |
| **Schema context** | Spec RAG theo level đang generate | Spec RAG cố định physical + `schema_model` JSON hiện tại (không introspect DB thật) |
| **Project docs** | Hybrid re-rank (BM25 + semantic, top-k) | Giống hệt — hybrid re-rank |
| **Generator node** | `schema_generator`/`schema_editor` | `sql_generator` |
| **Validator node** | `validator` — JSON Schema + structural checks | `sql_validator` — sqlglot syntax + identifier existence |
| **Temperature** | 0.1 | 0 (SQL cần chính xác tuyệt đối) |
| **Output format** | model.json (fenced code block) | SQL (fenced ` ```sql ` block) |
| **Streaming** | Có | Có |
| **Retry** | Có, tối đa `VALIDATION_MAX_RETRIES` | Có, tái dùng cùng cơ chế/env var |
| **Ghi vào `schema_model`** | Có (là output chính) | Không — read-only với schema |

---

## Thứ tự ưu tiên context (ĐÃ ĐỔI so với v1)

```
1. Physical schema model.json (primary)  ← từ input_model FE gửi, sync vào schema_model
2. Spec RAG (docs/physical/*)            ← full, không chunk — LLM cần hiểu JSON structure
3. Project docs (secondary)              ← ChromaDB RAG, hybrid re-rank, chỉ có nếu project_id + đã ingest
4. target_dbms                           ← suy từ schema_model.model.dbms, không cần LLM detect
```

Live DB connection **không còn là context cho AI** — connection chỉ dùng ở bước Execute (sau khi có SQL), việc này nằm ngoài scope của thay đổi này.

---

## API contracts (v2)

**Frontend → dbflow-ai (LangGraph server, trực tiếp — không qua NestJS):**

```ts
POST /threads/{thread_id}/runs/stream
Body: {
  assistant_id: DBFLOW_ASSISTANT_ID,
  input: {
    messages: [{ role: "user", content: nl_query }],
    current_level: "physical",
    input_model: <PhysicalModelPayload>,
    project_id?: string,
    input_intent: "text_to_sql",
  },
  config: { configurable: { thread_id } },
  stream_mode: ["messages"],
}
```

SSE response giống hệt schema-gen (`messages/partial`, `messages/complete`, `metadata`, `error`). FE parse SQL bằng `extractSqlFromContent()`.

**Route v1 cũ (vẫn còn trong code, không còn được frontend gọi):**

```python
POST /api/text-to-sql   # dbflow-ai FastAPI sidecar, src/api/ingest.py — KHÔNG XOÁ, ngoài scope lần đổi này
Body: { nl_query, dbms, schema_tables: IntrospectedTable[], project_id? }
Response: { sql: string }
```

---

## Giới hạn

| Tính năng | v2 | Ghi chú |
|---|---|---|
| Sinh nhiều câu query cùng lúc | Không hỗ trợ | 1 statement mỗi lần Generate |
| Streaming SQL | Có | Qua LangGraph SSE, giống schema-gen |
| Validate SQL trước khi trả về | Có | `sqlglot` syntax + identifier existence, có retry loop |
| Safeguard (chặn DROP/TRUNCATE từ AI) | Không ở bước này | Safeguard Layer chạy khi user bấm Execute (phía FE, ngoài scope pipeline này) |
| Inject physical schema model | Có — là nguồn chính | Đảo ngược hoàn toàn so với v1 |
| DB introspect live làm context AI | Không còn | Introspect (nếu có) chỉ phục vụ Execute sau này |
| Multi-turn chat để sửa SQL | Không | UI vẫn one-shot (nút Generate), mỗi lần tạo thread mới |
| Business logic / quyền hạn | Không check | `sql_validator_node` chỉ check syntax + identifier tồn tại |

---

## Lịch sử

**v1 (đã thay thế)**: pipeline chạy qua FastAPI sidecar riêng (`POST /api/text-to-sql`, stateless, single-shot), context chính là DBMS introspect (live DB), không có validator/retry, không streaming. Code v1 vẫn còn trong `src/api/ingest.py` (không xoá) nhưng không còn được frontend gọi kể từ khi chuyển sang v2.

**v2 (hiện tại)**: chuyển hẳn vào LangGraph như một intent (`text_to_sql`), tái dùng toàn bộ hạ tầng retrieval/rerank/retry của schema-gen pipeline, đổi context chính sang physical schema model.json (không phụ thuộc kết nối DB thật), thêm validator (`sqlglot`) với retry loop.

---

## Liên kết với các tính năng khác

| Tính năng | Liên quan |
|---|---|
| **Document Ingestion** (`DOC-document-ingestion.md`) | Project docs được embed vào ChromaDB bởi ingest pipeline — dùng lại collection `project_docs`, cùng cơ chế rerank với Schema Gen |
| **Query Executor** (`query-executor-implementation-rules.md` trong dbflow-frontend) | Text-to-SQL là sub-feature của Query Executor; SQL sinh ra đặt vào Monaco editor rồi Safeguard Layer + Execute mới chạy (phần Execute không đổi trong lần cập nhật này) |
| **Schema Gen Pipeline** (`DOC-schema-gen-pipeline.md`) | Dùng chung graph, chung `retriever_node`/`reranker_node`, chung cơ chế `validation_issues`/`retry_count`. Khác node sinh output cuối (`sql_generator`/`sql_validator` thay vì `schema_generator`/`schema_editor`/`validator`) |
