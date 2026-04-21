from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from openai import AsyncOpenAI

from app.categorize.service import CategorizationService
from app.config import Config
from app.extract.auth_manager import TelegramAuthManager
from app.report.generator import ReportService
from app.search.service import SearchService
from app.server.routes import PipelineStatus, make_router
from app.storage.store import FileStore

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    config = Config()
    store = FileStore(data_dir=config.data_dir)
    store.init()

    oai_client = AsyncOpenAI(api_key=config.openai_api_key)
    cat_service = CategorizationService(config=config, store=store, client=oai_client)
    search_service = SearchService(config=config, store=store, client=oai_client)
    report_service = ReportService(config=config, store=store)
    pipeline_status = PipelineStatus()
    auth_manager = TelegramAuthManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("=" * 60)
        log.info("  Telegram Categorizer V2")
        log.info("  http://%s:%d", config.server_host, config.server_port)
        log.info("=" * 60)
        # Warm-load the embedding index on startup if available
        try:
            await search_service.ensure_index()
        except Exception as e:
            log.warning("Could not pre-load search index: %s", e)
        yield
        log.info("Server shutting down.")

    app = FastAPI(title="Telegram Categorizer V2", lifespan=lifespan)

    def _prompt_hash_or_compute() -> str:
        from app.categorize.prompt import PromptBuilder
        return PromptBuilder(config).hash

    cat_service._prompt_hash_or_compute = _prompt_hash_or_compute

    app.include_router(
        make_router(
            config=config,
            store=store,
            cat_service=cat_service,
            search_service=search_service,
            report_service=report_service,
            pipeline_status=pipeline_status,
            auth_manager=auth_manager,
        )
    )
    return app
