import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import Config
from telegram_extractor import UserData

log = logging.getLogger(__name__)


@dataclass
class UserMetadata:
    age: Optional[int] = None
    city: Optional[str] = None
    country: Optional[str] = None
    profession: Optional[str] = None
    experience_years: Optional[int] = None
    languages: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    contact_info: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "age": self.age,
            "city": self.city,
            "country": self.country,
            "profession": self.profession,
            "experience_years": self.experience_years,
            "languages": self.languages if self.languages else None,
            "links": self.links if self.links else None,
            "contact_info": self.contact_info,
        }.items() if v is not None}


@dataclass
class CategoryResult:
    user_id: int
    username: str
    first_name: str
    last_name: str
    category: str
    tags: List[str]
    summary: str
    worth_checking: bool
    reasoning: str
    user_metadata: UserMetadata = field(default_factory=UserMetadata)
    messages: List[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        full_name = " ".join(p for p in [self.first_name, self.last_name] if p)
        if self.username:
            return f"@{self.username}" + (f" ({full_name})" if full_name else "")
        return full_name or f"User#{self.user_id}"



def _load_prompt_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        log.info("Loaded prompt from: %s", path)
        return content
    except FileNotFoundError:
        log.warning("Prompt file not found: %s — using empty string", path)
        return ""


RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "categorization_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "users": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "integer"},
                            "category": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "summary": {"type": "string"},
                            "worth_checking": {"type": "boolean"},
                            "reasoning": {"type": "string"},
                            "user_metadata": {
                                "type": "object",
                                "properties": {
                                    "age": {"type": ["integer", "null"]},
                                    "city": {"type": ["string", "null"]},
                                    "country": {"type": ["string", "null"]},
                                    "profession": {"type": ["string", "null"]},
                                    "experience_years": {"type": ["integer", "null"]},
                                    "languages": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "links": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "contact_info": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "age", "city", "country", "profession",
                                    "experience_years", "languages", "links",
                                    "contact_info",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "required": [
                            "user_id", "category", "tags", "summary",
                            "worth_checking", "reasoning", "user_metadata",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["users"],
            "additionalProperties": False,
        },
    },
}

CHECKPOINT_FILENAME = "_checkpoint.json"


class MessageCategorizer:
    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key)
        self._checkpoint_path = os.path.join(config.output_dir, CHECKPOINT_FILENAME)

    def _system_prompt(self) -> str:
        template = _load_prompt_file(self.config.prompt_file)
        if not template:
            log.error("System prompt is empty. Check PROMPT_FILE path: %s", self.config.prompt_file)
            raise RuntimeError(f"System prompt file not found or empty: {self.config.prompt_file}")
        categories_list = "\n".join(
            f"  - {name}: {desc}"
            for name, desc in self.config.categories
        )
        rules_list = "\n".join(
            f"   - {rule}" for rule in self.config.category_rules
        )
        return template.format(
            categories=categories_list,
            category_rules=rules_list,
        )

    def _few_shot(self) -> str:
        return _load_prompt_file(self.config.few_shot_file)

    def _user_prompt(self, users: List[UserData]) -> str:
        max_msgs = self.config.max_messages_per_user
        blocks = []
        for user in users:
            sample = user.messages[:max_msgs]
            msgs = "\n".join(f'  [{i+1}] "{m}"' for i, m in enumerate(sample))
            extra = (
                f"  (+{len(user.messages) - len(sample)} more not shown)"
                if len(user.messages) > len(sample) else ""
            )
            blocks.append(
                f"USER_ID: {user.user_id}\n"
                f"NAME: {user.display_name}\n"
                f"TOTAL MESSAGES: {len(user.messages)}{extra}\n"
                f"MESSAGES:\n{msgs}"
            )

        users_text = "\n\n" + ("\n\n" + "─" * 40 + "\n\n").join(blocks)

        return f"""\
Analyze and profile each user below.

{users_text}

─────────────────────────────────────────

Respond with a JSON object matching the schema. Include every user from the input.
"""

    # ── Single batch call with retry ──────────────────────────────────

    def _categorize_batch(self, users: List[UserData]) -> List[dict]:
        few_shot = self._few_shot()
        messages = [
            {"role": "system", "content": self._system_prompt()},
        ]
        if few_shot:
            messages.append({"role": "user", "content": few_shot})
        messages.append({"role": "user", "content": self._user_prompt(users)})

        last_error = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    response_format=RESPONSE_SCHEMA,
                    temperature=0.2,
                    messages=messages,
                )

                text = (response.choices[0].message.content or "{}").strip()
                data = json.loads(text)

                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for v in data.values():
                        if isinstance(v, list):
                            return v
                return []

            except json.JSONDecodeError as e:
                last_error = e
                log.warning("Attempt %d/%d: JSON parse error — %s", attempt, self.config.max_retries, e)
            except Exception as e:
                last_error = e
                log.warning("Attempt %d/%d: API error — %s", attempt, self.config.max_retries, e)

            if attempt < self.config.max_retries:
                wait = 2 ** attempt
                log.info("Retrying in %ds...", wait)
                time.sleep(wait)

        log.error("All %d attempts failed. Last error: %s", self.config.max_retries, last_error)
        return []

    def _load_checkpoint(self) -> Dict[int, dict]:
        """Load previously categorized results keyed by user_id."""
        if not os.path.exists(self._checkpoint_path):
            return {}
        try:
            with open(self._checkpoint_path, "r", encoding="utf-8") as f:
                items = json.load(f)
            checkpoint = {item["user_id"]: item for item in items}
            log.info("Loaded checkpoint with %d users.", len(checkpoint))
            return checkpoint
        except Exception as e:
            log.warning("Could not load checkpoint: %s", e)
            return {}

    def _save_checkpoint(self, results: List[dict]) -> None:
        os.makedirs(self.config.output_dir, exist_ok=True)
        with open(self._checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    def _clear_checkpoint(self) -> None:
        if os.path.exists(self._checkpoint_path):
            os.remove(self._checkpoint_path)
            log.info("Checkpoint cleared.")

    @staticmethod
    def _parse_metadata(raw: dict) -> UserMetadata:
        md = raw.get("user_metadata") or {}
        return UserMetadata(
            age=md.get("age"),
            city=md.get("city"),
            country=md.get("country"),
            profession=md.get("profession"),
            experience_years=md.get("experience_years"),
            languages=md.get("languages") or [],
            links=md.get("links") or [],
            contact_info=md.get("contact_info"),
        )

    def _build_result(self, user: UserData, entry: dict) -> CategoryResult:
        return CategoryResult(
            user_id=user.user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            category=entry.get("category", "Uncategorized"),
            tags=entry.get("tags", []),
            summary=entry.get("summary", ""),
            worth_checking=bool(entry.get("worth_checking", False)),
            reasoning=entry.get("reasoning", "Not provided"),
            user_metadata=self._parse_metadata(entry),
            messages=user.messages,
        )

    def _build_empty_result(self, user: UserData, reason: str) -> CategoryResult:
        return CategoryResult(
            user_id=user.user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            category="Uncategorized",
            tags=[],
            summary="",
            worth_checking=False,
            reasoning=reason,
            messages=user.messages,
        )

    def categorize_users(
        self, users_by_id: Dict[int, UserData]
    ) -> List[CategoryResult]:
        users_list = list(users_by_id.values())
        total = len(users_list)
        batch_size = self.config.users_per_batch
        total_batches = (total + batch_size - 1) // batch_size

        # Load checkpoint — skip users already processed
        checkpoint = self._load_checkpoint()
        checkpoint_raw: List[dict] = list(checkpoint.values())

        results: List[CategoryResult] = []
        skipped = 0

        log.info("Categorizing %d users in %d batch(es) of %d...", total, total_batches, batch_size)

        for i in range(0, total, batch_size):
            batch = users_list[i : i + batch_size]
            batch_num = i // batch_size + 1

            # Check which users in this batch are already in checkpoint
            to_process = [u for u in batch if u.user_id not in checkpoint]
            already_done = [u for u in batch if u.user_id in checkpoint]

            # Reconstruct results for checkpointed users
            for user in already_done:
                results.append(self._build_result(user, checkpoint[user.user_id]))
                skipped += 1

            if not to_process:
                log.info("  Batch %d/%d: all %d users from checkpoint, skipping.", batch_num, total_batches, len(batch))
                continue

            if already_done:
                log.info("  Batch %d/%d: %d from checkpoint, processing %d...", batch_num, total_batches, len(already_done), len(to_process))
            else:
                log.info("  Batch %d/%d: processing %d users...", batch_num, total_batches, len(to_process))

            try:
                raw = self._categorize_batch(to_process)
                cat_by_id = {item["user_id"]: item for item in raw}

                for user in to_process:
                    entry = cat_by_id.get(user.user_id, {})
                    result = self._build_result(user, entry)
                    results.append(result)
                    # Add to checkpoint raw data
                    checkpoint_raw.append(entry if entry else {
                        "user_id": user.user_id,
                        "category": "Uncategorized",
                        "tags": [],
                        "summary": "",
                        "worth_checking": False,
                        "reasoning": "Categorization failed",
                        "user_metadata": {},
                    })

                # Save checkpoint after each successful batch
                self._save_checkpoint(checkpoint_raw)
                log.info("  Batch %d/%d: done. Checkpoint saved.", batch_num, total_batches)

            except Exception as e:
                log.error("  Batch %d/%d: ERROR — %s", batch_num, total_batches, e)
                for user in to_process:
                    results.append(self._build_empty_result(user, f"Categorization failed: {e}"))

        if skipped:
            log.info("Restored %d users from checkpoint.", skipped)

        # Clear checkpoint on successful completion
        self._clear_checkpoint()

        return results
