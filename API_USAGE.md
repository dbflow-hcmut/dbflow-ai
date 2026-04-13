# Hướng Dẫn Sử Dụng API

## 🌐 Base URLs

**Local Development:**
```
http://localhost:2024
```

**Production Server:**
```
http://your-server-ip:2024
```

## 📚 API Documentation

Sau khi server chạy, truy cập:
- **Swagger UI**: http://localhost:2024/docs
- **ReDoc**: http://localhost:2024/redoc

## 🚀 Các Endpoint Chính

### 1. Health Check

```bash
curl http://localhost:2024/ok
```

Response:
```json
{"ok": "ok"}
```

### 2. Tạo Thread Mới

Thread là một phiên chat/conversation.

```bash
curl -X POST http://localhost:2024/threads \
  -H "Content-Type: application/json" \
  -d '{}'
```

Response:
```json
{
  "thread_id": "abc123...",
  "created_at": "2026-04-04T10:00:00Z"
}
```

### 3. Chạy Agent (Generate Schema)

Gửi yêu cầu tạo database schema:

```bash
curl -X POST http://localhost:2024/threads/{thread_id}/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "agent",
    "input": {
      "messages": [
        {
          "role": "user",
          "content": "Create a schema for a simple blog system with users, posts, and comments"
        }
      ]
    }
  }'
```

Response:
```json
{
  "run_id": "run123...",
  "thread_id": "abc123...",
  "status": "pending"
}
```

### 4. Xem Kết Quả

#### a) Stream Response (Real-time)

```bash
curl -N http://localhost:2024/threads/{thread_id}/runs/{run_id}/stream
```

#### b) Get Final State

```bash
curl http://localhost:2024/threads/{thread_id}/state
```

Response:
```json
{
  "values": {
    "messages": [...],
    "schema_type": "conceptual",
    "schema": {
      "entities": [...],
      "relationships": [...]
    },
    "diagram": "..."
  }
}
```

### 5. Lấy Lịch Sử Thread

```bash
curl http://localhost:2024/threads/{thread_id}/history
```

## 🐍 Python Client Example

### Installation

```bash
pip install langgraph-sdk
```

### Sử dụng SDK

```python
from langgraph_sdk import get_client

# Kết nối tới server
client = get_client(url="http://localhost:2024")

# Tạo thread mới
thread = client.threads.create()
print(f"Thread ID: {thread['thread_id']}")

# Chạy agent
run = client.runs.create(
    thread_id=thread["thread_id"],
    assistant_id="agent",
    input={
        "messages": [
            {
                "role": "user",
                "content": "Create a conceptual schema for an e-commerce system"
            }
        ]
    }
)

# Stream kết quả real-time
for chunk in client.runs.stream(
    thread_id=thread["thread_id"],
    run_id=run["run_id"]
):
    print(chunk)

# Hoặc đợi kết quả cuối cùng
result = client.runs.join(
    thread_id=thread["thread_id"],
    run_id=run["run_id"]
)
print(result)

# Lấy state hiện tại
state = client.threads.get_state(thread_id=thread["thread_id"])
print(state["values"])
```

## 📝 Complete Example - Multi-turn Conversation

```python
from langgraph_sdk import get_client

client = get_client(url="http://localhost:2024")

# Tạo thread
thread = client.threads.create()
thread_id = thread["thread_id"]

# Turn 1: Tạo conceptual schema
print("=== Creating Conceptual Schema ===")
run1 = client.runs.create(
    thread_id=thread_id,
    assistant_id="agent",
    input={
        "messages": [{
            "role": "user",
            "content": "Create a conceptual schema for a university management system"
        }]
    }
)
result1 = client.runs.join(thread_id=thread_id, run_id=run1["run_id"])
print(result1["values"]["schema"])

# Turn 2: Chuyển sang logical schema
print("\n=== Converting to Logical Schema ===")
run2 = client.runs.create(
    thread_id=thread_id,
    assistant_id="agent",
    input={
        "messages": [{
            "role": "user",
            "content": "Now create a logical schema from this"
        }]
    }
)
result2 = client.runs.join(thread_id=thread_id, run_id=run2["run_id"])
print(result2["values"]["schema"])

# Turn 3: Sửa đổi schema
print("\n=== Modifying Schema ===")
run3 = client.runs.create(
    thread_id=thread_id,
    assistant_id="agent",
    input={
        "messages": [{
            "role": "user",
            "content": "Add a new entity for Departments"
        }]
    }
)
result3 = client.runs.join(thread_id=thread_id, run_id=run3["run_id"])
print(result3["values"]["schema"])
```

## 🔧 cURL Examples

### Workflow Hoàn Chỉnh

```bash
# 1. Tạo thread
THREAD_ID=$(curl -s -X POST http://localhost:2024/threads | jq -r '.thread_id')
echo "Thread ID: $THREAD_ID"

# 2. Gửi request
RUN_ID=$(curl -s -X POST http://localhost:2024/threads/$THREAD_ID/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "agent",
    "input": {
      "messages": [{
        "role": "user",
        "content": "Create a logical schema for a library management system"
      }]
    }
  }' | jq -r '.run_id')
echo "Run ID: $RUN_ID"

# 3. Đợi hoàn thành và lấy kết quả
sleep 5
curl -s http://localhost:2024/threads/$THREAD_ID/state | jq '.values.schema'

# 4. Tiếp tục conversation
curl -s -X POST http://localhost:2024/threads/$THREAD_ID/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "agent",
    "input": {
      "messages": [{
        "role": "user",
        "content": "Add an entity for Members and Books"
      }]
    }
  }'
```

## 📊 Message Format

Input message format:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Your request here"
    }
  ]
}
```

Agent response format:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Your request"
    },
    {
      "role": "assistant",
      "content": "Schema generated successfully"
    }
  ],
  "schema_type": "conceptual|logical|physical",
  "schema": {
    "entities": [...],
    "relationships": [...]
  },
  "diagram": "mermaid diagram string"
}
```

## 🎯 Schema Types

Agent hỗ trợ 3 loại schema:

1. **Conceptual**: High-level entities và relationships
2. **Logical**: Chi tiết attributes, data types, constraints
3. **Physical**: SQL DDL statements cho specific database

Để chọn schema type, thêm vào prompt:

```python
"Create a logical schema for..."
"Generate physical schema for PostgreSQL for..."
```

## 🔍 Debugging

### Check Server Logs

```bash
# Docker logs
docker logs dbflow-ai -f

# Local dev
# Logs sẽ hiện trực tiếp trong terminal
```

### Common Issues

**1. Connection Refused**
```bash
# Kiểm tra server có chạy không
curl http://localhost:2024/ok
```

**2. Slow Response**
- LLM call có thể mất 10-30s
- Dùng streaming để xem progress real-time

**3. Invalid Schema**
- Kiểm tra message format
- Xem validation errors trong response

## 🌟 Best Practices

1. **Reuse threads** cho multi-turn conversations
2. **Use streaming** cho UX tốt hơn
3. **Handle errors** gracefully
4. **Set timeouts** phù hợp (30-60s)
5. **Cache results** nếu cần

## 📱 Integration Examples

### React/Next.js

```typescript
const createSchema = async (prompt: string) => {
  // Create thread
  const threadRes = await fetch('http://localhost:2024/threads', {
    method: 'POST',
  });
  const { thread_id } = await threadRes.json();

  // Run agent
  const runRes = await fetch(`http://localhost:2024/threads/${thread_id}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      assistant_id: 'agent',
      input: {
        messages: [{ role: 'user', content: prompt }]
      }
    })
  });
  const { run_id } = await runRes.json();

  // Get result
  const stateRes = await fetch(`http://localhost:2024/threads/${thread_id}/state`);
  const state = await stateRes.json();
  
  return state.values.schema;
};
```

### FastAPI Backend

```python
from fastapi import FastAPI
from langgraph_sdk import get_client

app = FastAPI()
client = get_client(url="http://localhost:2024")

@app.post("/generate-schema")
async def generate_schema(prompt: str):
    thread = client.threads.create()
    run = client.runs.create(
        thread_id=thread["thread_id"],
        assistant_id="agent",
        input={"messages": [{"role": "user", "content": prompt}]}
    )
    result = client.runs.join(
        thread_id=thread["thread_id"],
        run_id=run["run_id"]
    )
    return result["values"]["schema"]
```

## 🔐 Security Notes

- **Production**: Thêm authentication/API keys
- **Rate limiting**: Implement để tránh abuse
- **Input validation**: Validate user prompts
- **CORS**: Configure nếu gọi từ browser

## 📞 Support

- Docs: http://localhost:2024/docs
- GitHub Issues: [Your repo]
- LangGraph Docs: https://langchain-ai.github.io/langgraph/
