from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from openai import AsyncOpenAI

from app.categorize.prompt import PromptBuilder
from app.categorize.worker import CategorizationWorker
from app.config import Config
from app.storage.store import FileStore

log = logging.getLogger(__name__)


class PromptChangedError(Exception):
    def __init__(self, current_hash: str, stored_hash: str, affected_users: int) -> None:
        self.current_hash = current_hash
        self.stored_hash = stored_hash
        self.affected_users = affected_users
        super().__init__(
            f"Prompt hash changed ({stored_hash[:16]}... → {current_hash[:16]}...); "
            f"{affected_users} users would be reprocessed."
        )


class CategorizationService:
    def __init__(self, config: Config, store: FileStore, client: AsyncOpenAI) -> None:
        self.config = config
        self.store = store
        self.client = client

    async def run(
        self,
        progress_callback: Optional[Callable[[str], None]] = None,
        force: bool = False,
    ) -> None:
        prompt = PromptBuilder(self.config)
        await self._ensure_prompt_hash(prompt, force=force)

        pending_ids = self.store.users_needing_categorization(prompt.hash)
        if not pending_ids:
            log.info("Nothing to categorize.")
            return

        batch_size = self.config.users_per_batch
        batches = [pending_ids[i: i + batch_size] for i in range(0, len(pending_ids), batch_size)]
        total_batches = len(batches)

        log.info(
            "Categorizing %d users in %d batch(es) of %d, %d parallel workers...",
            len(pending_ids),
            total_batches,
            batch_size,
            self.config.parallel_workers,
        )

        sem = asyncio.Semaphore(self.config.parallel_workers)
        tasks = [
            asyncio.create_task(
                self._run_batch(batch, batch_num + 1, total_batches, prompt, sem, progress_callback)
            )
            for batch_num, batch in enumerate(batches)
        ]
        await asyncio.gather(*tasks, return_exceptions=False)

        # Compact shards → single categorizations.json for offline use
        self.store.compact_categorizations()
        log.info("Categorization complete.")

    async def _run_batch(
        self,
        user_ids: list,
        batch_num: int,
        total_batches: int,
        prompt: PromptBuilder,
        sem: asyncio.Semaphore,
        progress_callback: Optional[Callable[[str], None]],
    ) -> None:
        async with sem:
            worker = CategorizationWorker(self.config, self.store, self.client, prompt)
            await worker.process_batch(
                user_ids,
                batch_num=batch_num,
                total_batches=total_batches,
                on_done=progress_callback,
            )

    async def _ensure_prompt_hash(self, prompt: PromptBuilder, force: bool) -> None:
        current_hash = prompt.hash
        stored_hash = self.store.get_meta("prompt_hash")

        if stored_hash is None:
            # First run — write hash and proceed
            self.store.set_meta("prompt_hash", current_hash)
            log.info("First run — prompt hash stored: %s", current_hash[:16])
            return

        if stored_hash == current_hash:
            log.debug("Prompt hash unchanged (%s).", current_hash[:16])
            return

        if force:
            # User confirmed reset — wipe and proceed
            log.info("Prompt hash changed (confirmed) — wiping categorizations and embeddings.")
            self.store.delete_all_categorizations()
            self.store.delete_embeddings()
            self.store.set_meta("prompt_hash", current_hash)
            return

        # Hash differs and not confirmed — raise for the server to surface the modal
        affected = len(self.store.users_needing_categorization(current_hash))
        raise PromptChangedError(
            current_hash=current_hash,
            stored_hash=stored_hash,
            affected_users=affected,
        )
