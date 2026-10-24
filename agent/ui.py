"""Publishers for viva.ui messages (contract in PLAN.md)."""

import json
import logging

log = logging.getLogger("viva.ui")


class LiveKitUI:
    def __init__(self, room):
        self.room = room

    async def publish(self, msg: dict) -> None:
        try:
            await self.room.local_participant.send_text(json.dumps(msg, ensure_ascii=False), topic="viva.ui")
        except Exception as exc:  # the UI is best-effort; never break the exam over it
            log.warning("viva.ui send failed: %s", exc)


class PrintUI:
    """For headless simulation: print each viva.ui message on one line."""

    def __init__(self, clock):
        self.clock = clock

    async def publish(self, msg: dict) -> None:
        print(f"{self.clock():7.2f}s  UI {json.dumps(msg, ensure_ascii=False)}", flush=True)
