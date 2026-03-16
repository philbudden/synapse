from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import settings


@dataclass
class EmbeddingError(Exception):
    message: str


def embed_text(text: str) -> list[float]:
    url = f"{settings.ollama_base_url}/api/embeddings"
    payload = {"model": settings.embed_model, "prompt": text}

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.RequestError as e:
        raise EmbeddingError(f"Failed to reach Ollama at {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        body = e.response.text
        raise EmbeddingError(f"Ollama error {e.response.status_code}: {body}") from e

    emb = data.get("embedding")
    if not isinstance(emb, list) or not emb:
        raise EmbeddingError(f"Unexpected Ollama response: missing 'embedding': {data}")

    try:
        return [float(x) for x in emb]
    except (TypeError, ValueError) as e:
        raise EmbeddingError(f"Invalid embedding values from Ollama: {e}") from e
