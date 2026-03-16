from __future__ import annotations

from typing import Any

from pgvector.psycopg import Vector


def search_memories(conn: Any, query_embedding: list[float], limit: int) -> list[dict[str, object]]:
    # Cosine distance operator: <=> (0 is identical). Convert to similarity in [~ -inf, 1].
    qv = Vector(query_embedding)
    sql = """
        SELECT content,
               1 - (embedding <=> %s) AS score
        FROM memories
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s
        LIMIT %s
    """
    rows = conn.execute(sql, (qv, qv, limit)).fetchall()
    return [{"content": r[0], "score": float(r[1])} for r in rows]
