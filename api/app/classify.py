from __future__ import annotations

import math
from dataclasses import dataclass

from .embeddings import embed_text


@dataclass(frozen=True)
class Classification:
    category: str
    confidence: float

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "confidence": float(self.confidence),
            "method": "embedding-prototypes",
        }


# Minimal, fixed taxonomy. Keep this small and stable.
_PROTOTYPES: dict[str, str] = {
    "task": "A todo or action item that should be done soon.",
    "idea": "A new idea, concept, or invention; brainstorming.",
    "work": "Work-related note about projects, meetings, coworkers, or business.",
    "personal": "Personal life note about feelings, health, relationships, or daily life.",
    "question": "A question that needs an answer or research.",
    "reference": "A fact, quote, link, or information to refer back to later.",
    "other": "Other uncategorized note.",
}

_cached_proto_vectors: dict[str, list[float]] | None = None
_cached_proto_norms: dict[str, float] | None = None


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _cosine(a: list[float], b: list[float], norm_a: float, norm_b: float) -> float:
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)


def _ensure_prototypes() -> tuple[dict[str, list[float]], dict[str, float]]:
    global _cached_proto_vectors, _cached_proto_norms
    if _cached_proto_vectors is not None and _cached_proto_norms is not None:
        return _cached_proto_vectors, _cached_proto_norms

    vectors: dict[str, list[float]] = {}
    norms: dict[str, float] = {}
    for cat, prompt in _PROTOTYPES.items():
        v = embed_text(prompt)
        vectors[cat] = v
        norms[cat] = _norm(v)

    _cached_proto_vectors = vectors
    _cached_proto_norms = norms
    return vectors, norms


def classify_embedding(embedding: list[float]) -> Classification:
    """Classify an embedding by similarity to a small set of prototype category embeddings."""

    vectors, norms = _ensure_prototypes()
    n = _norm(embedding)

    sims: list[tuple[str, float]] = []
    for cat, pv in vectors.items():
        sims.append((cat, _cosine(embedding, pv, n, norms[cat])))

    sims.sort(key=lambda x: x[1], reverse=True)
    best_cat, best_sim = sims[0]

    # Softmax over cosine sims for a rough confidence score.
    # Temperature chosen to spread values a bit without requiring tuning.
    t = 10.0
    exps = [math.exp(s * t) for _, s in sims]
    conf = exps[0] / sum(exps) if exps else 0.0

    return Classification(category=best_cat, confidence=conf)
