from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

_DATA_DIR = os.getenv("DATA_DIR", "./data")
_SETTINGS_PATH = os.path.join(_DATA_DIR, "settings.json")


def _load_settings() -> Dict[str, Any]:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get(settings: Dict[str, Any], key: str, env_key: str, default: Any) -> Any:
    if key in settings and settings[key] not in (None, ""):
        return settings[key]
    env_val = os.getenv(env_key)
    if env_val not in (None, ""):
        return env_val
    return default


def _env_set(key: str) -> Set[str]:
    raw = os.getenv(key, "")
    if not raw.strip():
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _env_int_set(key: str) -> Set[int]:
    result: Set[int] = set()
    for item in _env_set(key):
        try:
            result.add(int(item))
        except ValueError:
            pass
    return result


@dataclass
class FilterConfig:
    include_categories: Set[str] = field(default_factory=lambda: _env_set("FILTER_INCLUDE_CATEGORIES"))
    exclude_categories: Set[str] = field(default_factory=lambda: _env_set("FILTER_EXCLUDE_CATEGORIES"))
    skip_user_ids: Set[int] = field(default_factory=lambda: _env_int_set("FILTER_SKIP_USER_IDS"))
    require_tags: Set[str] = field(default_factory=lambda: _env_set("FILTER_REQUIRE_TAGS"))
    only_worth_checking: bool = field(
        default_factory=lambda: os.getenv("FILTER_ONLY_WORTH_CHECKING", "").strip().lower() in ("1", "true", "yes")
    )


@dataclass
class Config:
    # ── Telegram ──
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    channel_username: str = ""

    # ── Extraction ──
    max_messages: int = 1000
    min_messages_per_user: int = 1
    topic_id: int = 0

    # ── LLM ──
    openai_api_key: str = ""
    model: str = "gpt-4o"
    users_per_batch: int = 5
    max_messages_per_user: int = 10
    max_retries: int = 3
    parallel_workers: int = 5

    # ── Files ──
    categories_file: str = "./config/categories.json"
    prompt_file: str = "./config/prompts/system_prompt.txt"
    few_shot_file: str = "./config/prompts/few_shot_example.txt"
    data_dir: str = "./data"
    output_dir: str = "./data/exports"

    # ── Categories (loaded from file) ──
    categories: List[tuple] = field(default_factory=list)
    category_rules: List[str] = field(default_factory=list)

    # ── Search ──
    embedding_model: str = "text-embedding-3-small"
    reranker_model: str = "gpt-4o-mini"
    search_top_k: int = 25
    search_confidence_threshold: float = 0.6

    # ── Server ────
    server_host: str = "127.0.0.1"
    server_port: int = 8787

    # ── Filtering (report) ──
    filters: FilterConfig = field(default_factory=FilterConfig)

    def __post_init__(self) -> None:
        self._apply_settings()
        if not self.categories:
            self._load_categories()

    def _apply_settings(self) -> None:
        s = _load_settings()

        def _int(key: str, env_key: str, default: int) -> int:
            return int(_get(s, key, env_key, default))

        def _float(key: str, env_key: str, default: float) -> float:
            return float(_get(s, key, env_key, default))

        def _str(key: str, env_key: str, default: str) -> str:
            return str(_get(s, key, env_key, default))

        self.telegram_api_id = _int("telegram_api_id", "TELEGRAM_API_ID", 0)
        self.telegram_api_hash = _str("telegram_api_hash", "TELEGRAM_API_HASH", "")
        self.telegram_phone = _str("telegram_phone", "TELEGRAM_PHONE", "")
        self.channel_username = _str("channel_username", "CHANNEL_USERNAME", "")
        self.openai_api_key = _str("openai_api_key", "OPENAI_API_KEY", "")
        self.model = _str("openai_model", "OPENAI_MODEL", "gpt-4o")
        self.max_messages = _int("max_messages", "MAX_MESSAGES", 1000)
        self.min_messages_per_user = _int("min_messages_per_user", "MIN_MESSAGES_PER_USER", 1)
        self.topic_id = _int("topic_id", "TOPIC_ID", 8)
        self.users_per_batch = _int("users_per_batch", "USERS_PER_BATCH", 5)
        self.max_messages_per_user = _int("max_messages_per_user", "MAX_MESSAGES_PER_USER", 10)
        self.max_retries = _int("max_retries", "MAX_RETRIES", 3)
        self.parallel_workers = _int("parallel_workers", "PARALLEL_WORKERS", 5)
        self.search_top_k = _int("search_top_k", "SEARCH_TOP_K", 25)
        self.search_confidence_threshold = _float(
            "search_confidence_threshold", "SEARCH_CONFIDENCE_THRESHOLD", 0.6
        )
        self.embedding_model = _str("embedding_model", "EMBEDDING_MODEL", "text-embedding-3-small")
        self.reranker_model = _str("reranker_model", "RERANKER_MODEL", "gpt-4o-mini")
        self.server_host = _str("server_host", "SERVER_HOST", "127.0.0.1")
        self.server_port = _int("server_port", "SERVER_PORT", 8787)
        self.data_dir = _str("data_dir", "DATA_DIR", "./data")
        self.output_dir = os.path.join(self.data_dir, "exports")

    def _load_categories(self) -> None:
        try:
            with open(self.categories_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.categories = [
                (cat["name"], cat["description"])
                for cat in data.get("categories", [])
            ]
            self.category_rules = data.get("assignment_rules", [])
            log.info(
                "Loaded %d categories and %d rules from %s",
                len(self.categories), len(self.category_rules), self.categories_file,
            )
        except FileNotFoundError:
            log.error("Categories file not found: %s", self.categories_file)
            raise RuntimeError(f"Categories file not found: {self.categories_file}")
        except (json.JSONDecodeError, KeyError) as e:
            log.error("Failed to parse categories file: %s", e)
            raise RuntimeError(f"Invalid categories file: {e}")

    def reload(self) -> None:
        self.categories = []
        self.__post_init__()

    def validate(self) -> List[str]:
        errors = []
        if not self.telegram_api_id:
            errors.append("telegram_api_id is missing")
        if not self.telegram_api_hash:
            errors.append("telegram_api_hash is missing")
        if not self.telegram_phone:
            errors.append("telegram_phone is missing")
        if not self.channel_username:
            errors.append("channel_username is missing")
        if not self.openai_api_key:
            errors.append("openai_api_key is missing")
        return errors

    def to_settings_dict(self) -> Dict[str, Any]:
        return {
            "telegram_api_id": self.telegram_api_id,
            "telegram_api_hash": self.telegram_api_hash,
            "telegram_phone": self.telegram_phone,
            "channel_username": self.channel_username,
            "openai_api_key": self.openai_api_key,
            "openai_model": self.model,
            "max_messages": self.max_messages,
            "min_messages_per_user": self.min_messages_per_user,
            "topic_id": self.topic_id,
            "users_per_batch": self.users_per_batch,
            "max_messages_per_user": self.max_messages_per_user,
            "max_retries": self.max_retries,
            "parallel_workers": self.parallel_workers,
            "search_top_k": self.search_top_k,
            "search_confidence_threshold": self.search_confidence_threshold,
            "embedding_model": self.embedding_model,
            "reranker_model": self.reranker_model,
        }
