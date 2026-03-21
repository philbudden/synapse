from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pgvector.psycopg import Vector
from psycopg.types.json import Json

from .classify import classify_embedding
from .config import settings
from .db import close_pool, get_conn, get_structured_memory, init_pool
from .embeddings import EmbeddingError, embed_text
from .models import CaptureRequest, CaptureResponse, SearchResponse
from .search import search_memories

app = FastAPI(title="Synapse API", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_pool()


@app.on_event("shutdown")
def _shutdown() -> None:
    close_pool()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/capture", response_model=CaptureResponse)
def capture(req: CaptureRequest) -> CaptureResponse:
    try:
        embedding = embed_text(req.content)
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if len(embedding) != 768:
        raise HTTPException(
            status_code=500,
            detail=f"Embedding dimension {len(embedding)} does not match schema VECTOR(768).",
        )

    # Classification should not block storing; if it fails we store an explicit fallback.
    try:
        classification = classify_embedding(embedding).as_dict()
    except Exception as e:
        classification = {"category": "unclassified", "confidence": 0.0, "error": str(e)}

    try:
        with get_conn() as conn:
            with conn.transaction():
                capture_id = conn.execute(
                    """
                    INSERT INTO captures (source, content, classification, classification_model, classified_at)
                    VALUES (%s, %s, %s, %s, now())
                    RETURNING id
                    """,
                    (req.source, req.content, Json(classification), settings.embed_model),
                ).fetchone()[0]

                memory_id = conn.execute(
                    """
                    INSERT INTO memories (capture_id, content, embedding)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (capture_id, req.content, Vector(embedding)),
                ).fetchone()[0]
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return CaptureResponse(status="stored", id=str(memory_id), classification=classification)


@app.get("/search", response_model=SearchResponse)
def search(query: str, limit: int = 5) -> SearchResponse:
    query = (query or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is required")
    if limit < 1 or limit > 50:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50")

    try:
        query_embedding = embed_text(query)
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if len(query_embedding) != 768:
        raise HTTPException(
            status_code=500,
            detail=f"Embedding dimension {len(query_embedding)} does not match schema VECTOR(768).",
        )

    try:
        with get_conn() as conn:
            results = search_memories(conn, query_embedding, limit)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return SearchResponse(results=results)


@app.get("/structured_memory/{key}")
def fetch_structured_memory(key: str) -> dict[str, object | None]:
    try:
        with get_conn() as conn:
            value = get_structured_memory(conn, key)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {"key": key, "value": value}
