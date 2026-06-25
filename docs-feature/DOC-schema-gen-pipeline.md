# Schema Generation Pipeline

Pipeline áp dụng cho intent: `create` / `edit` / `forward_engineer` / `reverse_engineer`.
Intent `chat` đi thẳng vào chatbot_node, bỏ qua toàn bộ pipeline này.

---

| Bước | Tên | Mô tả |
|---|---|---|
| 1 | **Nạp state** | Lấy `AgentState` từ LangGraph thread hiện tại: `schema_model` đang có, `current_level`, `history`, `retry_count`. Nếu frontend gửi kèm `input_model` (schema từ diagram — serialized model.json) thì sync vào `schema_model` trước. `schema_model` sau bước này là schema hiện tại chính thức, dùng làm input cho intent `edit`. |
| 2 | **Phân loại intent** | `router_node` gọi LLM (temperature=0) để classify intent và detect level. Xác định `user_intent` (create / edit / forward_engineer / reverse_engineer) và `current_level` / `target_level` (conceptual / logical / physical). Reset `retry_count = 0`, `validation_issues = []` cho mỗi request mới. Emit routing info ra stream để FE biết intent đang xử lý. |
| 3 | **Hybrid retrieval (song song)** | Chạy song song hai nguồn: |
| | └ *Spec RAG* | Từ `schema_docs` → **luôn đọc full file theo `current_level`, không chunk, không rank**. File spec được chọn theo level đang generate (conceptual / logical / physical), mỗi level có file spec riêng. Bỏ nhánh fallback ChromaDB cho spec. Đây là nguồn bắt buộc — LLM phải tuân thủ format này, cắt bất kỳ phần nào đều có thể làm sai output. |
| | └ *Project RAG* | Từ `project_docs` → lấy top-N candidates (N = 3×k) theo cosine similarity từ ChromaDB, filter theo `project_id`. Lấy rộng hơn để bước re-rank có đủ margin. **Bỏ qua toàn bộ bước này và bước 3.5 nếu project chưa có document nào** (`project_docs_context = null`). |
| 3.5 | **Re-rank project_docs** | Chỉ chạy khi `project_docs_context` không null. Score lại N project chunks bằng hybrid scoring: `final_score = 0.6 × semantic_score + 0.4 × bm25_score`. `semantic_score` lấy lại từ cosine sim đã có của ChromaDB; `bm25_score` tính tại runtime từ keyword overlap giữa query và chunk text (không cần index riêng). Nếu tổng số chunks < N thì rank toàn bộ, không cần pad. Giữ top-k chunks sau rank. Gắn `rerank_score` vào metadata của mỗi chunk để phục vụ telemetry. |
| 4 | **Merge context** | Gộp kết quả vào state theo intent: `project_docs_context` = top-k chunks đã rank (luôn có nếu project có docs). `retrieval_context` (spec, full) **chỉ được nhét vào khi intent là `create` / `edit` / `forward_engineer` / `reverse_engineer`** — intent mới thêm sau mặc định không nhét spec trừ khi khai báo rõ. Spec luôn đặt trước project docs trong prompt nếu có. |
| 5 | **Xây prompt LLM** | Tổng hợp prompt theo intent: |
| | └ *create* | `SCHEMA_GENERATOR_PROMPT` + `retrieval_context` (spec) + `project_docs_context` + `level_specific_instructions` + `user_message`. |
| | └ *edit* | `SCHEMA_EDITOR_PROMPT` + `schema_model` hiện tại (JSON đầy đủ từ bước 1) + `retrieval_context` (spec) + `project_docs_context` + `level_specific_instructions` + `user_message`. |
| | └ *forward_engineer* | `SCHEMA_GENERATOR_PROMPT` + `retrieval_context` (spec) + `project_docs_context` + `level_specific_instructions` + `user_message` + **`raw_input`** (SQL DDL mà user cung cấp — LLM đọc DDL này để gen schema). |
| | └ *reverse_engineer* | `SCHEMA_GENERATOR_PROMPT` + `retrieval_context` (spec) + `project_docs_context` + `level_specific_instructions` + `user_message` + **`raw_input`** (schema JSON / DB description mà user cung cấp). |
| | | `user_message` là câu yêu cầu gốc của user — LLM cần biết để hiểu đúng ý định chỉnh sửa hoặc context generate. Nếu đang ở retry (bước 8 gửi về): append danh sách `validation_issues` vào cuối prompt để LLM tự sửa. |
| 6 | **Gọi LLM & nhận kết quả** | Gọi Gemini (temperature=0.1, max_output_tokens=131072). LLM trả về text có chứa fenced code block `model.json`. Parse JSON ra khỏi text. Nếu parse thất bại (truncated output) thì retry nội bộ tối đa 2 lần với prompt yêu cầu regenerate. Sau khi parse thành công, chạy dedup ID để đảm bảo mọi `id` trong model là globally unique. |
| 7 | **Guardrails (validator_node)** | Validate `schema_model` vừa sinh ra theo hai lớp: |
| | └ *JSON Schema validation* | Kiểm tra model có conform đúng `model.schema.json` của level không: field bắt buộc, kiểu dữ liệu, enum values, pattern ID. |
| | └ *Structural checks* | Conceptual: entity trùng tên, strong entity thiếu key attribute, relationship tham chiếu entity không tồn tại. Logical: table thiếu PK, FK trỏ vào table/column không tồn tại, table trùng tên. Physical: table trùng tên trong cùng schema. |
| 8 | **Retry loop** | Nếu có `validation_issues` và `retry_count` chưa vượt ngưỡng (mặc định 2): tăng `retry_count`, emit thông báo "auto-correcting…" ra stream, quay lại **bước 5** với issues làm feedback. Nếu đã hết retry: emit danh sách issues đầy đủ như warning và tiếp tục trả kết quả. |
| 9 | **Trả kết quả & stream** | Emit `schema_model` (model.json) ra stream về FE. FE tự render ERD từ model.json — không có bước render phía server. FE cũng tự generate DDL từ model.json khi cần (đã có sẵn `ddl-generator.ts`). Persist `schema_model` mới vào `AgentState` (ghi đè giá trị cũ) để request tiếp theo ở bước 1 nhận được schema đã cập nhật. Lưu snapshot vào `history` trong state để hỗ trợ undo. |
| 10 | **Telemetry** | Log vào LangGraph run metadata: `thread_id`, `intent`, `level`, số `validation_issues`, số `retry_count`, `token_count`, `latency`. FE nhận `effective_level` và `intent` qua routing message để cập nhật UI. |

---

## Điểm khác so với pipeline mẫu

| Pipeline mẫu | Hệ thống này | Lý do |
|---|---|---|
| Embed prompt → lưu embedding_hash | Chưa có | Có thể thêm để cache retrieval result cho prompt giống nhau |
| Re-rank hợp nhất | Hybrid re-rank chỉ trên `project_docs` (0.6 semantic + 0.4 BM25); `schema_docs` luôn full, không rank | Spec phải nguyên vẹn để LLM gen đúng format; project docs mới cần rank để lọc noise |
| LLM trả DDL + citations | FE tự gen DDL từ model.json | DDL từ structured JSON đáng tin hơn DDL từ LLM |
| Kiểm chứng ERD phía server | FE tự render ERD (React Flow) | ERD là client-side concern |
| Migration ngoài runtime | Migration do BE xử lý độc lập | AI pipeline không chạm vào DB thật |

---

## Flow tóm tắt

```
START
  → router_node          (bước 2)
  → retriever_node       (bước 3)
  → reranker_node        (bước 3.5 — project_docs only; spec đi thẳng qua)
  → merge_node           (bước 4)
  → schema_generator     (bước 5 + 6)
  → validator_node       (bước 7)
  → [issues?] ──yes──→  schema_generator  (bước 8, retry)
              └─ no ──→ END               (bước 9 + 10)
```
