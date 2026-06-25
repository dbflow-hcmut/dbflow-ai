"""Entrypoint for the document ingestion sidecar."""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("AI_INGEST_PORT", "8001"))
    uvicorn.run("api.ingest:app", host="0.0.0.0", port=port, reload=False)
