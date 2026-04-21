from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

log = logging.getLogger(__name__)

# ── Data models ───

@dataclass
class UserRecord:
    user_id: int
    username: str
    first_name: str
    last_name: str
    updated_at: float = field(default_factory=time.time)

    @property
    def display_name(self) -> str:
        full_name = " ".join(p for p in [self.first_name, self.last_name] if p)
        if self.username:
            return f"@{self.username}" + (f" ({full_name})" if full_name else "")
        return full_name or f"User#{self.user_id}"


@dataclass
class MessageRecord:
    message_id: int
    text: str
    sent_at: float
    fetched_at: float = field(default_factory=time.time)


@dataclass
class CategorizationRecord:
    user_id: int
    category: str
    tags: List[str]
    summary: str
    worth_checking: bool
    reasoning: str
    user_metadata: Dict[str, Any]
    prompt_hash: str
    last_message_id: int
    message_count_seen: int
    categorized_at: float = field(default_factory=time.time)


@dataclass
class EmbeddingIndex:
    ids: Any        # np.ndarray int64, shape (N,)
    vectors: Any    # np.ndarray float32, shape (N, dim)
    prompt_hash: str
    model: str


# ── Helpers ───

def _atomic_write_json(path: str, data: Any, lock: threading.Lock) -> None:
    tmp = path + ".tmp"
    with lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# ── FileStore ───

class FileStore:
    def __init__(self, data_dir: str = "./data") -> None:
        self.data_dir = Path(data_dir)
        self._cat_dir = self.data_dir / "categorizations"
        self._meta_path = str(self.data_dir / "meta.json")
        self._settings_path = str(self.data_dir / "settings.json")
        self._users_path = str(self.data_dir / "users.json")
        self._messages_path = str(self.data_dir / "messages.json")
        self._embeddings_path = str(self.data_dir / "embeddings.npz")

        # One lock per file to serialize writers
        self._meta_lock = threading.Lock()
        self._settings_lock = threading.Lock()
        self._users_lock = threading.Lock()
        self._messages_lock = threading.Lock()

    def init(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cat_dir.mkdir(exist_ok=True)
        for path, default in [
            (self._meta_path, {}),
            (self._settings_path, {}),
            (self._users_path, {}),
            (self._messages_path, {}),
        ]:
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(default, f)

    # ── meta ────

    def get_meta(self, key: str) -> Optional[str]:
        return _read_json(self._meta_path, {}).get(key)

    def set_meta(self, key: str, value: Any) -> None:
        meta = _read_json(self._meta_path, {})
        meta[key] = value
        _atomic_write_json(self._meta_path, meta, self._meta_lock)

    # ── settings ────

    def load_settings(self) -> Dict[str, Any]:
        return _read_json(self._settings_path, {})

    def save_settings(self, settings: Dict[str, Any]) -> None:
        _atomic_write_json(self._settings_path, settings, self._settings_lock)

    # ── users ─────

    def upsert_user(self, user: UserRecord) -> None:
        users = _read_json(self._users_path, {})
        users[str(user.user_id)] = {
            "user_id": user.user_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "updated_at": user.updated_at,
        }
        _atomic_write_json(self._users_path, users, self._users_lock)

    def all_users(self) -> List[UserRecord]:
        raw = _read_json(self._users_path, {})
        return [
            UserRecord(
                user_id=int(v["user_id"]),
                username=v.get("username", ""),
                first_name=v.get("first_name", ""),
                last_name=v.get("last_name", ""),
                updated_at=v.get("updated_at", 0.0),
            )
            for v in raw.values()
        ]


    def upsert_messages(self, user_id: int, msgs: List[MessageRecord]) -> int:
        all_msgs = _read_json(self._messages_path, {})
        key = str(user_id)
        existing: Dict[str, Any] = {str(m["message_id"]): m for m in all_msgs.get(key, [])}
        new_count = 0
        for m in msgs:
            mid = str(m.message_id)
            if mid not in existing:
                existing[mid] = {
                    "message_id": m.message_id,
                    "text": m.text,
                    "sent_at": m.sent_at,
                    "fetched_at": m.fetched_at,
                }
                new_count += 1
        all_msgs[key] = sorted(existing.values(), key=lambda x: x["message_id"])
        _atomic_write_json(self._messages_path, all_msgs, self._messages_lock)
        return new_count

    def messages_for(self, user_id: int, limit: Optional[int] = None) -> List[MessageRecord]:
        all_msgs = _read_json(self._messages_path, {})
        raw = all_msgs.get(str(user_id), [])
        if limit:
            raw = raw[:limit]
        return [
            MessageRecord(
                message_id=m["message_id"],
                text=m["text"],
                sent_at=m.get("sent_at", 0.0),
                fetched_at=m.get("fetched_at", 0.0),
            )
            for m in raw
        ]

    def max_message_id_for(self, user_id: int) -> Optional[int]:
        msgs = self.messages_for(user_id)
        if not msgs:
            return None
        return max(m.message_id for m in msgs)

    # ── categorizations (per-user shards) ───

    def _shard_path(self, user_id: int) -> str:
        return str(self._cat_dir / f"{user_id}.json")

    def get_categorization(self, user_id: int) -> Optional[CategorizationRecord]:
        path = self._shard_path(user_id)
        raw = _read_json(path, None)
        if raw is None:
            return None
        return CategorizationRecord(
            user_id=raw["user_id"],
            category=raw.get("category", "Uncategorized"),
            tags=raw.get("tags", []),
            summary=raw.get("summary", ""),
            worth_checking=raw.get("worth_checking", False),
            reasoning=raw.get("reasoning", ""),
            user_metadata=raw.get("user_metadata", {}),
            prompt_hash=raw.get("prompt_hash", ""),
            last_message_id=raw.get("last_message_id", 0),
            message_count_seen=raw.get("message_count_seen", 0),
            categorized_at=raw.get("categorized_at", 0.0),
        )

    def save_categorization(self, rec: CategorizationRecord) -> None:
        path = self._shard_path(rec.user_id)
        tmp = path + ".tmp"
        data = asdict(rec)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def all_categorizations(self) -> List[CategorizationRecord]:
        results = []
        for p in self._cat_dir.glob("*.json"):
            if p.suffix == ".json" and not p.name.endswith(".tmp"):
                rec = self.get_categorization(int(p.stem))
                if rec is not None:
                    results.append(rec)
        return results

    def delete_all_categorizations(self) -> None:
        for p in self._cat_dir.glob("*.json"):
            p.unlink(missing_ok=True)
        log.info("Deleted all categorization shards.")

    def users_needing_categorization(self, prompt_hash: str) -> List[int]:
        pending: List[int] = []
        for user in self.all_users():
            cat = self.get_categorization(user.user_id)
            max_mid = self.max_message_id_for(user.user_id) or 0
            if cat is None:
                pending.append(user.user_id)
            elif cat.prompt_hash != prompt_hash:
                pending.append(user.user_id)
            elif max_mid > cat.last_message_id:
                pending.append(user.user_id)
        return pending

    # ── embeddings ───

    def save_embeddings(
        self,
        ids: "np.ndarray",
        vectors: "np.ndarray",
        model: str,
        prompt_hash: str,
    ) -> None:
        # np.savez auto-appends .npz; use a base tmp name without .npz so
        # the actual file created is <base>.npz which we can os.replace
        base_tmp = self._embeddings_path.removesuffix(".npz") + ".tmp"
        np.savez(
            base_tmp,
            ids=ids.astype(np.int64),
            vectors=vectors.astype(np.float32),
        )
        os.replace(base_tmp + ".npz", self._embeddings_path)
        self.set_meta("embedding_model", model)
        self.set_meta("embedding_prompt_hash", prompt_hash)
        log.info("Saved embeddings: %d vectors (%s, hash=%s)", len(ids), model, prompt_hash[:12])

    def load_embeddings(self) -> Optional[EmbeddingIndex]:
        if not os.path.exists(self._embeddings_path):
            return None
        stored_hash = self.get_meta("embedding_prompt_hash")
        current_hash = self.get_meta("prompt_hash")
        if stored_hash != current_hash:
            log.info("Embeddings stale (hash mismatch) — will rebuild.")
            return None
        model = self.get_meta("embedding_model") or "text-embedding-3-small"
        try:
            npz = np.load(self._embeddings_path)
            return EmbeddingIndex(
                ids=npz["ids"],
                vectors=npz["vectors"],
                prompt_hash=stored_hash or "",
                model=model,
            )
        except Exception as e:
            log.warning("Failed to load embeddings: %s", e)
            return None

    def delete_embeddings(self) -> None:
        if os.path.exists(self._embeddings_path):
            os.remove(self._embeddings_path)
        self.set_meta("embedding_prompt_hash", None)
        log.info("Deleted embeddings.")

    # ── compaction ───

    def compact_categorizations(self) -> None:
        """Merge all shards into a single categorizations.json for offline use."""
        all_cats = self.all_categorizations()
        path = str(self.data_dir / "categorizations.json")
        _atomic_write_json(path, [asdict(c) for c in all_cats], threading.Lock())
        log.info("Compacted %d categorizations → %s", len(all_cats), path)