from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from .config import settings

_pool: ConnectionPool | None = None


def init_pool() -> None:
    """Initialize a connection pool without failing hard if Postgres isn't ready yet."""
    global _pool
    if _pool is not None:
        return

    def _configure(conn) -> None:  # type: ignore[no-untyped-def]
        register_vector(conn)

    # Compose `depends_on` doesn't wait for readiness; open lazily to avoid crash loops.
    _pool = ConnectionPool(
        conninfo=settings.postgres_dsn,
        min_size=1,
        max_size=10,
        open=False,
        configure=_configure,
    )
    try:
        _pool.open(wait=False)
    except Exception:
        # Will retry on first request.
        pass


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Iterator:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")

    if _pool.closed:
        try:
            _pool.open(wait=False)
        except Exception as e:
            raise RuntimeError(f"Database unavailable: {e}") from e

    try:
        with _pool.connection(timeout=5) as conn:
            yield conn
    except Exception as e:
        raise RuntimeError(f"Database unavailable: {e}") from e
