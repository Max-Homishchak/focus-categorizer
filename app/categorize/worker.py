from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, List, Optional

from openai import AsyncOpenAI

from app.categorize.prompt import PromptBuilder
from app.categorize.schema import RESPONSE_SCHEMA
from app.config import Config
from app.storage.store import CategorizationRecord, FileStore

log = logging.getLogger(__name__)


class CategorizationWorker:
    def __init__(
        self,
        config: Config,
        store: FileStore,
        client: AsyncOpenAI,
        prompt: PromptBuilder,
    ) -> None:
        self.config = config
        self.store = store
        self.client = client
        self.prompt = prompt

    async def process_batch(
        self,
        user_ids: List[int],
        batch_num: int,
        total_batches: int,
        on_done: Optional[Callable[[str], None]] = None,
    ) -> None:
        # Load user records and messages
        all_users_map = {u.user_id: u for u in self.store.all_users()}
        batch_data: List[tuple] = []  # (user_id, display_name, messages, max_mid)
        for uid in user_ids:
            user = all_users_map.get(uid)
            if user is None:
                log.error("User %d not found in store — skipping.", uid)
                if on_done:
                    on_done("failed")
                continue
            msgs = self.store.messages_for(uid)
            max_mid = max((m.message_id for m in msgs), default=0)
            batch_data.append((uid, user.display_name, [m.text for m in msgs], max_mid, len(msgs)))

        if not batch_data:
            return

        log.info(
            "  Batch %d/%d: processing %d users...",
            batch_num, total_batches, len(batch_data),
        )

        # Build prompt tuples for PromptBuilder (user_id, display_name, messages)
        prompt_tuples = [(uid, name, msgs) for uid, name, msgs, _, _ in batch_data]
        raw_entries = await self._call_llm(prompt_tuples, batch_num, total_batches)

        # Index LLM results by user_id
        results_by_id = {entry["user_id"]: entry for entry in raw_entries}

        for uid, display_name, message_texts, max_mid, msg_count in batch_data:
            entry = results_by_id.get(uid)
            if entry:
                rec = CategorizationRecord(
                    user_id=uid,
                    category=entry.get("category", "Uncategorized"),
                    tags=entry.get("tags", []),
                    summary=entry.get("summary", ""),
                    worth_checking=bool(entry.get("worth_checking", False)),
                    reasoning=entry.get("reasoning", ""),
                    user_metadata=entry.get("user_metadata", {}),
                    prompt_hash=self.prompt.hash,
                    last_message_id=max_mid,
                    message_count_seen=msg_count,
                )
                outcome = "done"
            else:
                # LLM returned no entry for this user — write sentinel
                rec = CategorizationRecord(
                    user_id=uid,
                    category="Uncategorized",
                    tags=[],
                    summary="",
                    worth_checking=False,
                    reasoning="Categorization failed: no result returned by LLM.",
                    user_metadata={},
                    prompt_hash=self.prompt.hash,
                    last_message_id=max_mid,
                    message_count_seen=msg_count,
                )
                outcome = "failed"
                log.warning("No LLM result for user %d in batch %d/%d.", uid, batch_num, total_batches)

            self.store.save_categorization(rec)
            if on_done:
                on_done(outcome)

        log.info("  Batch %d/%d: done.", batch_num, total_batches)

    async def _call_llm(
        self,
        prompt_tuples: List[tuple],
        batch_num: int,
        total_batches: int,
    ) -> List[dict]:
        system = self.prompt.system_prompt()
        few_shot = self.prompt.few_shot()
        user_msg = self.prompt.user_prompt(prompt_tuples)

        chat_messages = [{"role": "system", "content": system}]
        if few_shot:
            chat_messages.append({"role": "user", "content": few_shot})
        chat_messages.append({"role": "user", "content": user_msg})

        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.config.model,
                    response_format=RESPONSE_SCHEMA,
                    temperature=0.2,
                    messages=chat_messages,
                )
                text = (response.choices[0].message.content or "{}").strip()
                data = json.loads(text)
                # Support both {"users": [...]} and bare list
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for v in data.values():
                        if isinstance(v, list):
                            return v
                return []
            except json.JSONDecodeError as e:
                last_error = e
                log.warning(
                    "Batch %d/%d attempt %d/%d: JSON parse error — %s",
                    batch_num, total_batches, attempt, self.config.max_retries, e,
                )
            except Exception as e:
                last_error = e
                log.warning(
                    "Batch %d/%d attempt %d/%d: API error — %s",
                    batch_num, total_batches, attempt, self.config.max_retries, e,
                )

            if attempt < self.config.max_retries:
                wait = 2 ** attempt
                log.info("Retrying batch %d/%d in %ds...", batch_num, total_batches, wait)
                await asyncio.sleep(wait)

        log.error(
            "Batch %d/%d: all %d attempts failed. Last error: %s",
            batch_num, total_batches, self.config.max_retries, last_error,
        )
        return []
