"""RAG pipeline — embed /docs schema specifications into ChromaDB for retrieval.

This module:
1. Loads all .md and .json schema files from ``docs/``.
2. Chunks them with metadata (level: conceptual/logical/physical, doc_type: model/diagram).
3. Embeds using Google Generative AI Embeddings.
4. Stores in a persistent local ChromaDB collection.
5. Exposes an async ``aretrieve()`` function for use in the LangGraph retriever node.

All ChromaDB operations are wrapped in ``asyncio.to_thread`` so they never
block the async event loop used by LangGraph's ASGI server.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # dbflow-ai/
DOCS_DIR = _PROJECT_ROOT / "docs"
CHROMA_PERSIST_DIR = _PROJECT_ROOT / ".chroma_db"

# ── Embedding model ─────────────────────────────────────────────────────────

def _get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Create a Google embedding model instance."""
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )


# ── Document loading ────────────────────────────────────────────────────────

def _infer_metadata(file_path: Path) -> dict:
    """Extract metadata from the file path structure.

    Example:  docs/conceptual/model-schema.md
      -> {"level": "conceptual", "doc_type": "model", "format": "md"}
    """
    parts = file_path.relative_to(DOCS_DIR).parts
    level = parts[0] if len(parts) > 1 else "general"

    filename = file_path.stem  # e.g. "model-schema" or "model.schema"
    if "model" in filename:
        doc_type = "model"
    elif "diagram" in filename:
        doc_type = "diagram"
    else:
        doc_type = "other"

    return {
        "level": level,
        "doc_type": doc_type,
        "format": file_path.suffix.lstrip("."),
        "source": str(file_path.relative_to(_PROJECT_ROOT)),
    }


def _load_markdown_file(file_path: Path) -> List[Document]:
    """Load and chunk a Markdown file by headers, then further split large chunks."""
    text = file_path.read_text(encoding="utf-8")
    meta = _infer_metadata(file_path)

    # Split by markdown headers first for semantic coherence
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "h1"),
            ("##", "h2"),
            ("###", "h3"),
        ],
        strip_headers=False,
    )
    header_docs = header_splitter.split_text(text)

    # Further split large header sections into smaller chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=200,
        separators=["\n\n", "\n", ". ", " "],
    )

    docs: List[Document] = []
    for h_doc in header_docs:
        sub_chunks = text_splitter.split_text(h_doc.page_content)
        for i, chunk in enumerate(sub_chunks):
            merged_meta = {**meta, **h_doc.metadata, "chunk_index": i}
            docs.append(Document(page_content=chunk, metadata=merged_meta))

    return docs


def _load_json_schema_file(file_path: Path) -> List[Document]:
    """Load a JSON Schema file as a document.

    JSON schemas are kept as whole documents (or split if very large)
    because their structure is referential.
    """
    text = file_path.read_text(encoding="utf-8")
    meta = _infer_metadata(file_path)

    # Try to create a more readable description for embedding
    try:
        schema = json.loads(text)
        title = schema.get("title", file_path.stem)
        description = f"JSON Schema: {title}\n\n{text}"
    except json.JSONDecodeError:
        description = text

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=200,
    )

    chunks = text_splitter.split_text(description)
    return [
        Document(page_content=chunk, metadata={**meta, "chunk_index": i})
        for i, chunk in enumerate(chunks)
    ]


def load_all_docs() -> List[Document]:
    """Load all documentation from the ``docs/`` directory."""
    all_docs: List[Document] = []

    for file_path in sorted(DOCS_DIR.rglob("*")):
        if file_path.is_dir():
            continue
        if file_path.suffix == ".md":
            all_docs.extend(_load_markdown_file(file_path))
        elif file_path.suffix == ".json":
            all_docs.extend(_load_json_schema_file(file_path))

    return all_docs


# ── ChromaDB vector store ───────────────────────────────────────────────────

def _compute_docs_hash(docs: List[Document]) -> str:
    """Hash all document content to detect changes."""
    content = "".join(d.page_content for d in docs).encode()
    return hashlib.sha256(content).hexdigest()[:16]


def get_or_create_vectorstore():
    """Return a ChromaDB vectorstore, building the index if needed.

    Uses a content hash to detect when docs have changed and need re-indexing.
    """
    import chromadb
    from langchain_community.vectorstores import Chroma

    embeddings = _get_embeddings()

    # Load docs and compute hash
    docs = load_all_docs()
    current_hash = _compute_docs_hash(docs)

    # Check if we already have an up-to-date index
    hash_file = CHROMA_PERSIST_DIR / ".docs_hash"
    needs_rebuild = True
    if hash_file.exists():
        stored_hash = hash_file.read_text().strip()
        if stored_hash == current_hash:
            needs_rebuild = False

    if needs_rebuild:
        # Rebuild the vector store from scratch
        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)

        # Delete old collection if exists
        client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
        try:
            client.delete_collection("schema_docs")
        except (ValueError, Exception):
            pass  # Collection doesn't exist yet — that's fine

        vectorstore = Chroma.from_documents(
            documents=docs,
            embedding=embeddings,
            collection_name="schema_docs",
            persist_directory=str(CHROMA_PERSIST_DIR),
        )

        hash_file.write_text(current_hash)
    else:
        vectorstore = Chroma(
            collection_name="schema_docs",
            embedding_function=embeddings,
            persist_directory=str(CHROMA_PERSIST_DIR),
        )

    return vectorstore


# ── Public retrieval API ────────────────────────────────────────────────────

_vectorstore = None
_vectorstore_lock = asyncio.Lock()


def _get_vectorstore_sync():
    """Return the cached vectorstore, creating it on first call."""
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = get_or_create_vectorstore()
    return _vectorstore


def _retrieve_sync(
    query: str,
    level: str | None = None,
    doc_type: str | None = None,
    k: int = 6,
) -> List[Document]:
    """Retrieve relevant documents synchronously."""
    vs = _get_vectorstore_sync()

    # Build metadata filter
    where_filter = {}
    if level:
        where_filter["level"] = level
    if doc_type:
        where_filter["doc_type"] = doc_type

    search_kwargs = {"k": k}
    if where_filter:
        if len(where_filter) == 1:
            search_kwargs["filter"] = where_filter
        else:
            search_kwargs["filter"] = {
                "$and": [{key: val} for key, val in where_filter.items()]
            }

    return vs.similarity_search(query, **search_kwargs)


async def aretrieve(
    query: str,
    level: str | None = None,
    doc_type: str | None = None,
    k: int = 6,
) -> List[Document]:
    """Async retrieval — wraps all blocking ChromaDB I/O in a thread.

    Args:
        query: The natural-language query (typically the user's message).
        level: Filter by schema level ("conceptual", "logical", "physical").
        doc_type: Filter by doc type ("model", "diagram").
        k: Number of results to return.

    Returns:
        List of relevant Document objects.
    """
    return await asyncio.to_thread(_retrieve_sync, query, level, doc_type, k)


# Keep a sync version for non-async callers (tests, scripts)
retrieve = _retrieve_sync


# ── Project-docs vector store ─────────────────────────────────────────────────

_project_vectorstore = None


def get_project_vectorstore():
    """Return a ChromaDB vectorstore for the ``project_docs`` collection.

    Unlike ``get_or_create_vectorstore``, no hash/rebuild logic is needed
    because this collection is populated dynamically via the ingest sidecar.
    The instance is cached module-level for the lifetime of the process.
    """
    global _project_vectorstore
    if _project_vectorstore is None:
        from langchain_community.vectorstores import Chroma

        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        embeddings = _get_embeddings()
        _project_vectorstore = Chroma(
            collection_name="project_docs",
            embedding_function=embeddings,
            persist_directory=str(CHROMA_PERSIST_DIR),
        )
    return _project_vectorstore


def _retrieve_project_docs_sync(
    query: str,
    project_id: str,
    k: int = 4,
) -> List[Document]:
    """Retrieve project-specific documents synchronously."""
    vs = get_project_vectorstore()
    try:
        return vs.similarity_search(query, k=k, filter={"project_id": project_id})
    except Exception:
        # ChromaDB raises InternalError when collection is empty or has no matching docs.
        return []


async def aretrieve_project_docs(
    query: str,
    project_id: str,
    k: int = 4,
) -> List[Document]:
    """Async retrieval of project-specific uploaded documents.

    Args:
        query: Natural-language query to match against embedded chunks.
        project_id: Filter results to this project only.
        k: Number of results to return.

    Returns:
        List of relevant Document objects.
    """
    return await asyncio.to_thread(_retrieve_project_docs_sync, query, project_id, k)


def _retrieve_project_docs_with_score_sync(
    query: str,
    project_id: str,
    k: int = 12,
) -> List[tuple]:
    """Retrieve project documents with relevance scores synchronously.

    Return List[Tuple[Document, float]] where score is cosine similarity (higher = more relevant).
    """
    vs = get_project_vectorstore()
    try:
        return vs.similarity_search_with_score(query, k=k, filter={"project_id": project_id})
    except Exception:
        return []


async def aretrieve_project_docs_with_score(
    query: str,
    project_id: str,
    k: int = 12,
) -> List[tuple]:
    """Async retrieval of project docs with relevance scores for re-ranking.

    Args:
        query: Natural-language query to match against embedded chunks.
        project_id: Filter results to this project only.
        k: Number of candidates to fetch (should be larger than final top-k to give re-ranker margin).

    Returns:
        List of (Document, score) tuples where score is cosine similarity in [0, 1].
    """
    return await asyncio.to_thread(_retrieve_project_docs_with_score_sync, query, project_id, k)


def format_project_docs_context(docs: List[Document]) -> str:
    """Format project-document chunks into a context string for the LLM.

    Each document is rendered as a titled section separated by horizontal rules.
    Returns an empty string when no documents were retrieved.
    """
    if not docs:
        return ""

    sections: List[str] = []
    for doc in docs:
        title = doc.metadata.get("title", "Untitled")
        sections.append(f"[{title}]\n{doc.page_content}")

    return "\n\n---\n\n".join(sections)


def format_retrieved_context(docs: List[Document]) -> str:
    """Format retrieved documents into a context string for the LLM."""
    if not docs:
        return ""

    sections: List[str] = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        header = (
            f"[{meta.get('level', '?').upper()} / "
            f"{meta.get('doc_type', '?').upper()} — "
            f"{meta.get('source', 'unknown')}]"
        )
        sections.append(f"--- Reference {i}: {header} ---\n{doc.page_content}")

    return "\n\n".join(sections)
