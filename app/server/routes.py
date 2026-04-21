from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.categorize.service import CategorizationService
from app.config import Config
from app.extract.auth_manager import TelegramAuthManager
from app.extract.telegram_extractor import TelegramExtractor
from app.report.generator import ReportService
from app.search.service import SearchService
from app.storage.store import FileStore

log = logging.getLogger(__name__)


# ── Pydantic models ───

class SetupPayload(BaseModel):
    telegram_api_id: Optional[int] = None
    telegram_api_hash: Optional[str] = None
    telegram_phone: Optional[str] = None
    channel_username: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    reranker_model: Optional[str] = None
    max_messages: Optional[int] = None
    min_messages_per_user: Optional[int] = None
    topic_id: Optional[int] = None
    users_per_batch: Optional[int] = None
    max_messages_per_user: Optional[int] = None
    max_retries: Optional[int] = None
    parallel_workers: Optional[int] = None
    search_top_k: Optional[int] = None
    search_confidence_threshold: Optional[float] = None
    embedding_model: Optional[str] = None


class SearchPayload(BaseModel):
    query: str


class PromptPayload(BaseModel):
    categories: list
    assignment_rules: list
    system_prompt: str = ""


class TwoFAPayload(BaseModel):
    password: str


# ── Pipeline status ───

class PipelineStatus:
    def __init__(self) -> None:
        self.state: str = "idle"       # idle | running | done | error
        self.phase: str = ""           # extracting | categorizing | indexing | exporting
        self.total: int = 0
        self.done: int = 0
        self.failed: int = 0
        self.last_error: Optional[str] = None

    def reset(self, total: int) -> None:
        self.state = "running"
        self.phase = "categorizing"
        self.total = total
        self.done = 0
        self.failed = 0
        self.last_error = None

    def on_progress(self, outcome: str) -> None:
        self.done += 1
        if outcome == "failed":
            self.failed += 1

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "phase": self.phase,
            "total": self.total,
            "done": self.done,
            "failed": self.failed,
            "last_error": self.last_error,
        }


def make_router(
    config: Config,
    store: FileStore,
    cat_service: CategorizationService,
    search_service: SearchService,
    report_service: ReportService,
    pipeline_status: PipelineStatus,
    auth_manager: TelegramAuthManager,
    oai_client=None,
) -> APIRouter:

    r = APIRouter()

    @r.get("/", response_class=HTMLResponse)
    async def index():
        errors = config.validate()
        if errors:
            return HTMLResponse(content="", status_code=302, headers={"Location": "/setup"})
        return HTMLResponse(content=report_service.render_report_html())

    @r.get("/setup", response_class=HTMLResponse)
    async def setup_page():
        settings = store.load_settings()
        masked = dict(settings)
        if settings.get("telegram_api_hash"):
            masked["_api_hash_saved"] = True
            masked["_api_hash_last4"] = settings["telegram_api_hash"][-4:]
            masked.pop("telegram_api_hash", None)
        if settings.get("openai_api_key"):
            masked["_openai_key_saved"] = True
            masked["_openai_key_last4"] = settings["openai_api_key"][-4:]
            masked.pop("openai_api_key", None)
        return HTMLResponse(content=report_service.render_setup_html(masked))

    # ── Setup API ──────────────────────────────────────────────────────────────

    @r.post("/api/setup")
    async def api_setup_save(payload: SetupPayload):
        settings = store.load_settings()
        data = payload.model_dump(exclude_none=True)
        settings.update(data)
        store.save_settings(settings)
        config.reload()
        # Keep the shared AsyncOpenAI client in sync with the new key so that
        # services started after a key change (e.g. .env deleted, key entered
        # via wizard) don't keep hitting 401s with the old empty key.
        if oai_client is not None and config.openai_api_key:
            oai_client.api_key = config.openai_api_key
            log.info("OpenAI client key updated.")
        log.info("Settings saved.")
        return {"ok": True}

    @r.get("/api/setup")
    async def api_setup_get():
        settings = store.load_settings()
        masked = dict(settings)
        if masked.get("telegram_api_hash"):
            masked["telegram_api_hash"] = {"has_value": True, "last4": masked["telegram_api_hash"][-4:]}
        if masked.get("openai_api_key"):
            masked["openai_api_key"] = {"has_value": True, "last4": masked["openai_api_key"][-4:]}
        missing = [f for f in ["telegram_api_id", "telegram_api_hash", "telegram_phone",
                                "openai_api_key", "channel_username"] if not settings.get(f)]
        return {"settings": masked, "missing": missing}

    # ── Telegram auth ──────────────────────────────────────────────────────────

    @r.get("/api/auth/telegram/status")
    async def api_auth_status():
        """Return current Telegram auth state."""
        if auth_manager.state == "authorized":
            return auth_manager.to_dict()

        # do a quick session check so a pre-existing session shows as authorized
        if auth_manager.state == "idle":
            if await auth_manager.check_authorized(config):
                auth_manager.state = "authorized"
        return auth_manager.to_dict()

    @r.post("/api/auth/telegram/start")
    async def api_auth_start():
        """Start QR login flow. Returns immediately; poll /status for QR SVG."""
        if auth_manager.state == "authorized":
            return {"ok": True, "already_authorized": True}
        auth_manager.start_auth(config)
        return {"ok": True}

    @r.post("/api/auth/telegram/2fa")
    async def api_auth_2fa(payload: TwoFAPayload):
        if auth_manager.state != "needs_2fa":
            raise HTTPException(status_code=400, detail="2FA not currently required.")
        await auth_manager.submit_password(payload.password)
        return {"ok": True}


    # ── Run pipeline ───────────────────────────────────────────────────────────

    @r.post("/api/run")
    async def api_run(confirm_prompt_reset: bool = Query(False)):
        if pipeline_status.state == "running":
            raise HTTPException(status_code=409, detail="Pipeline already running.")

        errors = config.validate()
        if errors:
            raise HTTPException(status_code=400, detail=f"Config incomplete: {errors}")

        # Check Telegram auth before starting
        if auth_manager.state != "authorized":
            is_auth = await auth_manager.check_authorized(config)
            if not is_auth:
                raise HTTPException(
                    status_code=403,
                    detail={"code": "TELEGRAM_NOT_AUTHORIZED"},
                )
            auth_manager.state = "authorized"

        # Check for prompt hash change
        if not confirm_prompt_reset:
            from app.categorize.prompt import PromptBuilder

            prompt = PromptBuilder(config)
            stored_hash = store.get_meta("prompt_hash")
            if stored_hash and stored_hash != prompt.hash:
                affected = len(store.users_needing_categorization(prompt.hash))
                raise HTTPException(
                    status_code=409,
                    detail={"code": "PROMPT_CHANGE_REQUIRES_CONFIRM", "affected_users": affected},
                )

        async def _run_pipeline(force: bool) -> None:
            try:
                pipeline_status.state = "running"
                pipeline_status.phase = "extracting"
                pipeline_status.total = 0
                pipeline_status.done = 0
                pipeline_status.failed = 0
                pipeline_status.last_error = None

                extractor = TelegramExtractor(config, store)
                await extractor.extract_messages()

                pending = store.users_needing_categorization(cat_service._prompt_hash_or_compute())
                pipeline_status.reset(len(pending))

                await cat_service.run(
                    progress_callback=pipeline_status.on_progress,
                    force=force,
                )

                pipeline_status.phase = "indexing"
                await search_service.ensure_index()

                pipeline_status.phase = "exporting"
                report_service.write_static_exports()

                pipeline_status.state = "done"
                pipeline_status.phase = ""
                log.info("Pipeline complete.")
            except Exception as e:
                pipeline_status.state = "error"
                pipeline_status.phase = ""
                pipeline_status.last_error = str(e)
                log.exception("Pipeline error: %s", e)

        asyncio.create_task(_run_pipeline(force=confirm_prompt_reset))
        return {"ok": True, "message": "Pipeline started."}

    @r.get("/api/status")
    async def api_status():
        return pipeline_status.to_dict()


    # ── Search ─────────────────────────────────────────────────────────────────

    @r.post("/api/search")
    async def api_search(payload: SearchPayload):
        result = await search_service.search(payload.query)
        return {
            "reason": result.reason,
            "matches": [
                {"user_id": m.user_id, "confidence": m.confidence, "rationale": m.rationale}
                for m in result.matches
            ],
        }

    @r.post("/api/reset-search")
    async def api_reset_search():
        return {"ok": True}

    # ── Prompt editor ──────────────────────────────────────────────────────────

    @r.get("/api/prompt")
    async def api_prompt_get():
        try:
            with open(config.prompt_file, "r", encoding="utf-8") as f:
                sys_prompt = f.read()
        except FileNotFoundError:
            sys_prompt = ""
        try:
            with open(config.categories_file, "r", encoding="utf-8") as f:
                cats_data = json.load(f)
        except Exception:
            cats_data = {"categories": [], "assignment_rules": []}
        return {
            "system_prompt": sys_prompt,
            "categories": cats_data.get("categories", []),
            "assignment_rules": cats_data.get("assignment_rules", []),
        }

    @r.put("/api/prompt")
    async def api_prompt_save(payload: PromptPayload, confirm: bool = Query(False)):
        from app.categorize.schema import SCHEMA_VERSION
        import hashlib

        cat_tuples = [(c["name"], c["description"]) for c in payload.categories]
        hash_payload = {
            "system_prompt": payload.system_prompt.strip(),
            "few_shot": "",
            "categories": cat_tuples,
            "category_rules": list(payload.assignment_rules),
            "response_schema_version": SCHEMA_VERSION,
        }
        try:
            with open(config.few_shot_file, "r", encoding="utf-8") as f:
                hash_payload["few_shot"] = f.read().strip()
        except FileNotFoundError:
            pass

        canonical = json.dumps(hash_payload, sort_keys=True, ensure_ascii=False)
        new_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        stored_hash = store.get_meta("prompt_hash")

        if not confirm and stored_hash and stored_hash != new_hash:
            affected = len(store.users_needing_categorization(new_hash))
            raise HTTPException(
                status_code=409,
                detail={"code": "PROMPT_CHANGE_REQUIRES_CONFIRM", "users_to_reprocess": affected},
            )

        if payload.system_prompt:
            with open(config.prompt_file, "w", encoding="utf-8") as f:
                f.write(payload.system_prompt)

        with open(config.categories_file, "w", encoding="utf-8") as f:
            json.dump(
                {"categories": payload.categories, "assignment_rules": payload.assignment_rules},
                f, indent=2, ensure_ascii=False,
            )

        store.set_meta("prompt_hash", new_hash)
        config.reload()

        if confirm and stored_hash != new_hash:
            store.delete_all_categorizations()
            store.delete_embeddings()
            asyncio.create_task(cat_service.run(force=True))

        return {"ok": True, "changed": stored_hash != new_hash}

    return r
