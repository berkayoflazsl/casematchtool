from __future__ import annotations

import threading
import numpy as np
from fastembed import TextEmbedding

from app.embedding_model import BGE_QUERY_PREFIX, EMBEDDING_MODEL_NAME, EMBEDDING_DIMENSION

_model: TextEmbedding | None = None
_lock = threading.Lock()


def get_model() -> TextEmbedding:
    global _model
    with _lock:
        if _model is None:
            _model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
        return _model


def embed_queries(texts: list[str]) -> list[list[float]]:
    model = get_model()
    pref = [BGE_QUERY_PREFIX + t for t in texts]
    vecs = list(model.embed(pref))
    return _as_list_of_lists(vecs)


def embed_passages(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = get_model()
    vecs = list(model.embed(texts))
    return _as_list_of_lists(vecs)


def _as_list_of_lists(vecs: list[np.ndarray]) -> list[list[float]]:
    out: list[list[float]] = []
    for v in vecs:
        a = np.asarray(v, dtype=np.float32).ravel()
        if a.shape[0] != EMBEDDING_DIMENSION:
            raise ValueError(
                f"Model output dim {a.shape[0]} != {EMBEDDING_DIMENSION} — update app/embedding_model.py and SQL."
            )
        out.append(a.astype(float).tolist())
    return out


def to_vector_sql_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"
