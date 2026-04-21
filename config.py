import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Set

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)


def _env_set(key: str) -> Set[str]:
    raw = os.getenv(key, "")
    if not raw.strip():
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _env_int_set(key: str) -> Set[int]:
    result = set()
    for item in _env_set(key):
        try:
            result.add(int(item))
        except ValueError:
            log.warning("Ignoring non-integer value '%s' in %s", item, key)
    return result


@dataclass
class FilterConfig:
    include_categories: Set[str] = field(default_factory=lambda: _env_set("FILTER_INCLUDE_CATEGORIES"))
    exclude_categories: Set[str] = field(default_factory=lambda: _env_set("FILTER_EXCLUDE_CATEGORIES"))
    skip_user_ids: Set[int] = field(default_factory=lambda: _env_int_set("FILTER_SKIP_USER_IDS"))
    require_tags: Set[str] = field(default_factory=lambda: _env_set("FILTER_REQUIRE_TAGS"))
    only_worth_checking: bool = bool(os.getenv("FILTER_ONLY_WORTH_CHECKING", "").strip().lower() in ("1", "true", "yes"))

@dataclass
class Config:
    # Telegram
    telegram_api_id: int = int(os.getenv("TELEGRAM_API_ID", "0"))
    telegram_api_hash: str = os.getenv("TELEGRAM_API_HASH", "")
    telegram_phone: str = os.getenv("TELEGRAM_PHONE", "")
    channel_username: str = os.getenv("CHANNEL_USERNAME", "")

    # Extraction
    max_messages: int = int(os.getenv("MAX_MESSAGES", "1000"))
    min_messages_per_user: int = int(os.getenv("MIN_MESSAGES_PER_USER", "1"))
    topic_id: int = int(os.getenv("TOPIC_ID", "0"))

    # LLM
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    users_per_batch: int = int(os.getenv("USERS_PER_BATCH", "5"))
    max_messages_per_user: int = int(os.getenv("MAX_MESSAGES_PER_USER", "10"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    prompt_file: str = os.getenv("PROMPT_FILE", "./prompts/system_prompt.txt")
    few_shot_file: str = os.getenv("FEW_SHOT_FILE", "./prompts/few_shot_example.txt")
    categories_file: str = os.getenv("CATEGORIES_FILE", "./config/categories.json")

    # Categories (loaded from file)
    categories: List[tuple] = field(default_factory=list)
    category_rules: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.categories:
            self._load_categories()

    def _load_categories(self) -> None:
        try:
            with open(self.categories_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.categories = [
                (cat["name"], cat["description"])
                for cat in data.get("categories", [])
            ]
            self.category_rules = data.get("assignment_rules", [])
            log.info("Loaded %d categories and %d rules from %s",
                     len(self.categories), len(self.category_rules), self.categories_file)
        except FileNotFoundError:
            log.error("Categories file not found: %s", self.categories_file)
            raise RuntimeError(f"Categories file not found: {self.categories_file}")
        except (json.JSONDecodeError, KeyError) as e:
            log.error("Failed to parse categories file: %s", e)
            raise RuntimeError(f"Invalid categories file: {e}")

    # Filtering
    filters: FilterConfig = field(default_factory=FilterConfig)

    # Output
    output_dir: str = os.getenv("OUTPUT_DIR", "./output")

    def validate(self) -> List[str]:
        errors = []
        if not self.telegram_api_id:
            errors.append("TELEGRAM_API_ID is missing")
        if not self.telegram_api_hash:
            errors.append("TELEGRAM_API_HASH is missing")
        if not self.telegram_phone:
            errors.append("TELEGRAM_PHONE is missing")
        if not self.channel_username:
            errors.append("CHANNEL_USERNAME is missing")
        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is missing")
        return errors
