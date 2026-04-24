from __future__ import annotations

import hashlib
import json
import logging
from typing import List

from app.categorize.schema import SCHEMA_VERSION
from app.config import Config

log = logging.getLogger(__name__)

def _read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        log.warning("File not found: %s — using empty string", path)
        return ""


class PromptBuilder:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._system_template = _read_file(config.prompt_file)
        self._few_shot_text = _read_file(config.few_shot_file)
        self._hash: str | None = None

    @property
    def hash(self) -> str:
        if self._hash is None:
            self._hash = self.compute_hash()
        return self._hash

    def compute_hash(self) -> str:
        payload = {
            "system_prompt": self._system_template,
            "few_shot": self._few_shot_text,
            "categories": [(name, desc) for name, desc in self.config.categories],
            "category_rules": list(self.config.category_rules),
            "response_schema_version": SCHEMA_VERSION,
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def system_prompt(self) -> str:
        if not self._system_template:
            raise RuntimeError(
                f"System prompt file not found or empty: {self.config.prompt_file}"
            )
        categories_list = "\n".join(
            f"  - {name}: {desc}" for name, desc in self.config.categories
        )
        rules_list = "\n".join(f"   - {rule}" for rule in self.config.category_rules)
        return self._system_template.format(
            categories=categories_list,
            category_rules=rules_list,
        )

    def few_shot(self) -> str:
        return self._few_shot_text

    def user_prompt(self, users: List[tuple]) -> str:
        max_msgs = self.config.max_messages_per_user
        blocks = []
        for user_id, display_name, messages in users:
            sample = messages[:max_msgs]
            msgs = "\n".join(f'  [{i + 1}] "{m}"' for i, m in enumerate(sample))
            extra = (
                f"  (+{len(messages) - len(sample)} more not shown)"
                if len(messages) > len(sample)
                else ""
            )
            blocks.append(
                f"USER_ID: {user_id}\n"
                f"NAME: {display_name}\n"
                f"TOTAL MESSAGES: {len(messages)}{extra}\n"
                f"MESSAGES:\n{msgs}"
            )

        users_text = "\n\n" + ("\n\n" + "─" * 40 + "\n\n").join(blocks)
        return (
            f"Analyze and profile each user below.\n"
            f"{users_text}\n\n"
            f"─────────────────────────────────────────\n\n"
            f"Respond with a JSON object matching the schema. Include every user from the input."
        )
