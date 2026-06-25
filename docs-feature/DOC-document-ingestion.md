# Document Ingestion Pipeline

## Vấn đề

Documents upload vào Hub hiện chỉ được lưu trên S3 và ghi metadata vào DB.
AI không đọc, không dùng các file này trong bất kỳ bước nào.
Mục tiêu: mỗi document upload vào Hub được tự động xử lý thành vector
và sử dụng như context khi user chat với AI trong cùng project.

---

## Tổng quan flow

```
User upload doc lên Hub
        │
        ▼
Backend lưu metadata vào DB  (status = uploaded)
        │
        ▼
Backend gọi AI Ingestion Service bất đồng bộ
        │
  ┌─────┴──────┐
  │ status = processing
  │
  ├── Download file từ S3
  ├── Extract text (theo loại file)
  ├── Chia nhỏ thành chunks
  ├── Embed từng chunk thành vector
  └── Lưu vào ChromaDB collection "project_docs"
        │
  ┌─────┴──────┐
  │ status = ready  (hoặc failed nếu lỗi)
        │
        ▼
Khi user chat → retriever_node kéo chunks
liên quan từ "project_docs" theo project_id
        │
        ▼
Inject vào prompt generator như business context
```

---

## Xử lý từng loại file

Tất cả loại file FE đang hỗ trợ đều xử lý được:

| Loại file | Cách extract |
|---|---|
| `.pdf` | Dùng pdfplumber để đọc text từng trang |
| `.docx`, `.doc` | Dùng python-docx để đọc các paragraph |
| `.txt`, `.md` | Đọc thẳng nội dung text |
| `.sql`, `.json`, `.csv` | Đọc thẳng nội dung text |
| `.svg` | Đọc như text, bỏ các XML tag nếu cần |
| `.png`, `.jpg`, `.jpeg`, `.webp` | Gửi sang Gemini Vision để mô tả nội dung và nhận dạng cấu trúc (đặc biệt hữu ích với ảnh chụp schema, ERD) |

Sau khi extract, tất cả đều đi qua cùng một bước: chia chunk → embed → lưu vào ChromaDB.

---

## Job lifecycle

Field `status` trong bảng `project_documents` đóng vai trò tracking job:

```
uploaded → processing → ready
                     └→ failed
```

- `uploaded`: vừa tạo xong record, chưa xử lý
- `processing`: AI service đang chạy ingestion
- `ready`: embed thành công, sẵn sàng cho RAG
- `failed`: extract hoặc embed thất bại

Khi delete document, ngoài xóa S3 còn cần xóa luôn các chunk tương ứng trong ChromaDB.

---

## Các thành phần cần thay đổi hoặc tạo mới

### dbflow-ai

**Tạo mới: AI Ingestion Sidecar**

Một FastAPI server nhỏ chạy song song với LangGraph server (cổng riêng).
Backend gọi vào đây để trigger ingestion. Sidecar này chịu trách nhiệm:
- Nhận thông tin document (s3_key, mime_type, project_id, document_id)
- Download từ S3
- Dispatch extract theo mime_type
- Chunk → embed → lưu vào ChromaDB collection riêng tên `project_docs`
- Trả về kết quả để backend cập nhật status

Collection `project_docs` hoàn toàn tách biệt với `schema_docs` (schema spec docs của hệ thống).
Mỗi chunk trong `project_docs` mang metadata: `project_id`, `document_id`, `title`, `chunk_index`.

**Sửa: rag.py**

Thêm helper để query `project_docs` collection, filter theo `project_id`.
Format kết quả thành text block để inject vào prompt.

**Sửa: state.py**

Thêm hai field vào `AgentState`:
- `project_id`: để retriever biết query project nào
- `project_docs_context`: kết quả retrieve từ project docs, truyền xuống generator

**Sửa: retriever_node**

Sau khi retrieve schema spec docs như hiện tại, nếu state có `project_id`
thì query thêm `project_docs` với câu hỏi của user.
Hai nguồn context này độc lập, không thay thế nhau.

**Sửa: prompts.py**

Thêm section "Project Business Context" vào prompt của schema_generator và schema_editor.
Section này inject nội dung từ `project_docs_context`.
Nếu không có docs nào → bỏ qua section, không ảnh hưởng flow hiện tại.

---

### dbflow-backend

**Tạo mới: AiIngestionService**

Module NestJS đơn giản, chỉ làm một việc: gọi HTTP đến AI Ingestion Sidecar.
Có hai method: `ingestDocument()` và `removeDocument()`.
Được inject vào `ProjectDocumentsService`.

**Sửa: ProjectDocumentsService**

- `create()`: thay `status = ready` thành `status = uploaded`, sau khi save xong thì gọi
  `runIngestion()` bất đồng bộ (fire-and-forget). `runIngestion()` tự cập nhật status
  theo kết quả từ AI sidecar.
- `remove()`: ngoài xóa S3, gọi thêm `aiIngestion.removeDocument()` để xóa embeddings.

---

### dbflow-frontend

**Sửa: api/ai/client.ts**

Thêm `project_id` vào phần `input` của LangGraph stream request.
`project_id` được truyền từ ChatBox xuống qua prop, hiện tại prop này đã có.

**Sửa: ProjectDocumentsHub**

Hiển thị status của từng document (queued / processing / ready / failed)
để user biết file nào đã sẵn sàng cho AI, file nào đang xử lý.

---

## Môi trường

Cần thêm vào env:

- `AI_INGEST_URL`: địa chỉ của AI Ingestion Sidecar (mặc định `http://localhost:8001`)
- `AI_INGEST_PORT`: cổng sidecar chạy
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME`:
  để sidecar tự download file từ S3 (backend không cần truyền raw bytes qua HTTP)

Dependencies cần thêm vào `pyproject.toml`:
`fastapi`, `uvicorn`, `pdfplumber`, `boto3`, `httpx`
(python-docx đã có sẵn)

---

## Điều chỉnh so với doc cũ

- Image không bị bỏ qua nữa — dùng Gemini Vision để mô tả, đặc biệt hữu ích
  khi user upload ảnh chụp màn hình schema hoặc diagram
- SVG được xử lý như text
- Tất cả file FE hỗ trợ đều được cover

---

## Nằm ngoài phạm vi lần này

- Re-ingestion khi user sửa title/description (nội dung file không đổi)
- Ingestion cho file đính kèm trong AI Chat (chỉ Hub upload)
- Auth trên AI Ingestion Sidecar (internal network, tin tưởng backend)
- Tuning chunk size theo loại file
