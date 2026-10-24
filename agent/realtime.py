"""Higgs Realtime WebSocket client for manual turn control.

Logs one line per event and never audio. Two server rules are handled here so callers
don't have to (see agent/CLAUDE.md, Stage 1 results):
- commit is rejected while a response is being generated, so a commit asked for then is
  queued and sent after response.done;
- after a server-executed web_search the server starts the follow-up response itself, so
  create_response() refuses while that follow-up is pending, and commits wait too: a user
  item committed while the search runs makes the server drop the follow-up (Stage 2 sim).
"""

import asyncio
import base64
import json
import logging
import time
from typing import Awaitable, Callable

import websockets
from websockets.protocol import State

log = logging.getLogger("viva.realtime")

EventHandler = Callable[[str, dict], Awaitable[None]]
MIN_COMMIT_BYTES = 24_000 * 2 // 10  # 100 ms of 24 kHz 16-bit mono: the server's minimum


class RealtimeClient:
    def __init__(self, url: str, api_key: str, on_event: EventHandler, name: str = "voice"):
        self.name = name  # "voice" or "brain": both sessions log through here
        self.url = url
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.on_event = on_event
        self.ws = None
        self.response_active = False  # requested or generating
        self.server_tool_pending = False  # a server web_search is running; its follow-up is coming
        self.server_tool_since = 0.0
        self.assistant_item_id: str | None = None
        self._pending_commit = False
        self._uncommitted = 0  # bytes appended since the last commit
        self._awaiting_created = False
        self._session: dict = {}
        self._reader: asyncio.Task | None = None

    async def connect(self, session: dict) -> None:
        self._session = session
        self.ws = await websockets.connect(self.url, additional_headers=self.headers, max_size=None)
        await self.send({"type": "session.update", "session": session})
        self._reader = asyncio.create_task(self._read())

    @property
    def connected(self) -> bool:
        return self.ws is not None and self.ws.state == State.OPEN

    async def ensure_connected(self) -> bool:
        """Reconnect with the same session config if the server closed us (e.g. its 5-minute idle
        timeout while waiting for the presenter). Returns True if a new connection was made."""
        if self.connected:
            return False
        log.warning("realtime %s: reconnecting", self.name)
        self.response_active = self.server_tool_pending = self._pending_commit = self._awaiting_created = False
        self._uncommitted = 0
        await self.connect(self._session)
        return True

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self.ws:
            await self.ws.close()

    async def send(self, event: dict) -> None:
        try:
            await self.ws.send(json.dumps(event))
        except websockets.ConnectionClosed:
            log.warning("realtime %s: dropped %s (connection closed)", self.name, event.get("type"))

    async def append(self, pcm: bytes) -> None:
        self._uncommitted += len(pcm)
        await self.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()})

    async def commit(self) -> str:
        """Commit the presenter's audio so far. Returns "sent", "queued" (sent after the active
        response), "merged" (into a commit already queued, so one transcript covers both) or
        "skipped" (under 100 ms of audio, which the server rejects)."""
        if self.busy:
            merged = self._pending_commit
            self._pending_commit = True
            return "merged" if merged else "queued"
        if self._uncommitted < MIN_COMMIT_BYTES:
            return "skipped"
        await self._send_commit()
        return "sent"

    async def _send_commit(self) -> None:
        self._uncommitted = 0
        await self.send({"type": "input_audio_buffer.commit"})

    async def flush_pending_commit(self) -> None:
        if self._pending_commit and not self.busy:
            self._pending_commit = False
            if self._uncommitted >= MIN_COMMIT_BYTES:
                await self._send_commit()

    def abandon_server_tool(self) -> None:
        """The server's follow-up never came: stop waiting for it."""
        self.server_tool_pending = False

    def abandon_request(self) -> None:
        """Our response.create never started a response: stop counting it as active."""
        if self._awaiting_created:
            self._awaiting_created = False
            self.response_active = False

    @property
    def busy(self) -> bool:
        return self.response_active or self.server_tool_pending

    async def create_response(self, instructions: str | None = None, max_output_tokens: int | None = None) -> bool:
        """None: the session's instructions apply."""
        if self.busy:
            return False
        self.response_active = True
        self._awaiting_created = True
        response: dict = {"instructions": instructions} if instructions else {}
        if max_output_tokens:
            response["max_output_tokens"] = max_output_tokens
        await self.send({"type": "response.create", "response": response})
        return True

    async def cancel(self) -> None:
        if self.response_active:
            await self.send({"type": "response.cancel"})

    async def truncate(self, item_id: str, audio_end_ms: int) -> None:
        await self.send({"type": "conversation.item.truncate", "item_id": item_id, "content_index": 0, "audio_end_ms": audio_end_ms})

    async def add_note(self, text: str) -> None:
        """Context for the examiner that never triggers a reply (K4)."""
        await self.send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})

    async def update_instructions(self, instructions: str, tools: list | None = None) -> None:
        """Mid-session update of instructions (and optionally tools; tools: [] removes web search)."""
        session: dict = {"instructions": instructions}
        if tools is not None:
            session["tools"] = tools
            self._session = {**self._session, "tools": tools}  # a reconnect keeps the change
        await self.send({"type": "session.update", "session": session})

    async def _read(self) -> None:
        try:
            async for message in self.ws:
                event = json.loads(message)
                kind = event["type"]
                self._track(kind, event)
                if kind not in ("response.output_audio.delta", "response.output_text.delta"):
                    self._log(kind, event)
                await self.on_event(kind, event)
        except websockets.ConnectionClosed:
            pass
        # A normal close (code 1000, e.g. the idle timeout) ends the loop without raising.
        close = getattr(self.ws, "close_reason", None) or ""
        log.warning("realtime %s connection closed: %s %s", self.name, getattr(self.ws, "close_code", None), close)
        await self.on_event("connection.closed", {"code": getattr(self.ws, "close_code", None), "reason": close})

    def _track(self, kind: str, event: dict) -> None:
        if kind == "response.created":
            self.response_active = True
            self.server_tool_pending = False
            self._awaiting_created = False
        elif kind == "response.done":
            self.response_active = False
            asyncio.create_task(self.flush_pending_commit())  # waits while a server tool is pending
        elif kind == "conversation.item.added":
            item = event.get("item", {})
            if item.get("type") == "message" and item.get("role") == "assistant":
                self.assistant_item_id = item.get("id")
            elif item.get("type") == "function_call" and item.get("executor") == "server":
                self.server_tool_pending = True
                self.server_tool_since = time.monotonic()
        elif kind == "error" and self._awaiting_created:
            # Our response.create was rejected before it started: don't stay "busy" forever.
            self._awaiting_created = False
            self.response_active = False

    def _log(self, kind: str, event: dict) -> None:
        if kind == "error":
            err = event.get("error", {})
            log.warning("realtime %s error %s: %s", self.name, err.get("type"), err.get("message"))
        elif self.name == "brain":
            return  # the brain's decisions are logged by the exam; its routine events would only add noise
        elif kind == "response.done":
            log.info("response.done status=%s", event.get("response", {}).get("status"))
        elif kind == "conversation.item.added":
            item = event.get("item", {})
            log.info("item added %s/%s%s", item.get("type"), item.get("role") or item.get("name"),
                     f" executor={item.get('executor')}" if item.get("type") == "function_call" else "")
        elif kind in ("session.created", "session.updated"):
            s = event.get("session", {})
            log.info("%s model=%s", kind, s.get("model"))
        elif kind in ("response.created", "input_audio_buffer.committed"):
            log.debug(kind)
