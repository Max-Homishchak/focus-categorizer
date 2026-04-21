from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from openai import AsyncOpenAI

from app.config import Config
from app.search.embedder import Embedder
from app.search.reranker import LLMReranker, RankedResult
from app.search.store import VectorIndex
from app.storage.store import FileStore

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class SearchResponse:
    matches: List[RankedResult]
    reason: str  # ok | no_match | no_candidates | empty_query | error


class SearchService:
    def __init__(self, config: Config, store: FileStore, client: AsyncOpenAI) -> None:
        self.config = config
        self.store = store
        self.client = client
        self._embedder = Embedder(config, client)
        self._reranker = LLMReranker(config, client)
        self._index: Optional[VectorIndex] = None

    async def ensure_index(self) -> None:
        """Build or refresh the vector index if needed."""
        idx = self.store.load_embeddings()
        if idx is not None:
            self._index = VectorIndex(idx)
            log.info("Vector index loaded: %d vectors.", len(idx.ids))
            return

        cats = self.store.all_categorizations()
        current_hash = self.store.get_meta("prompt_hash") or ""
        cats = [c for c in cats if c.prompt_hash == current_hash]

        if not cats:
            log.info("No categorizations available — skipping index build.")
            self._index = None
            return

        log.info("Building embedding index for %d users...", len(cats))
        t0 = time.monotonic()

        texts = [self._make_document(c) for c in cats]
        ids = np.array([c.user_id for c in cats], dtype=np.int64)
        vectors = await self._embedder.embed_batch(texts)
        self.store.save_embeddings(
            vectors=vectors, ids=ids,
            model=self.config.embedding_model, prompt_hash=current_hash,
        )
        self._index = VectorIndex(self.store.load_embeddings())
        log.info("Embedding index built and saved in %.1fs.", time.monotonic() - t0)

    @staticmethod
    def _make_document(cat) -> str:
        md = cat.user_metadata or {}
        langs = ", ".join(md.get("languages") or [])
        return (
            f"{cat.category}. {cat.summary}\n"
            f"Tags: {', '.join(cat.tags)}\n"
            f"Profession: {md.get('profession', '')}, "
            f"City: {md.get('city', '')}, "
            f"Country: {md.get('country', '')}, "
            f"Languages: {langs}\n"
            f"Reasoning: {cat.reasoning}"
        )

    async def search(self, query: str) -> SearchResponse:
        if not query.strip():
            return SearchResponse(matches=[], reason="empty_query")

        t_total = time.monotonic()
        log.info("Search query: %r", query)

        try:
            await self.ensure_index()
        except Exception as e:
            log.error("Index build failed: %s", e)
            return SearchResponse(matches=[], reason="error")

        if self._index is None:
            log.warning("Search aborted — index is empty (no categorizations yet).")
            return SearchResponse(matches=[], reason="no_candidates")

        # Stage 1: embed the query
        t0 = time.monotonic()
        try:
            query_vec = await self._embedder.embed_one(query)
        except Exception as e:
            log.error("Query embedding failed: %s", e)
            return SearchResponse(matches=[], reason="error")
        log.info("  [1/2] Query embedded in %.2fs.", time.monotonic() - t0)

        # Stage 2: cosine top-k
        t0 = time.monotonic()
        candidates = self._index.top_k(query_vec, k=self.config.search_top_k)
        log.info(
            "  [2/2] Top-%d retrieved in %.3fs (cosine scores: %.3f – %.3f).",
            len(candidates),
            time.monotonic() - t0,
            candidates[-1][1] if candidates else 0.0,
            candidates[0][1] if candidates else 0.0,
        )
        if not candidates:
            return SearchResponse(matches=[], reason="no_candidates")

        # Stage 3: LLM rerank
        cats_map = {c.user_id: c for c in self.store.all_categorizations()}
        t0 = time.monotonic()
        try:
            scored = await self._reranker.rerank(query, candidates, cats_map)
        except Exception as e:
            log.error("Reranker failed: %s", e)
            return SearchResponse(matches=[], reason="error")
        log.info(
            "  Reranker scored %d candidates in %.1fs.",
            len(scored),
            time.monotonic() - t0,
        )

        # Stage 4: Filter out scored users with not enough confidence score
        threshold = self.config.search_confidence_threshold
        filtered = [s for s in scored if s.confidence >= threshold]
        filtered.sort(key=lambda s: s.confidence, reverse=True)

        log.info(
            "Search done in %.1fs total — %d/%d passed threshold %.2f. Reason: %s.",
            time.monotonic() - t_total,
            len(filtered),
            len(scored),
            threshold,
            "ok" if filtered else "no_match",
        )
        if filtered:
            for r in filtered[:3]:
                log.info("  user_id=%-12d  confidence=%.2f  %s", r.user_id, r.confidence, r.rationale[:80])

        if not filtered:
            return SearchResponse(matches=[], reason="no_match")
        return SearchResponse(matches=filtered, reason="ok")
