"""Session config, slide images, log upload and scorecard.

session_id "demo" always works from the demo/ sample files.
Creating a session (upload + prep) lives in session_create.py.
"""

import asyncio
import json
from pathlib import Path

import anthropic
from fastapi import APIRouter, HTTPException, Path as PathParam, Request
from fastapi.responses import FileResponse

from config import DATA_DIR, DEMO_DIR
from scorecard import ScorecardError, generate_scorecard, read_log

router = APIRouter(prefix="/api/sessions")

SessionId = PathParam(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


def read_json(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(404, f"{path.name} not found")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/{session_id}")
def get_session(session_id: str = SessionId) -> dict:
    if session_id == "demo":
        return read_json(DEMO_DIR / "session-config.json")
    return read_json(DATA_DIR / session_id / "config.json")


@router.get("/{session_id}/slides/{n}.png")
def get_slide(n: int, session_id: str = SessionId) -> FileResponse:
    path = DATA_DIR / session_id / "slides" / f"{n}.png"
    if not path.exists():
        raise HTTPException(404, "slide not rendered")
    return FileResponse(path, media_type="image/png")


MAX_LOG_BYTES = 5 * 1024 * 1024


@router.post("/{session_id}/log")
async def upload_log(request: Request, session_id: str = SessionId) -> dict:
    """Raw JSONL body (application/x-ndjson), one log object per line, sample-log.jsonl format."""
    body = await request.body()
    if len(body) > MAX_LOG_BYTES:
        raise HTTPException(413, "log too large")
    try:
        lines = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise HTTPException(400, f"body must be JSONL: {err}") from err
    if not all(isinstance(e, dict) and "t" in e and "kind" in e for e in lines):
        raise HTTPException(400, "every line must be an object with 't' and 'kind'")

    session_dir = DATA_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in lines)
    (session_dir / "log.jsonl").write_text(text, encoding="utf-8")
    (session_dir / "scorecard.json").unlink(missing_ok=True)  # stale: built from the old log
    return {"ok": True, "lines": len(lines)}


_scorecard_locks: dict[str, asyncio.Lock] = {}


@router.get("/{session_id}/scorecard")
async def get_scorecard(session_id: str = SessionId) -> dict:
    """Generated on first request from log.jsonl + config.json (~15-20 s), then cached to disk."""
    if session_id == "demo":
        return read_json(DEMO_DIR / "sample-scorecard.json")
    session_dir = DATA_DIR / session_id
    cached = session_dir / "scorecard.json"
    async with _scorecard_locks.setdefault(session_id, asyncio.Lock()):  # one generation per session
        if cached.exists():
            return read_json(cached)
        config = read_json(session_dir / "config.json")
        if not (session_dir / "log.jsonl").exists():
            raise HTTPException(404, "no session log yet: the agent uploads it when the session ends")
        log = read_log((session_dir / "log.jsonl").read_text(encoding="utf-8"))
        try:
            card = await generate_scorecard(log, config)
        except (ScorecardError, anthropic.APIError) as err:
            raise HTTPException(502, f"scorecard generation failed, try again: {err}") from err
        cached.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return card
