"""The examiner's brain: a text-only Higgs Realtime session that hears the presenter and decides.

It gets the same presenter audio as the voice session, committed at the same pauses, plus
[bracketed] notes: the slide showing, what the examiner said that it didn't write itself
(reminders, web-search results), being talked over. When asked, it answers with one line:
    SILENT | SAY: <words> | CHECK: <claim> | END: <words>        (END only in Q&A)
The voice session speaks SAY lines word for word; CHECK runs the voice's server web search.

Why a second session and not the voice deciding itself: an audio response can't be silent,
the voice refuses commits and responses while it speaks or searches, and a judge-only session
keeps her spoken conversation free of dozens of SILENT turns (agent/CLAUDE.md "Higgs brain").

Measured (probes/higgs_brain.py, 3 runs of a 10-chunk talk with 6 planted errors): caught 6/6
every run, 0 malformed answers, median ~0.45 s. The Haiku director it replaces caught 5-6/6
from transcripts at a median ~1.5-1.9 s.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from realtime import RealtimeClient

log = logging.getLogger("viva.brain")

TAGS = ("SILENT", "SAY:", "CHECK:", "END:")
TAG = re.compile(r"\b(SILENT|SAY:|CHECK:|END:)")  # also mid-line: "The answer is END: That's all my questions."
LOOKUP = re.compile(r"\blet me (check|look)", re.I)
STUCK_S = 6  # a decision that never finished is dropped (watchdog)


@dataclass
class Decision:
    action: str  # SILENT | SAY | CHECK | END | INVALID
    text: str
    ms: int
    ctx: dict = field(default_factory=dict)
    raw: str = ""
    item_ids: list[str] = field(default_factory=list)  # its answer in the brain's conversation (to forget it)


def parse(text: str) -> tuple[str, str]:
    """The first tag in the first line and the words after it. No tag: INVALID (treated as silence).
    A SAY that announces a look-up ("Microsoft made it, not Google. Let me check.") is a CHECK: the brain
    sometimes corrects a fact itself instead, and the web search is the point of the moment."""
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    found = TAG.search(line)
    if not found:
        return "INVALID", line
    tag = found.group(1)
    words = line[found.end():].strip().strip('"')
    if tag == "SAY:" and LOOKUP.search(words):
        return "CHECK", words
    return tag.rstrip(":"), words


class Brain:
    def __init__(self, url: str, api_key: str, on_decision: Callable[[Decision], Awaitable[None]],
                 on_closed: Callable[[], Awaitable[None]] | None = None):
        self.rt = RealtimeClient(url, api_key, self._on_event, name="brain")
        self.on_decision = on_decision
        self.on_closed = on_closed
        self._asked: dict | None = None  # the decision in flight
        self._text = ""
        self._marks: list[str] = []  # notes waiting for a commit that was queued behind a decision
        self.last_done = 0.0  # when its last response finished (the voice waits a moment after it: exam.py)

    @property
    def connected(self) -> bool:
        return self.rt.connected

    @property
    def thinking(self) -> bool:
        return self._asked is not None

    async def connect(self, session: dict) -> None:
        await self.rt.connect(session)

    async def ensure_connected(self) -> bool:
        return await self.rt.ensure_connected()

    async def close(self) -> None:
        self._asked = None
        await self.rt.close()

    async def append(self, pcm: bytes) -> None:
        await self.rt.append(pcm)

    async def commit(self) -> None:
        await self.rt.commit()  # queued by the client while a decision is being written

    async def note(self, text: str) -> None:
        if self.connected:
            await self.rt.add_note(text)

    async def mark(self, text: str) -> None:
        """A note at this point of the presenter's audio: commit what was heard so far, then the note, in that
        order. While a decision is being written the commit is queued, so the note waits for it."""
        if not self.connected:
            return
        if self.rt.busy:
            await self.rt.commit()  # queued: sent when the decision is done
            self._marks.append(text)
            return
        await self.rt.commit()
        await self.rt.add_note(text)

    async def update_instructions(self, instructions: str) -> None:
        if self.connected:
            await self.rt.update_instructions(instructions)

    async def ask(self, ctx: dict, instructions: str | None = None, max_tokens: int | None = None) -> bool:
        """Ask for one decision about everything heard so far. False if it is still deciding (or offline)."""
        if not self.connected or self._asked or self.rt.busy:
            return False
        self._asked = {"ctx": ctx, "at": time.monotonic(), "items": []}
        self._text = ""
        if not await self.rt.create_response(instructions, max_tokens):
            self._asked = None
            return False
        return True

    async def forget(self, decision: Decision) -> None:
        """Remove a decision that was never spoken from the brain's conversation. Left in, each blocked repeat
        read as "she said it again", and it kept proposing the same line instead of answering the presenter's
        question (live run, Sat 06:17: the same line ~15 times, "which slide?" six times unanswered)."""
        for item_id in decision.item_ids:
            await self.rt.send({"type": "conversation.item.delete", "item_id": item_id})
        log.info("brain: forgot %d item(s) of an unspoken %s", len(decision.item_ids), decision.action)

    def check_stuck(self) -> None:
        if self._asked and time.monotonic() - self._asked["at"] > STUCK_S:
            log.warning("brain: no decision after %ss; dropping the request", STUCK_S)
            self._asked = None
            self.rt.abandon_request()

    async def _on_event(self, kind: str, event: dict) -> None:
        if kind == "response.output_text.done":
            self._text = event.get("text", "")
        elif kind == "conversation.item.added" and self._asked:
            item = event.get("item", {})
            if item.get("role") == "assistant" and item.get("id"):
                self._asked["items"].append(item["id"])
        elif kind == "response.done":
            self.last_done = time.monotonic()
            asked, self._asked = self._asked, None
            await self.rt.flush_pending_commit()  # audio heard during the decision goes in first
            marks, self._marks = self._marks, []
            for text in marks:
                await self.rt.add_note(text)
            if asked:
                action, text = parse(self._text)
                ms = int((time.monotonic() - asked["at"]) * 1000)
                ids = [o["id"] for o in event.get("response", {}).get("output", []) if o.get("id")]
                ids = list(dict.fromkeys(ids + asked["items"]))
                await self.on_decision(Decision(action, text, ms, asked["ctx"], self._text.strip(), ids))
        elif kind == "error" and self._asked and not self.rt.response_active:
            self._asked = None  # the request was refused before it started
        elif kind == "connection.closed":
            self._asked = None
            if self.on_closed:
                await self.on_closed()
