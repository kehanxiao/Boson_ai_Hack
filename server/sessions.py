"""Session config, slide images and scorecard.

session_id "demo" always works from the demo/ sample files.
POST /api/sessions (upload + prep) and POST /log arrive in Stage 3.
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Path as PathParam
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


@router.get("/{session_id}/scorecard")
def get_scorecard(session_id: str = SessionId) -> dict:
    if session_id == "demo":
        return read_json(DEMO_DIR / "sample-scorecard.json")
    return read_json(DATA_DIR / session_id / "scorecard.json")
