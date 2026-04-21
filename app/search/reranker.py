from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from openai import AsyncOpenAI

from app.config import Config
from app.storage.store import CategorizationRecord

log = logging.getLogger(__name__)

_RERANK_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "rerank_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "integer"},
                            "confidence": {"type": "number"},
                            "rationale": {"type": "string"},
                        },
                        "required": ["user_id", "confidence", "rationale"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["results"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class RankedResult:
    user_id: int
    confidence: float
    rationale: str


class LLMReranker:
    def __init__(self, config: Config, client: AsyncOpenAI) -> None:
        self.config = config
        self.client = client

    async def rerank(
        self,
        query: str,
        candidates: List[Tuple[int, float]],
        categorizations: Dict[int, CategorizationRecord],
    ) -> List[RankedResult]:
        if not candidates:
            return []

        profiles = []
        for uid, cosine in candidates:
            rec = categorizations.get(uid)
            if rec is None:
                log.debug("Reranker: no categorization found for user_id=%d — skipping.", uid)
                continue
            md = rec.user_metadata or {}
            profiles.append(
                f"user_id: {uid}\n"
                f"category: {rec.category}\n"
                f"summary: {rec.summary}\n"
                f"tags: {', '.join(rec.tags)}\n"
                f"profession: {md.get('profession', 'n/a')}, "
                f"city: {md.get('city', 'n/a')}, "
                f"country: {md.get('country', 'n/a')}, "
                f"languages: {', '.join(md.get('languages') or [])}\n"
                f"reasoning: {rec.reasoning}"
            )

        if not profiles:
            return []

        system = (
            "You are a relevance scorer for a community search system. "
            "Given a search query and user profiles, assign each profile a confidence score from 0.0 to 1.0.\n\n"
            "Score rough meaning:\n"
            "  1.0 — perfect match: profile explicitly states the exact role, skill, or attribute from the query\n"
            "  0.8 — strong match: profile clearly fits the query intent even if wording differs\n"
            "  0.6 — partial match: profile is related but missing a key aspect of the query (e.g. has the role but no commercial experience mentioned)\n"
            "  0.4 — weak match: profile is in the same broad domain but does not specifically match\n"
            "  0.2 — tangential: profile touches on the topic only indirectly or aspirationally\n"
            "  0.0 — no match: profile has no meaningful connection to the query\n\n"
            "Rules:\n"
            "- Score based on what the profile actually states, not what the person might be capable of.\n"
            "- 'Interested in X' or 'learning X' is NOT the same as 'works as X' — score accordingly.\n"
            "- Include every profile — do NOT omit any.\n"
            "- Be strict: reserve 0.8+ for profiles that clearly and concretely satisfy the query."
        )
        user_msg = (
            f"Query: {query}\n\n"
            "Profiles:\n\n"
            + "\n\n---\n\n".join(profiles)
            + "\n\nReturn all profiles with confidence scores and brief rationales."
        )

        # Rough token estimate: ~4 chars per token
        estimated_tokens = (len(system) + len(user_msg)) // 4
        log.info(
            "Reranker: sending %d profiles to %s (~%d tokens estimated).",
            len(profiles), self.config.reranker_model, estimated_tokens,
        )

        log.info(
            "Reranker prompt:\nSystem:\n%s\n\nUser:\n%s",
            system, user_msg
        )

        t0 = time.monotonic()
        try:
            resp = await self.client.chat.completions.create(
                model=self.config.reranker_model,
                response_format=_RERANK_SCHEMA,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
            )
            elapsed = time.monotonic() - t0
            usage = resp.usage
            log.info(
                "Reranker: response in %.1fs — prompt=%d tokens, completion=%d tokens.",
                elapsed,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            )
            text = (resp.choices[0].message.content or "{}").strip()
            data = json.loads(text)
            results = [
                RankedResult(
                    user_id=item["user_id"],
                    confidence=float(item["confidence"]),
                    rationale=item.get("rationale", ""),
                )
                for item in data.get("results", [])
            ]
            log.debug(
                "Reranker: confidence distribution — min=%.2f, max=%.2f, mean=%.2f.",
                min(r.confidence for r in results) if results else 0,
                max(r.confidence for r in results) if results else 0,
                sum(r.confidence for r in results) / len(results) if results else 0,
            )
            return results
        except Exception as e:
            log.error("Reranker failed after %.1fs: %s", time.monotonic() - t0, e)
            return []
