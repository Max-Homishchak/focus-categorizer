import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List

from telethon import TelegramClient
from telethon.tl.types import User

from config import Config

log = logging.getLogger(__name__)


@dataclass
class UserData:
    user_id: int
    username: str
    first_name: str
    last_name: str
    messages: List[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        full_name = " ".join(p for p in [self.first_name, self.last_name] if p)
        if self.username:
            return f"@{self.username}" + (f" ({full_name})" if full_name else "")
        return full_name or f"User#{self.user_id}"


class TelegramExtractor:
    def __init__(self, config: Config):
        self.config = config
        self.client = TelegramClient(
            "tg_session",
            config.telegram_api_id,
            config.telegram_api_hash,
        )

    async def _authenticate(self) -> None:
        import qrcode

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

        me = await self.client.get_me()
        log.info("Authorized as: %s (@%s)", me.first_name, me.username)

    async def extract_messages(self) -> Dict[int, UserData]:
        users: Dict[int, UserData] = {}
        skip_ids = self.config.filters.skip_user_ids

        await self._authenticate()

        try:
            channel = self.config.channel_username.strip()
            channel_id = int(channel) if channel.lstrip("-").isdigit() else channel
            entity = await self.client.get_entity(channel_id)
            title = getattr(entity, "title", self.config.channel_username)
            log.info("Connected to: %s", title)
            log.info("Fetching up to %d messages...", self.config.max_messages)

            topic_id = self.config.topic_id if self.config.topic_id else None
            if topic_id:
                log.info("Filtering to topic ID: %d", topic_id)
            else:
                log.info("Scraping all topics.")

            count = 0
            async for message in self.client.iter_messages(
                entity, limit=self.config.max_messages, reply_to=topic_id
            ):
                if not message.text or not message.sender_id:
                    continue

                sender_id = message.sender_id

                # Skip users the operator marked to ignore
                if sender_id in skip_ids:
                    continue

                if sender_id not in users:
                    try:
                        sender = await message.get_sender()
                        if isinstance(sender, User):
                            users[sender_id] = UserData(
                                user_id=sender_id,
                                username=sender.username or "",
                                first_name=sender.first_name or "",
                                last_name=sender.last_name or "",
                            )
                        else:
                            users[sender_id] = UserData(
                                user_id=sender_id,
                                username=getattr(sender, "username", "") or "",
                                first_name=getattr(sender, "title", f"Entity#{sender_id}") or "",
                                last_name="",
                            )
                    except Exception:
                        users[sender_id] = UserData(
                            user_id=sender_id,
                            username="",
                            first_name=f"User#{sender_id}",
                            last_name="",
                        )

                users[sender_id].messages.append(message.text)
                count += 1

                if count % 200 == 0:
                    log.info("  ...%d messages collected so far", count)

        finally:
            await self.client.disconnect()

        log.info("Extracted %d messages from %d unique senders.", count, len(users))

        if self.config.min_messages_per_user > 1:
            before = len(users)
            users = {
                uid: u
                for uid, u in users.items()
                if len(u.messages) >= self.config.min_messages_per_user
            }
            log.info(
                "Filtered to %d users with >= %d messages (removed %d).",
                len(users), self.config.min_messages_per_user, before - len(users),
            )

        return users
