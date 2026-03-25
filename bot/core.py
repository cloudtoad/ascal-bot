"""Core bot lifecycle: login, sync, module management."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from nio import (
    AsyncClient,
    AsyncClientConfig,
    InviteMemberEvent,
    JoinResponse,
    LoginResponse,
    MatrixRoom,
    RoomMemberEvent,
    RoomMessageText,
)

from bot.context import BotContext, _LoggerFactory
from bot.dispatcher import Dispatcher
from bot.messaging import Messenger
from bot.notifications import NotificationBus

if TYPE_CHECKING:
    from bot.config import AppConfig
    from bot.module import Module

log = logging.getLogger(__name__)

SESSION_FILE = "session.json"


class BotCore:
    """Top-level bot class that owns the nio client and module lifecycle."""

    def __init__(self, config: "AppConfig") -> None:
        self._config = config
        self._modules: list["Module"] = []
        self._client: AsyncClient | None = None
        self._bot_ctx: BotContext | None = None

    def register_module(self, module: "Module") -> None:
        """Queue a module for setup when the bot starts."""
        self._modules.append(module)
        log.info("Module queued: %s", module.name)

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Matrix, set up modules, and sync forever."""
        mc = self._config.matrix

        # 1. Create AsyncClient
        client_config = AsyncClientConfig(
            encryption_enabled=True,
            store_sync_tokens=True,
        )
        store_path = mc.store_path
        os.makedirs(store_path, mode=0o750, exist_ok=True)

        self._client = AsyncClient(
            homeserver=mc.homeserver,
            user=mc.username,
            store_path=store_path,
            config=client_config,
        )

        # 2. Login (session restore or fresh)
        await self._login()

        # 3. Upload encryption keys if needed
        if self._client.should_upload_keys:
            await self._client.keys_upload()

        # 4. Register nio callbacks
        messenger = Messenger(self._client)
        dispatcher = Dispatcher(
            prefix=self._config.bot.prefix,
            messenger=messenger,
            bot_user_id=self._client.user_id,
        )
        notifications = NotificationBus(messenger, self._config)

        self._client.add_event_callback(
            dispatcher.dispatch_message, RoomMessageText
        )
        self._client.add_event_callback(
            dispatcher.dispatch_event, RoomMemberEvent
        )
        self._client.add_event_callback(
            self._on_invite, InviteMemberEvent
        )

        # 5. Initial sync to skip old messages
        log.info("Running initial sync...")
        resp = await self._client.sync(timeout=30000, full_state=True)
        log.info(
            "Connected to %s as %s (%s)",
            self._client.homeserver,
            self._client.user_id,
            self._client.device_id,
        )

        # 6. Enable ignore_unverified_devices after sync loads olm state
        if hasattr(self._client, "olm") and self._client.olm is not None:
            self._client.olm.ignore_unverified_devices = True
            key = self._client.olm.account.identity_keys.get("ed25519", "")
            if key:
                pretty = " ".join(key[i : i + 4] for i in range(0, len(key), 4))
                log.info("Session fingerprint: %s", pretty)

        # 7. Build BotContext and set up modules
        import bot.user_settings as user_settings_module

        self._bot_ctx = BotContext(
            client=self._client,
            config=self._config,
            dispatcher=dispatcher,
            messenger=messenger,
            notifications=notifications,
            user_settings=user_settings_module,
            logger_factory=_LoggerFactory(),
        )

        for module in self._modules:
            log.info("Setting up module: %s", module.name)
            await module.setup(self._bot_ctx)

        # 8. Sync forever
        log.info("Entering sync loop...")
        await self._client.sync_forever(timeout=30000, full_state=True)

    async def stop(self) -> None:
        """Tear down modules and close the client."""
        for module in reversed(self._modules):
            try:
                log.info("Tearing down module: %s", module.name)
                await module.teardown()
            except Exception:
                log.exception("Error tearing down module %s", module.name)

        if self._client:
            await self._client.close()
            log.info("Client closed.")

    # ── Login ────────────────────────────────────────────────────────────

    async def _login(self) -> None:
        """Authenticate with the homeserver.

        Priority:
            1. Saved session.json (access_token + device_id + user_id)
            2. Config access_token (set directly, then persist)
            3. Config password (login, then persist)
        """
        mc = self._config.matrix
        session = self._load_session()

        if session:
            log.info("Restoring session for %s", session["user_id"])
            self._client.access_token = session["access_token"]
            self._client.user_id = session["user_id"]
            self._client.device_id = session["device_id"]
            if hasattr(self._client, "load_store"):
                self._client.load_store()
            return

        if mc.access_token:
            log.info("Using access_token from config for %s", mc.username)
            self._client.access_token = mc.access_token
            # We need to resolve user_id and device_id via whoami
            import aiohttp

            async with aiohttp.ClientSession() as session_http:
                async with session_http.get(
                    f"{mc.homeserver}/_matrix/client/r0/account/whoami",
                    headers={"Authorization": f"Bearer {mc.access_token}"},
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ConnectionError(
                            f"whoami failed ({resp.status}): {body}"
                        )
                    data = await resp.json()

            self._client.user_id = data["user_id"]
            self._client.device_id = data.get("device_id", "")
            if hasattr(self._client, "load_store"):
                self._client.load_store()
            self._save_session()
            return

        if mc.password:
            log.info("Logging in with password for %s", mc.username)
            resp = await self._client.login(password=mc.password)
            if isinstance(resp, LoginResponse):
                log.info("Login successful, device_id=%s", resp.device_id)
                self._save_session()
            else:
                raise ConnectionError(f"Login failed: {resp}")
            return

        raise ValueError(
            "No authentication method available. "
            "Provide password, access_token, or a valid session.json."
        )

    def _load_session(self) -> dict | None:
        """Load saved session from session.json if it exists."""
        path = Path(SESSION_FILE)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if all(k in data for k in ("access_token", "device_id", "user_id")):
                return data
            log.warning("session.json is missing required fields, ignoring")
            return None
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read session.json: %s", exc)
            return None

    def _save_session(self) -> None:
        """Persist current session credentials to session.json."""
        data = {
            "access_token": self._client.access_token,
            "device_id": self._client.device_id,
            "user_id": self._client.user_id,
        }
        Path(SESSION_FILE).write_text(json.dumps(data, indent=2))
        log.info("Session saved to %s", SESSION_FILE)

    # ── Invite handler ───────────────────────────────────────────────────

    async def _on_invite(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        """Auto-join all room invites."""
        # Only respond to invites directed at us
        if event.state_key != self._client.user_id:
            return

        log.info("Invited to %s by %s — joining", room.room_id, event.sender)
        resp = await self._client.join(room.room_id)
        if isinstance(resp, JoinResponse):
            log.info("Joined %s", room.room_id)
        else:
            log.warning("Failed to join %s: %s", room.room_id, resp)
