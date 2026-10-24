"""Viva server. Run: uv run uvicorn main:app --reload --port 8000"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import livekit_token
import sessions
from config import DATA_DIR, DEMO_DIR, WEB_ORIGINS
from render import is_stale, render_deck


def render_demo_deck() -> None:
    """Keep data/demo/ in sync with demo/deck.pdf so session "demo" always has slides."""
    pdf, out = DEMO_DIR / "deck.pdf", DATA_DIR / "demo"
    if pdf.exists() and is_stale(pdf, out):
        render_deck(pdf, out)


@asynccontextmanager
async def lifespan(_: FastAPI):
    render_demo_deck()
    yield


app = FastAPI(title="Viva server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=WEB_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(livekit_token.router)
app.include_router(sessions.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True}
