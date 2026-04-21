from __future__ import annotations

from typing import List, Tuple

import numpy as np

from app.storage.store import EmbeddingIndex


class VectorIndex:
    def __init__(self, index: EmbeddingIndex) -> None:
        self._ids = index.ids  # shape (N,)
        # Pre-normalise for fast cosine via dot product
        norms = np.linalg.norm(index.vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        self._vectors = index.vectors / norms  # shape (N, dim), float32

    def top_k(self, query_vec: np.ndarray, k: int) -> List[Tuple[int, float]]:
        """Return top-k (user_id, cosine_score) pairs, sorted descending."""
        if self._vectors.shape[0] == 0:
            return []

        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []
        q = query_vec / query_norm

        scores = self._vectors @ q  # shape (N,)
        k = min(k, len(scores))

        if k <= 0:
            return []

        top_indices = np.argpartition(scores, -k)[-k:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        return [(int(self._ids[i]), float(scores[i])) for i in top_indices]
