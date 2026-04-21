from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from telethon import TelegramClient
from telethon.tl.types import User

from app.config import Config
from app.storage.store import FileStore, MessageRecord, UserRecord

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class TelegramExtractor:
    def __init__(self, config: Config, store: FileStore) -> None:
        self.config = config
        self.store = store
        self.client = TelegramClient(
            "tg_session",
            config.telegram_api_id,
            config.telegram_api_hash,
        )

    async def _authenticate(self) -> None:
        import getpass

        import qrcode
        from telethon.errors import SessionPasswordNeededError

        await self.client.connect()
        log.info("Connected: %s", self.client.is_connected())

        if await self.client.is_user_authorized():
            me = await self.client.get_me()
            log.info("Already authorized as: %s (@%s)", me.first_name, me.username)
            return

        log.info("QR Code Login — open Telegram → Settings → Devices → Link Desktop Device")

        while True:
            qr_login = await self.client.qr_login()

            qr = qrcode.QRCode()
            qr.add_data(qr_login.url)
            qr.print_ascii(invert=True)

            log.info("Waiting for scan (30s)...")
            try:
                await qr_login.wait(30)
                break
            except asyncio.TimeoutError:
                log.warning("QR expired — generating a new one...")
            except SessionPasswordNeededError:
                log.info("Two-factor authentication detected.")
                password = getpass.getpass("  Enter your Telegram 2FA password: ")
                await self.client.sign_in(password=password)
                break

        me = await self.client.get_me()
        log.info("Authorized as: %s (@%s)", me.first_name, me.username)

    async def extract_messages(self) -> int:
        """Extract messages and upsert into FileStore. Returns total message count."""
        skip_ids = self.config.filters.skip_user_ids

        log.info(
            "Extraction config — max_messages=%d, min_messages_per_user=%d, topic_id=%s",
            self.config.max_messages,
            self.config.min_messages_per_user,
            self.config.topic_id or "all",
        )

        await self._authenticate()

        # Accumulate messages per user in memory, then bulk-upsert per user
        user_messages: dict[int, list[MessageRecord]] = {}
        user_records: dict[int, UserRecord] = {}
        total_count = 0

        try:
            channel = self.config.channel_username.strip()
            channel_id = int(channel) if channel.lstrip("-").isdigit() else channel
            entity = await self.client.get_entity(channel_id)
            title = getattr(entity, "title", self.config.channel_username)
            log.info("Connected to: %s", title)
            log.info("Fetching up to %d messages from Telegram API...", self.config.max_messages)

            topic_id = self.config.topic_id if self.config.topic_id else None
            if topic_id:
                log.info("Filtering to topic ID: %d", topic_id)
            else:
                log.info("Scraping all topics.")


            async for message in self.client.iter_messages(
                entity, limit=len(self.store.all_users()) + self.config.max_messages, reply_to=topic_id
            ):
                if not message.text or not message.sender_id:
                    continue

                sender_id = message.sender_id
                if sender_id in skip_ids:
                    continue

                if sender_id not in user_records:
                    try:
                        sender = await message.get_sender()
                        if isinstance(sender, User):
                            user_records[sender_id] = UserRecord(
                                user_id=sender_id,
                                username=sender.username or "",
                                first_name=sender.first_name or "",
                                last_name=sender.last_name or "",
                            )
                        else:
                            user_records[sender_id] = UserRecord(
                                user_id=sender_id,
                                username=getattr(sender, "username", "") or "",
                                first_name=getattr(sender, "title", f"Entity#{sender_id}") or "",
                                last_name="",
                            )
                    except Exception:
                        user_records[sender_id] = UserRecord(
                            user_id=sender_id,
                            username="",
                            first_name=f"User#{sender_id}",
                            last_name="",
                        )
                    user_messages[sender_id] = []

                sent_ts = message.date.timestamp() if message.date else time.time()
                user_messages[sender_id].append(
                    MessageRecord(
                        message_id=message.id,
                        text=message.text,
                        sent_at=sent_ts,
                    )
                )
                total_count += 1

                if total_count % 200 == 0:
                    log.info("  ...%d messages collected so far", total_count)

        finally:
            await self.client.disconnect()

        log.info("Extracted %d messages from %d unique senders.", total_count, len(user_records))

        # Filter by min_messages_per_user before persisting
        if self.config.min_messages_per_user > 1:
            before = len(user_records)
            user_records = {
                uid: u
                for uid, u in user_records.items()
                if len(user_messages.get(uid, [])) >= self.config.min_messages_per_user
            }
            log.info(
                "Filtered to %d users with >= %d messages (removed %d).",
                len(user_records),
                self.config.min_messages_per_user,
                before - len(user_records),
            )

        # Persist to FileStore
        for uid, user in user_records.items():
            self.store.upsert_user(user)
            msgs = user_messages.get(uid, [])
            new = self.store.upsert_messages(uid, msgs)
            if new:
                log.debug("User %d: %d new messages upserted.", uid, new)

        log.info(
            "Extraction done — %d new messages fetched this run, %d users upserted. "
            "Store now contains %d total users (all will be considered for categorization).",
            total_count,
            len(user_records),
            len(self.store.all_users()),
        )
        return total_count
