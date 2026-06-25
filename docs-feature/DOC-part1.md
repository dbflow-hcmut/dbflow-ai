# DBFlow AI — Technical Documentation (Part 1)

> **Phạm vi**: Tài liệu kỹ thuật ghi lại kiến trúc, kỹ thuật đã triển khai, và cách hoạt động  
> của hệ thống tính đến thời điểm hiện tại.  
> **Ngày**: 29/03/2026

---

## Mục lục

1. [Tổng quan kiến trúc](#1-tổng-quan-kiến-trúc)
2. [Cấu trúc thư mục](#2-cấu-trúc-thư-mục)
3. [LangGraph — State & Nodes](#3-langgraph--state--nodes)
4. [RAG Pipeline (Retrieval-Augmented Generation)](#4-rag-pipeline-retrieval-augmented-generation)
5. [Xử lý Async trong LangGraph Dev](#5-xử-lý-async-trong-langgraph-dev)
6. [Validator — JSON Schema Validation](#6-validator--json-schema-validation)
7. [Luồng xử lý end-to-end](#7-luồng-xử-lý-end-to-end)
8. [Troubleshooting & Lessons Learned](#8-troubleshooting--lessons-learned)

---

## 1. Tổng quan kiến trúc

Hệ thống là một **AI Agent** chạy trên **LangGraph**, sử dụng **Google Gemini** làm LLM,
kết hợp **RAG** (ChromaDB + Google Embeddings) để đảm bảo output tuân thủ đúng JSON Schema
đã define sẵn cho từng level (Conceptual / Logical / Physical).

```
User message
    │
    ▼
┌─────────┐     ┌────────────┐     ┌───────────────────┐     ┌───────────┐
│  Router  │────▶│  Retriever │────▶│ Schema Generator  │────▶│ Validator │──▶ Response
│ (intent) │     │   (RAG)    │     │   hoặc Editor     │     │(JSON Sch.)│
└─────────┘     └────────────┘     └───────────────────┘     └───────────┘
    │
    ├──▶ Chatbot ──▶ Response  (intent = chat)
    ├──▶ Converter ──▶ ... (chưa implement)
    └──▶ Reverter  ──▶ ... (chưa implement)
```

**Tech stack**:
- **LangGraph** — StateGraph để quản lý flow
- **Google Gemini 2.5 Flash Lite** — LLM chính
- **Google Gemini Embedding 001** — Embedding model cho RAG
- **ChromaDB** — Local vector store (persistent)
- **LangChain** — Orchestration layer (messages, prompts)
- **Pydantic** — Data models & validation
- **jsonschema** — Validate output theo JSON Schema specs từ `/docs`

---

## 2. Cấu trúc thư mục

```
dbflow-ai/
├── docs/                          # Schema specifications (nguồn cho RAG)
│   ├── conceptual/
│   │   ├── model-schema.md        # Mô tả dạng markdown
│   │   ├── model.schema.json      # JSON Schema chính thức
│   │   ├── diagram-schema.md
│   │   └── diagram.schema.json
│   ├── logical/
│   │   ├── model-schema.md
│   │   ├── model.schema.json
│   │   ├── diagram-schema.md
│   │   └── diagram.schema.json
│   └── physical/
│       ├── model-schema.md
│       └── model.schema.json
│
├── src/agent/
│   ├── __init__.py                # Export graph
│   ├── graph.py                   # ★ Main LangGraph — wiring tất cả nodes
│   ├── state.py                   # AgentState (TypedDict)
│   ├── models.py                  # Pydantic models (enums, RouterOutput,...)
│   ├── prompts.py                 # System prompts cho từng node
│   ├── rag.py                     # ★ RAG pipeline (load, chunk, embed, retrieve)
│   ├── utils.py                   # Diagram layout utilities
│   └── nodes/
│       ├── __init__.py
│       ├── router.py              # Router node — phân loại intent
│       ├── retriever.py           # Retriever node — query ChromaDB
│       ├── schema_generator.py    # Generator + Editor nodes
│       └── validator.py           # Validator node — JSON Schema + structural checks
│
├── .chroma_db/                    # ChromaDB persistent storage (gitignored)
├── langgraph.json                 # LangGraph config
└── pyproject.toml                 # Dependencies
```

---

## 3. LangGraph — State & Nodes

### 3.1. AgentState (`state.py`)

State là một `TypedDict` — LangGraph tự quản lý việc merge state giữa các node.

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[AnyMessage], add_messages]  # Chat history (auto-merge)
    schema_model: Optional[Dict[str, Any]]      # model.json hiện tại
    ui_diagram: Optional[Dict[str, Any]]        # diagram.json hiện tại
    history: List[Dict[str, Any]]               # Stack lưu version cũ (cho revert)
    current_level: str                          # "conceptual" | "logical" | "physical"
    user_intent: Optional[str]                  # "create" | "edit" | "convert" | ...
    retrieval_context: Optional[str]            # ★ RAG context — inject vào prompt LLM
```

**Điểm quan trọng**:
- `messages` dùng `add_messages` reducer → LangGraph tự append, không overwrite.
- Các field khác (schema_model, ui_diagram,...) → overwrite trực tiếp khi node return.
- `retrieval_context` là text đã format từ RAG, được inject vào system prompt.

### 3.2. Các Nodes

| Node | File | Chức năng |
|------|------|-----------|
| `router` | `nodes/router.py` | Dùng Gemini + structured output → `RouterOutput(intent, reasoning)` |
| `retriever` | `nodes/retriever.py` | Query ChromaDB → lấy schema specs liên quan → set `retrieval_context` |
| `schema_generator` | `nodes/schema_generator.py` | Tạo schema mới từ NL, inject RAG context vào prompt |
| `schema_editor` | `nodes/schema_generator.py` | Chỉnh sửa schema hiện tại, gửi kèm current model+diagram |
| `validator` | `nodes/validator.py` | Validate bằng JSON Schema + structural checks |
| `chatbot` | `graph.py` | Trả lời câu hỏi chung, hiển thị schema context nếu có |
| `schema_converter` | `graph.py` | Placeholder — chưa implement |
| `reverter` | `graph.py` | Placeholder — chưa implement |

### 3.3. Conditional Routing

```python
# Router output → chọn node tiếp theo
route_intent(state) → {
    "create" → "retriever"    # Qua RAG trước
    "edit"   → "retriever"    # Qua RAG trước
    "chat"   → "chatbot"      # Trả lời trực tiếp
    ...
}

# Sau retriever → chọn generator hay editor
_route_after_retriever(state) → {
    "create" → "schema_generator"
    "edit"   → "schema_editor"
}
```

**Tại sao cần 2 bước routing?**  
Vì cả `create` và `edit` đều cần RAG context, nên đi qua `retriever` trước.
Sau đó mới phân nhánh sang generator hoặc editor.

---

## 4. RAG Pipeline (Retrieval-Augmented Generation)

### 4.1. Tại sao cần RAG?

Thư mục `/docs` chứa JSON Schema specs chi tiết cho 3 level × 2 loại (model + diagram).
Tổng dung lượng lớn, không thể nhét hết vào prompt mỗi request.

**Giải pháp**: Embed tất cả docs → vector store → mỗi request chỉ query lấy phần liên quan
→ inject vào prompt. Tiết kiệm tokens, tăng accuracy.

### 4.2. Quy trình indexing (`rag.py`)

```
/docs/**/*.md + *.json
        │
        ▼
   ┌─────────────────┐
   │  Load & Chunk    │  Markdown: split by headers → sub-chunk ~1200 chars
   │                  │  JSON: sub-chunk ~1500 chars
   └────────┬────────┘
            │ + metadata: {level, doc_type, format, source}
            ▼
   ┌─────────────────┐
   │  Embed           │  Google Gemini Embedding 001
   │  (models/gemini- │  (model: "models/gemini-embedding-001")
   │   embedding-001) │
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │  ChromaDB        │  Collection: "schema_docs"
   │  (persistent)    │  Lưu tại: .chroma_db/
   └─────────────────┘
```

**Smart rebuild**: Hệ thống hash toàn bộ content docs. Nếu hash không thay đổi → dùng
index cũ, không re-embed (tiết kiệm API calls + thời gian startup).

### 4.3. Metadata & Filtering

Mỗi chunk được gắn metadata:

```python
{
    "level": "conceptual" | "logical" | "physical",
    "doc_type": "model" | "diagram",
    "format": "md" | "json",
    "source": "docs/logical/model-schema.md",
    "chunk_index": 0,      # Thứ tự chunk trong file
    "h2": "column",        # Header markdown (nếu có)
}
```

Khi retrieve, filter theo `level` + `doc_type` để chỉ lấy docs liên quan:

```python
# Ví dụ: user đang ở level "logical" và muốn "create"
model_docs = await aretrieve(query=..., level="logical", doc_type="model", k=4)
diagram_docs = await aretrieve(query=..., level="logical", doc_type="diagram", k=3)
# → Tổng 7 chunks context, chỉ gồm logical specs
```

### 4.4. Inject vào Prompt

Retrieved docs được format thành text:

```
--- Reference 1: [LOGICAL / MODEL — docs/logical/model-schema.md] ---
## `table`
* `id`: định danh bảng (prefix `lid_`).
* `name`: tên bảng.
...

--- Reference 2: [LOGICAL / MODEL — docs/logical/model.schema.json] ---
JSON Schema: Logical Relational Schema
{
  "$schema": "https://json-schema.org/draft/2019-09/schema",
  ...
```

Text này được inject vào `{retrieval_context}` placeholder trong prompt:

```python
SCHEMA_GENERATOR_PROMPT = """
...
## Schema Specification Reference
{retrieval_context}     ← ★ RAG context đặt ở đây
...
"""
```

---

## 5. Xử lý Async trong LangGraph Dev

### 5.1. Vấn đề: BlockingError

LangGraph dev server chạy trên **ASGI** (async). Nếu code có **blocking I/O** (đọc file,
import nặng, ChromaDB operations), nó sẽ block event loop → server detect và throw
`BlockingError`.

Các thao tác bị block:
- `import chromadb` (load nhiều sub-modules, đọc file system)
- `import jsonschema` (load `jsonschema_specifications`, dùng `iterdir()`)
- `ChromaDB.PersistentClient()` (đọc/ghi SQLite)
- `vectorstore.similarity_search()` (query SQLite + compute embeddings)
- `Path.read_text()`, `Path.exists()` (file I/O)

### 5.2. Giải pháp: `asyncio.to_thread()`

Wrap tất cả blocking operations vào `asyncio.to_thread()` — chạy trong thread pool riêng,
không block event loop.

**Pattern áp dụng**:

```python
# ❌ SAI — block event loop
async def my_node(state):
    import jsonschema                         # blocking import
    data = Path("file.json").read_text()      # blocking file I/O
    result = vectorstore.similarity_search()  # blocking DB query

# ✅ ĐÚNG — wrap trong thread
def _sync_work():
    """Hàm sync chứa tất cả blocking operations."""
    import jsonschema
    data = Path("file.json").read_text()
    result = vectorstore.similarity_search()
    return result

async def my_node(state):
    result = await asyncio.to_thread(_sync_work)  # chạy trong thread riêng
```

**Áp dụng trong project**:

| File | Hàm sync (chạy trong thread) | Hàm async (gọi từ node) |
|------|------------------------------|--------------------------|
| `rag.py` | `_retrieve_sync()` | `aretrieve()` |
| `validator.py` | `_run_validation()` | `validator_node()` |

---

## 6. Validator — JSON Schema Validation

### 6.1. Hai tầng validation

**Tầng 1: JSON Schema Validation**

Dùng file `.schema.json` từ `/docs/<level>/` để validate output LLM
theo đúng spec đã define. Ví dụ:
- Logical: check `model.id` phải có prefix `lid_`, `tables` phải có `columns`, v.v.
- Conceptual: check `entities` phải có `attributes`, mỗi attribute có `kind` + `isKey`.

```python
model_schema = _load_json_schema("logical", "model")
# → Đọc docs/logical/model.schema.json
issues = _validate_with_json_schema(raw_model, model_schema, "model.json")
# → ["❌ model.json `tables.0.columns.0.id`: 'xxx' does not match '^lid_'"]
```

**Tầng 2: Structural Checks (generic)**

Kiểm tra logic nghiệp vụ mà JSON Schema không cover:

| Level | Check |
|-------|-------|
| Conceptual | Entity mạnh phải có key attribute; relationship ends trỏ đúng entity ID |
| Logical | Mỗi table phải có PK column; FK references trỏ đúng table/column ID |
| Physical | Không duplicate table name trong cùng schema |

### 6.2. Tại sao không dùng Pydantic models cho validation?

Ban đầu dùng `SchemaModel` (Pydantic) để validate. Nhưng khi chuyển sang RAG, LLM output
theo format từ `/docs` specs (khác hoàn toàn với Pydantic models cũ):

```python
# Pydantic cũ: tables, fields, relationships.source_table_id
# Docs spec:   entities, attributes, relationships.ends[].entityId  (conceptual)
#              tables, columns, roles.foreignKey.refTableId          (logical)
```

→ **Giải pháp**: Validate bằng JSON Schema files gốc — luôn đúng format dù LLM output 
ở level nào.

---

## 7. Luồng xử lý end-to-end

### Ví dụ: User gửi "Thiết kế DB cho hệ thống quản lý trường học"

```
1. [__start__] → messages: [HumanMessage("Thiết kế DB cho hệ thống quản lý trường học")]

2. [router] → Gemini classify intent
   → user_intent: "create"

3. [retriever] → Query ChromaDB
   Filter: level="logical", doc_type="model" (k=4) + "diagram" (k=3)
   → retrieval_context: "--- Reference 1: [LOGICAL/MODEL] ... table, column, roles..."

4. [schema_generator] → Gemini generate schema
   Prompt = SCHEMA_GENERATOR_PROMPT.format(retrieval_context=...)
   Input: user message + schema specs context
   Output: model.json + diagram.json (extracted from code blocks)
   → schema_model: {...}, ui_diagram: {...}

5. [validator] → JSON Schema validation + structural checks
   Load docs/logical/model.schema.json → validate model
   Check: PK exists? FK valid? Duplicate names?
   → messages: [AIMessage("✅ Schema validation passed.")]

6. [END] → Return to user with schema summary
```

### Ví dụ: User gửi "Thêm trường email vào bảng students"

```
1. [router] → user_intent: "edit"
2. [retriever] → Lấy logical specs
3. [schema_editor] → Gemini nhận current schema + RAG context + edit request
   → Chỉ thêm column email, giữ nguyên phần còn lại
4. [validator] → Validate updated schema
5. [END]
```

---

## 8. Troubleshooting & Lessons Learned

### 8.1. Embedding model 404

```
❌ models/text-embedding-004 is not found
✅ models/gemini-embedding-001      ← Tên đúng
```

**Cách tìm**: Dùng `client.models.list()` để list models có sẵn, filter "embed".

### 8.2. ChromaDB `delete_collection` — collection not found

```python
# ❌ Crash khi collection chưa tồn tại
client.delete_collection("schema_docs")

# ✅ Catch tất cả exceptions
try:
    client.delete_collection("schema_docs")
except (ValueError, Exception):
    pass
```

### 8.3. BlockingError trong LangGraph Dev

**Nguyên nhân**: LangGraph dev server dùng `blockbuster` library để detect blocking calls
trong async context. Bất kỳ file I/O, heavy import nào cũng bị bắt.

**Giải pháp chung**: Mọi thao tác blocking → wrap trong `asyncio.to_thread()`.

**Các import bị ảnh hưởng**:
- `import chromadb` → load hàng chục sub-modules, đọc file system
- `import jsonschema` → `jsonschema_specifications` dùng `iterdir()` đọc schema files

### 8.4. LLM output không match Pydantic models

**Vấn đề**: Khi dùng RAG inject docs specs, LLM output theo format docs (tốt!), nhưng
validator dùng Pydantic models cũ → crash.

**Giải pháp**: Bỏ Pydantic validation, dùng `jsonschema` library validate trực tiếp
bằng JSON Schema files từ `/docs`.

### 8.5. Chroma deprecation warning

```
LangChainDeprecationWarning: The class `Chroma` was deprecated in LangChain 0.2.9
→ pip install langchain-chroma
→ from langchain_chroma import Chroma
```

Chưa fix vì không ảnh hưởng chức năng. Có thể fix sau.

---

## Phụ lục: Dependencies

```toml
[project.dependencies]
langgraph          >= 1.0.0       # StateGraph framework
python-dotenv      >= 1.0.1       # Load .env
langchain-google-genai >= 2.0.0   # Gemini LLM + Embeddings
langchain-community >= 0.4.0      # Chroma vectorstore wrapper
langchain-text-splitters >= 1.1.0 # Markdown + recursive text splitting
chromadb           >= 1.0.0       # Local vector DB
```

---

*Tiếp theo (Part 2): Schema Converter, Reverter, và tối ưu hóa prompt engineering.*
