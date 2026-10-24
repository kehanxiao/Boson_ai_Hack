"""Start the examiner agent for a session automatically.

When the Session page asks for a presenter token and the session's LiveKit room has no agent (and none started here
is still starting), the server runs `uv run main.py <room>` in agent/. That agent leaves as soon as the presenter does
(or after VIVA_AGENT_IDLE_EXIT_S, default 300 s, if none ever joins), which frees its avatar slot at once; the next
visit starts a fresh one. Before this, every new upload (and every agent that had been stopped) left the page waiting for an agent
that nobody had started.

VIVA_AUTOSTART_AGENT=0 turns this off, e.g. to run the agent by hand or on another machine.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from livekit import api

from config import env

log = logging.getLogger("viva.agent_launcher")

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
AGENT_IDENTITY = "viva-agent"  # contract: PLAN.md "Interfaces between A and B"

_started: dict[str, subprocess.Popen] = {}  # room -> the agent process started for it
# One request at a time: the Session page asks twice on load (React runs its effect twice in development), and two
# requests that both checked before either started an agent started two. They joined as the same identity, LiveKit
# dropped one mid-sentence, and each held an avatar slot until Boson ran out of them (live, Sat 12:35).
_lock = asyncio.Lock()


def enabled() -> bool:
    return env("VIVA_AUTOSTART_AGENT", "1") != "0"


async def agent_in_room(room: str) -> bool:
    """An agent is already there (started by hand, or before this server restarted)."""
    lk = api.LiveKitAPI(env("LIVEKIT_URL"), env("LIVEKIT_API_KEY"), env("LIVEKIT_API_SECRET"))
    try:
        res = await lk.room.list_participants(api.ListParticipantsRequest(room=room))
        return any(p.identity == AGENT_IDENTITY for p in res.participants)
    except Exception:
        return False  # the room doesn't exist yet
    finally:
        await lk.aclose()


async def ensure_agent(room: str) -> None:
    async with _lock:
        await _ensure(room)


async def _ensure(room: str) -> None:
    proc = _started.get(room)
    if not enabled() or (proc and proc.poll() is None) or await agent_in_room(room):
        return
    uv = os.environ.get("UV") or shutil.which("uv")  # `uv run` sets UV to its own path
    cmd = [uv, "run", "main.py", room] if uv else [sys.executable, "-m", "uv", "run", "main.py", room]
    logs = AGENT_DIR / "runs"
    logs.mkdir(exist_ok=True)
    out = open(logs / f"agent-{room}-{time.strftime('%Y%m%d-%H%M%S')}.log", "w", encoding="utf-8")
    child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
                 "VIVA_AGENT_IDLE_EXIT_S": env("VIVA_AGENT_IDLE_EXIT_S", "300")}
    child_env.pop("VIRTUAL_ENV", None)  # the server's venv; the agent runs in its own
    _started[room] = subprocess.Popen(cmd, cwd=AGENT_DIR, stdout=out, stderr=subprocess.STDOUT, env=child_env)
    out.close()  # the child keeps its own handle
    log.info("started the agent for room %s (pid %d), log in agent/runs/", room, _started[room].pid)
