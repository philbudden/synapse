from __future__ import annotations

from typing import Any

from pgvector.psycopg import Vector


def _run_search(conn: Any, qv: Vector, limit: int) -> list[dict[str, object]]:
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


def search_memories(conn: Any, query_embedding: list[float], limit: int) -> list[dict[str, object]]:
    """Search memories by cosine similarity.

    Uses pgvector's cosine distance operator (<=>) and returns similarity as (1 - distance).

    Note: ivfflat is approximate. On very small datasets (or with aggressive index settings),
    an index scan can occasionally return 0 rows. We fall back to an exact scan in that case.
    """

    qv = Vector(query_embedding)

    results = _run_search(conn, qv, limit)
    if results:
        return results

    # If there are no rows at all, there's nothing to fall back to.
    has_any = conn.execute(
        "SELECT 1 FROM memories WHERE embedding IS NOT NULL LIMIT 1"
    ).fetchone()
    if not has_any:
        return []

    # Exact scan fallback.
    with conn.transaction():
        conn.execute("SET LOCAL enable_indexscan = off")
        conn.execute("SET LOCAL enable_bitmapscan = off")
        return _run_search(conn, qv, limit)
