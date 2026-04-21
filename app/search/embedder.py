from __future__ import annotations

import logging
from typing import List

import numpy as np
from openai import AsyncOpenAI

from app.config import Config

log = logging.getLogger(__name__)

_BATCH_SIZE = 100  # stay well under OpenAI's 2048-input limit


class Embedder:
    def __init__(self, config: Config, client: AsyncOpenAI) -> None:
        self.config = config
        self.client = client

    async def embed_one(self, text: str) -> np.ndarray:
        vecs = await self.embed_batch([text])
        return vecs[0]

    async def embed_batch(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 1536), dtype=np.float32)

        all_vecs: List[np.ndarray] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            chunk = texts[i : i + _BATCH_SIZE]
            resp = await self.client.embeddings.create(
                model=self.config.embedding_model,
                input=chunk,
            )
            chunk_vecs = [np.array(item.embedding, dtype=np.float32) for item in resp.data]
            all_vecs.extend(chunk_vecs)
            log.debug("Embedded %d texts (chunk %d/%d).", len(chunk), i // _BATCH_SIZE + 1, (len(texts) + _BATCH_SIZE - 1) // _BATCH_SIZE)

        return np.stack(all_vecs, axis=0)
