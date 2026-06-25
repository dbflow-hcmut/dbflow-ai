Để chạy repo này, trước tiên cần cài Python 3.11+. Đây là các bước từ đầu:

Bash Check project structure and dependencies
IN
ls /Users/admin/Documents/study/dbflow/dbflow-ai/ 2>/dev/null && cat /Users/admin/Documents/study/dbflow/dbflow-ai/pyproject.toml 2>/dev/null | head -40

OUT
API_USAGE.md
DOC-part1.md
DOC.md
LICENSE
LOCAL_SETUP.md
Makefile
README.md
SETUP.md
docker-compose.prod.yml
docs
langgraph.json
pyproject.toml
src
static
testcase
tests
uv.lock
[project]
name = "agent"
version = "0.0.1"
description = "Starter template for making a new agent LangGraph."
authors = [
    { name = "William Fu-Hinthorn", email = "13333726+hinthornw@users.noreply.github.com" },
]
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.10"
dependencies = [
    "langgraph>=1.0.0",
    "python-dotenv>=1.0.1",
    "langchain-google-genai>=2.0.0",
    "langchain-community>=0.4.0",
    "langchain-text-splitters>=1.1.0",
    "chromadb>=1.0.0",
    "python-docx>=1.1.0",
]


[project.optional-dependencies]
dev = ["mypy>=1.11.1", "ruff>=0.6.1"]

[build-system]
requires = ["setuptools>=73.0.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["langgraph.templates.agent", "agent"]
[tool.setuptools.package-dir]
"langgraph.templates.agent" = "src/agent"
"agent" = "src/agent"


[tool.setuptools.package-data]
"*" = ["py.typed"]

[tool.ruff]
lint.select = [
Các bước chạy từ đầu (chưa có Python)
Bước 1: Cài Python 3.11 qua Homebrew

# Cài Homebrew nếu chưa có
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Cài Python 3.11
brew install python@3.11
Bước 2: Cài uv (package manager nhanh hơn pip)

brew install uv
Bước 3: Vào thư mục project và tạo môi trường ảo

cd /Users/admin/Documents/study/dbflow/dbflow-ai

uv venv --python 3.11
source .venv/bin/activate
Bước 4: Cài dependencies

uv pip install -e .
uv pip install "langgraph-cli[inmem]"
Bước 5: Tạo file .env

cat > .env << 'EOF'
GOOGLE_API_KEY=your_google_api_key_here

# Tuỳ chọn - để trace/debug
LANGSMITH_TRACING=false
EOF
Thay your_google_api_key_here bằng key thật từ Google AI Studio.

Bước 6: Chạy server

langgraph dev
Server sẽ lên tại http://localhost:2024 với auto-reload và SQLite tự động.

Tóm lại thứ tự cần có:

Homebrew → Python 3.11 → uv
Tạo venv → cài packages
Tạo .env với GOOGLE_API_KEY
langgraph dev
Bước nào gặp lỗi thì báo mình nhé.

