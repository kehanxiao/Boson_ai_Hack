"""Session config, slide images and scorecard.

session_id "demo" always works from the demo/ sample files.
POST /api/sessions (upload + prep) arrives in Stage 3.
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Path as PathParam, Request
from fastapi.responses import FileResponse

from config import DATA_DIR, DEMO_DIR

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


@router.get("/{session_id}/scorecard")
def get_scorecard(session_id: str = SessionId) -> dict:
    if session_id == "demo":
        return read_json(DEMO_DIR / "sample-scorecard.json")
    return read_json(DATA_DIR / session_id / "scorecard.json")
