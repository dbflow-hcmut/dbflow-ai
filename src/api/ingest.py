"""FastAPI document ingestion sidecar for DBFlow AI.

Endpoints:
  POST   /api/ingest                          — extract, chunk, embed a document
  DELETE /api/ingest/{project_id}/{document_id} — remove all chunks for a doc
  GET    /api/health                          — health check
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import traceback

import boto3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel

from agent.rag import get_project_vectorstore

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="DBFlow AI Ingest Sidecar", version="1.0.0")

# ── S3 client ────────────────────────────────────────────────────────────────

def _make_s3_client():
    """Create a boto3 S3 client from environment variables."""
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "ap-southeast-1"),
    )


# ── Text extraction ──────────────────────────────────────────────────────────

def _extract_text_sync(data: bytes, mime_type: str, file_name: str) -> str:
    """Extract plain text from document bytes according to mime type.

    All heavy imports are done inside the function to avoid import-time
    overhead for optional packages.
    """
    # PDF
    if mime_type == "application/pdf":
        import pdfplumber

        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts)

    # Word documents
    if mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(data))
        return "\n".join(para.text for para in doc.paragraphs if para.text)

    # SVG — strip XML tags, keep visible text
    if mime_type == "image/svg+xml" or file_name.lower().endswith(".svg"):
        raw = data.decode("utf-8", errors="replace")
        no_tags = re.sub(r"<[^>]+>", " ", raw)
        return " ".join(no_tags.split())

    # Raster images — Gemini Vision OCR
    if mime_type.startswith("image/"):
        from langchain_core.messages import HumanMessage as LCHumanMessage
        from langchain_google_genai import ChatGoogleGenerativeAI

        b64 = base64.b64encode(data).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"

        llm = ChatGoogleGenerativeAI(
            model=os.getenv("API_MODEL", "gemini-1.5-flash"),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )
        msg = LCHumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                },
                {
                    "type": "text",
                    "text": (
                        "Extract all visible text from this image. "
                        "If it contains a database diagram, ERD, or schema, "
                        "describe all entities, attributes, and relationships you can see."
                    ),
                },
            ]
        )
        response = llm.invoke([msg])
        content = response.content
        if isinstance(content, list):
            return " ".join(
                p["text"] if isinstance(p, dict) else str(p) for p in content
            )
        return str(content)

    # Everything else: plain text (SQL, CSV, JSON, TXT, MD, …)
    return data.decode("utf-8", errors="replace")


# ── Request / response models ────────────────────────────────────────────────

class IngestRequest(BaseModel):
    """Body for POST /api/ingest."""

    documentId: str
    projectId: str
    s3Key: str
    mimeType: str
    fileName: str
    title: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health() -> dict:
    """Return a simple health-check response."""
    return {"status": "ok"}


@app.post("/api/ingest")
async def ingest_document(body: IngestRequest) -> dict:  # noqa: C901
    """Download a document from S3, extract text, chunk and embed it.

    Steps:
    1. Download the file from S3.
    2. Extract text according to mime type.
    3. Skip if no extractable text.
    4. Split into chunks (1200 chars, 200 overlap).
    5. Add chunks to the project's ChromaDB collection with metadata.
    """
    try:
        # ── 1. Download from S3 ──────────────────────────────────────────────
        bucket = os.getenv("S3_BUCKET_NAME", "")
        if not bucket:
            raise ValueError("S3_BUCKET_NAME env var not set")

        def _download() -> bytes:
            s3 = _make_s3_client()
            obj = s3.get_object(Bucket=bucket, Key=body.s3Key)
            return obj["Body"].read()

        logger.info("Downloading s3://%s/%s", bucket, body.s3Key)
        raw_bytes: bytes = await asyncio.to_thread(_download)
        logger.info("Downloaded %d bytes", len(raw_bytes))

        # ── 2. Extract text ──────────────────────────────────────────────────
        logger.info("Extracting text from %s (mime: %s)", body.fileName, body.mimeType)
        text: str = await asyncio.to_thread(
            _extract_text_sync, raw_bytes, body.mimeType, body.fileName
        )
        logger.info("Extracted %d chars", len(text))

        # ── 3. Skip if empty ─────────────────────────────────────────────────
        if not text or not text.strip():
            logger.info("No extractable text — skipping embed")
            return {"status": "skipped", "reason": "no extractable text"}

        # ── 4. Chunk ─────────────────────────────────────────────────────────
        splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=200)
        chunks = splitter.split_text(text)
        logger.info("Split into %d chunks", len(chunks))

        from langchain_core.documents import Document

        docs = [
            Document(
                page_content=chunk,
                metadata={
                    "project_id": body.projectId,
                    "document_id": body.documentId,
                    "title": body.title,
                    "mime_type": body.mimeType,
                    "chunk_index": idx,
                },
            )
            for idx, chunk in enumerate(chunks)
        ]

        # ── 5. Embed into ChromaDB ────────────────────────────────────────────
        logger.info("Embedding %d chunks into ChromaDB project_docs...", len(docs))

        def _add_docs() -> None:
            vs = get_project_vectorstore()
            vs.add_documents(docs)

        await asyncio.to_thread(_add_docs)
        logger.info("Ingestion complete for document %s", body.documentId)

        return {
            "status": "ok",
            "documentId": body.documentId,
            "projectId": body.projectId,
            "chunks": len(docs),
        }

    except Exception as exc:
        logger.error(
            "Ingest failed for document %s:\n%s",
            body.documentId,
            traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class TextToSqlRequest(BaseModel):
    """Body for POST /api/text-to-sql."""

    nl_query: str
    dbms: str  # "postgresql" | "mysql" | "sqlserver"
    schema_tables: list  # List of IntrospectedTable dicts from introspect endpoint
    project_id: Optional[str] = None


def _format_schema_context(schema_tables: list, dbms: str) -> str:
    """Format introspected tables into a readable schema context string for the LLM."""
    if not schema_tables:
        return "No schema information available."

    dbms_label = {"postgresql": "PostgreSQL", "mysql": "MySQL", "sqlserver": "SQL Server"}.get(
        dbms.lower(), dbms.upper()
    )
    lines = [f"Database: {dbms_label}", ""]

    for table in schema_tables:
        name = table.get("name", "unknown")
        lines.append(f"Table: {name}")

        columns = table.get("columns", [])
        for col in columns:
            col_name = col.get("name", "?")
            col_type = col.get("dataType", "?")
            length = col.get("length")
            nullable = col.get("nullable", True)
            is_pk = col.get("isPrimaryKey", False)
            is_unique = col.get("isUnique", False)
            auto_inc = col.get("autoIncrement", False)
            default = col.get("defaultValue")

            flags = []
            if is_pk:
                flags.append("PRIMARY KEY")
            if auto_inc:
                flags.append("AUTO INCREMENT")
            if is_unique and not is_pk:
                flags.append("UNIQUE")
            if not nullable:
                flags.append("NOT NULL")
            if default is not None:
                flags.append(f"DEFAULT {default}")

            type_str = f"{col_type}({length})" if length else col_type
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            lines.append(f"  - {col_name}: {type_str}{flag_str}")

        fks = table.get("foreignKeys", [])
        for fk in fks:
            fk_cols = ", ".join(fk.get("columns", []))
            ref_table = fk.get("refTable", "?")
            ref_cols = ", ".join(fk.get("refColumns", []))
            lines.append(f"  FK: ({fk_cols}) → {ref_table}({ref_cols})")

        lines.append("")

    return "\n".join(lines).strip()


TEXT_TO_SQL_SYSTEM_PROMPT = """You are an expert SQL assistant. Generate a single SQL query based on the user's natural language description and the database schema provided.

Rules:
- Output ONLY the SQL query, nothing else — no explanation, no markdown fences, no code blocks.
- Use the exact table and column names from the schema.
- Write clean, readable SQL with proper formatting.
- Use appropriate JOINs based on foreign key relationships.
- Add a LIMIT clause for SELECT queries unless the user specifies otherwise.
- Use syntax compatible with the specified DBMS.
- If the request is ambiguous, make a reasonable assumption and generate the most likely query.
"""


@app.post("/api/text-to-sql")
async def text_to_sql(body: TextToSqlRequest) -> dict:
    """Generate SQL from a natural language query using the DB schema as context.

    Steps:
    1. Format schema tables into a readable context.
    2. Fetch relevant project documents from ChromaDB (if project_id provided).
    3. Call Gemini to generate the SQL query.
    4. Return the SQL string.
    """
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage as LCHumanMessage

        schema_context = _format_schema_context(body.schema_tables, body.dbms)

        # Fetch project docs from ChromaDB if project_id is provided
        project_docs_context = ""
        if body.project_id:
            try:
                from agent.rag import aretrieve_project_docs, format_project_docs_context

                docs = await aretrieve_project_docs(body.nl_query, body.project_id, k=3)
                if docs:
                    project_docs_context = (
                        "\n\nAdditional project documentation:\n"
                        + format_project_docs_context(docs)
                    )
            except Exception as e:
                logger.warning("Failed to fetch project docs for text-to-sql: %s", e)

        human_content = (
            f"Database Schema:\n{schema_context}"
            f"{project_docs_context}"
            f"\n\nGenerate SQL for: {body.nl_query}"
        )

        llm = ChatGoogleGenerativeAI(
            model=os.getenv("API_MODEL", "gemini-1.5-flash"),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=0,
        )

        response = await llm.ainvoke(
            [SystemMessage(content=TEXT_TO_SQL_SYSTEM_PROMPT), LCHumanMessage(content=human_content)]
        )

        sql = response.content
        if isinstance(sql, list):
            sql = " ".join(p["text"] if isinstance(p, dict) else str(p) for p in sql)
        sql = str(sql).strip()

        # Strip markdown fences if the model includes them despite instructions
        if sql.startswith("```"):
            lines = sql.split("\n")
            sql = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()

        return {"sql": sql}

    except Exception as exc:
        logger.error("text-to-sql failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/api/ingest/{project_id}/{document_id}")
async def delete_document(project_id: str, document_id: str) -> dict:
    """Remove all chunks for a document from the project's ChromaDB collection."""

    def _delete() -> None:
        vs = get_project_vectorstore()
        vs.delete(
            where={
                "$and": [
                    {"project_id": project_id},
                    {"document_id": document_id},
                ]
            }
        )

    await asyncio.to_thread(_delete)

    return {"status": "ok", "projectId": project_id, "documentId": document_id}
