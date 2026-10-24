"""Viva server. Run: uv run uvicorn main:app --port 8000"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import livekit_token
import session_create
import sessions
from config import WEB_ORIGINS
from fixed_sessions import render_fixed_decks


@asynccontextmanager
async def lifespan(_: FastAPI):
    render_fixed_decks()  # slides for the built-in "demo" and "gradebook" sessions
    yield


app = FastAPI(title="Viva server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=WEB_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(livekit_token.router)
app.include_router(session_create.router)
app.include_router(sessions.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True}
