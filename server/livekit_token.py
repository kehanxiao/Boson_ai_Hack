"""GET /token?room=&identity= -> {url, token} (contract: PLAN.md, Interfaces between A and B).

A presenter token also makes sure the room has an examiner agent (agent_launcher.py)."""

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query
from livekit import api

import agent_launcher
from config import env

router = APIRouter()

NAME_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"


@router.get("/token")
async def get_token(
    room: str = Query(..., pattern=NAME_PATTERN),
    identity: str = Query(..., pattern=NAME_PATTERN),
) -> dict:
    url, key, secret = env("LIVEKIT_URL"), env("LIVEKIT_API_KEY"), env("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        raise HTTPException(500, "LiveKit is not configured: set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET")
    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    token = (
        api.AccessToken(key, secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
        .with_ttl(timedelta(hours=2))
        .to_jwt()
    )
    if identity == "presenter":
        await agent_launcher.ensure_agent(room)
    return {"url": url, "token": token}
