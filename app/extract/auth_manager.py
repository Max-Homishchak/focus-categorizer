from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional

log = logging.getLogger(__name__)


class TelegramAuthManager:
    """Holds Telegram auth state for the lifetime of the server process."""

    def __init__(self) -> None:
        self.state: str = "idle"  # idle | starting | qr_shown | needs_2fa | authorized | error
        self.qr_svg: Optional[str] = None
        self.authorized_name: Optional[str] = None
        self.error: Optional[str] = None
        self._password_event: asyncio.Event = asyncio.Event()
        self._password: Optional[str] = None
        self._task: Optional[asyncio.Task] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def check_authorized(self, config) -> bool:
        from telethon import TelegramClient
        client = TelegramClient("tg_session", config.telegram_api_id, config.telegram_api_hash)
        try:
            await client.connect()
            return await client.is_user_authorized()
        except Exception:
            return False
        finally:
            await client.disconnect()

    def start_auth(self, config) -> None:
        """Start QR auth as a background task (idempotent if already running)."""
        if self._task and not self._task.done():
            return
        self.state = "starting"
        self.error = None
        self.qr_svg = None
        self._task = asyncio.create_task(self._run_auth(config))

    async def submit_password(self, password: str) -> None:
        self._password = password
        self._password_event.set()

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "qr_svg": self.qr_svg if self.state == "qr_shown" else None,
            "authorized_name": self.authorized_name,
            "error": self.error,
        }

    async def _run_auth(self, config) -> None:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError

        client: Optional[TelegramClient] = None
        try:
            client = TelegramClient("tg_session", config.telegram_api_id, config.telegram_api_hash)
            await client.connect()

            if await client.is_user_authorized():
                me = await client.get_me()
                self.authorized_name = me.first_name or me.username or "User"
                self.state = "authorized"
                log.info("Telegram: already authorized as %s.", self.authorized_name)
                return

            log.info("Telegram: starting QR login flow.")
            while True:
                qr_login = await client.qr_login()
                self.qr_svg = self._render_qr_svg(qr_login.url)
                self.state = "qr_shown"
                log.info("Telegram: QR code ready — waiting for scan (30s).")

                try:
                    await qr_login.wait(30)
                    me = await client.get_me()
                    self.authorized_name = me.first_name or me.username or "User"
                    self.state = "authorized"
                    log.info("Telegram: QR scanned — authorized as %s.", self.authorized_name)
                    return
                except asyncio.TimeoutError:
                    log.info("Telegram: QR expired — regenerating.")
                    continue
                except SessionPasswordNeededError:
                    log.info("Telegram: 2FA required — waiting for password from UI.")
                    self.state = "needs_2fa"
                    self._password_event.clear()
                    await self._password_event.wait()
                    await client.sign_in(password=self._password)
                    me = await client.get_me()
                    self.authorized_name = me.first_name or me.username or "User"
                    self.state = "authorized"
                    log.info("Telegram: 2FA accepted — authorized as %s.", self.authorized_name)
                    return

        except Exception as e:
            self.state = "error"
            self.error = str(e)
            log.error("Telegram auth error: %s", e)
        finally:
            if client:
                await client.disconnect()

    @staticmethod
    def _render_qr_svg(url: str) -> str:
        import re

        import qrcode
        import qrcode.image.svg as qr_svg

        img = qrcode.make(url, image_factory=qr_svg.SvgImage)
        buf = io.BytesIO()
        img.save(buf)
        svg = buf.getvalue().decode("utf-8")

        # qrcode's SvgImage uses xmlns:svg namespace prefixes (<svg:rect …>)
        # which browsers silently drop when injected via innerHTML.
        # Strip the prefix so elements render as plain SVG.
        svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()           # drop XML declaration
        svg = svg.replace("<svg:rect", "<rect").replace("</svg:rect>", "</rect>")
        svg = svg.replace(' xmlns:svg="http://www.w3.org/2000/svg"', "")

        return svg
