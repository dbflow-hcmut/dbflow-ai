# DBFlow AI — Hướng dẫn cài đặt & chạy

## 1. Tạo & kích hoạt môi trường ảo

```bash
cd dbflow-ai

# Tạo venv (chỉ cần chạy 1 lần)
python3 -m venv .venv

# Kích hoạt
source .venv/bin/activate
```

> Terminal hiển thị `(.venv)` ở đầu dòng là thành công.

---

## 2. Cài dependencies

```bash
pip install "langgraph-cli[inmem]" langchain-google-genai python-dotenv
pip install -e .
```

---

## 3. Cấu hình API Key

1. Lấy key tại [Google AI Studio](https://aistudio.google.com/apikey)
2. Mở file `.env` và điền:

```dotenv
GOOGLE_API_KEY=AIzaSy...your-key-here...
```

---

## 4. Chạy

```bash
source .venv/bin/activate
langgraph dev
```

Thành công sẽ thấy:

```
- 🚀 API: http://127.0.0.1:2024
- 🎨 Studio UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
- 📚 API Docs: http://127.0.0.1:2024/docs
```

---

## Xử lý lỗi thường gặp

| Lỗi | Cách fix |
|------|----------|
| `SSL: CERTIFICATE_VERIFY_FAILED` | `open "/Applications/Python 3.12/Install Certificates.command"` |
| `429 RESOURCE_EXHAUSTED` | Tạo API key mới tại [Google AI Studio](https://aistudio.google.com/apikey) hoặc bật billing |
| `command not found: langgraph` | Chạy `source .venv/bin/activate` trước |
