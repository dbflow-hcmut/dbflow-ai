# Hướng Dẫn Chạy Local

## 📋 Yêu cầu

- **Python**: ≥ 3.11 (bắt buộc cho LangGraph CLI)
- **uv**: Package manager (khuyên dùng)
- **Docker**: Nếu muốn chạy production mode

## 🚀 Setup Lần Đầu

### 1. Tạo Virtual Environment

```bash
# Dùng uv (khuyên dùng)
uv venv

# Hoặc dùng Python built-in
python3.11 -m venv .venv
```

### 2. Kích Hoạt Virtual Environment

```bash
# macOS/Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 3. Cài Đặt Dependencies

```bash
# Dùng uv
uv pip install -e .
uv pip install "langgraph-cli[inmem]"

# Hoặc dùng pip
pip install -e .
pip install "langgraph-cli[inmem]"
```

### 4. Tạo File `.env`

```bash
cat > .env << 'EOF'
# Google API Key (bắt buộc)
GOOGLE_API_KEY=your_google_api_key_here

# LangSmith (optional - để trace & debug)
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_PROJECT=dbflow-ai
EOF
```

**⚠️ Lưu ý**: Thay `your_google_api_key_here` bằng API key thực của bạn.

## 🏃 Chạy Development Server

### Cách 1: LangGraph CLI (Khuyên dùng)

```bash
langgraph dev
```

Server sẽ chạy tại: **http://localhost:2024**

**Tính năng:**
- ✅ Auto-reload khi code thay đổi
- ✅ Tự động setup SQLite database
- ✅ Load env từ `.env` file
- ✅ LangGraph Studio UI

### Cách 2: Docker Compose (Production mode)

```bash
# Build image
langgraph build -t ghcr.io/dbflow-hcmut/dbflow-ai:latest

# Chạy container
docker compose -f docker-compose.prod.yml up

# Hoặc chạy detached
docker compose -f docker-compose.prod.yml up -d
```

Server sẽ chạy tại: **http://localhost:2024**

## 🧪 Chạy Tests

### Unit Tests

```bash
# Dùng uv
uv run pytest tests/unit_tests

# Hoặc pytest trực tiếp
pytest tests/unit_tests
```

### Integration Tests

```bash
pytest tests/integration_tests
```

## 📝 Các Lệnh Hữu Ích

### LangGraph CLI

```bash
# Xem version
langgraph --version

# Build Docker image
langgraph build -t your-image-name:tag

# Up production server
langgraph up

# Test graph locally
langgraph test
```

### Docker

```bash
# Xem logs
docker compose -f docker-compose.prod.yml logs -f

# Stop và xóa containers
docker compose -f docker-compose.prod.yml down

# Restart container
docker compose -f docker-compose.prod.yml restart

# Xóa volumes (CẢNH BÁO: mất data)
docker compose -f docker-compose.prod.yml down -v
```

## 🐛 Troubleshooting

### Lỗi: Python version < 3.11

```bash
# Cài Python 3.11+ qua pyenv
pyenv install 3.11
pyenv local 3.11

# Hoặc qua Homebrew (macOS)
brew install python@3.11
```

### Lỗi: langgraph-cli không tìm thấy

```bash
# Cài lại với inmem support
pip install -U "langgraph-cli[inmem]"
```

### Lỗi: GOOGLE_API_KEY missing

Đảm bảo file `.env` có và chứa `GOOGLE_API_KEY`:

```bash
echo $GOOGLE_API_KEY  # Kiểm tra env var đã load chưa
cat .env              # Kiểm tra file .env
```

### Lỗi: DATABASE_URI missing (khi chạy Docker)

File `docker-compose.prod.yml` đã được fix. Nếu vẫn lỗi:

```bash
# Thêm explicit vào docker-compose.prod.yml
- POSTGRES_URI=sqlite:///data/langgraph.db
```

## 📁 Cấu Trúc Project

```
dbflow-ai/
├── src/agent/          # Main agent code
├── docs/               # Schema documentation
├── tests/              # Unit & integration tests
├── .env                # Environment variables (local)
├── langgraph.json      # LangGraph config
└── pyproject.toml      # Python dependencies
```

## 🌐 API Endpoints

Khi server chạy, access:

- **API Docs**: http://localhost:2024/docs
- **Health Check**: http://localhost:2024/ok
- **LangGraph Studio**: Mở trong LangGraph Desktop app

## 📚 Tài Liệu Thêm

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangSmith Tracing](https://docs.smith.langchain.com/)
- [Gemini API](https://ai.google.dev/gemini-api/docs)
