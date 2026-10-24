"""Stage 0 check: a preset Higgs Avatar talking through Higgs Realtime (1.5 preview).

Adapted from Boson's hand-built agent in
docs/vendor/boson/models/higgs-avatar/realtime-sessions.md, with three changes:
config comes from the repo's .env, the browser page and its LiveKit token are
served locally (no LiveKit CLI needed, no token printed), and events are logged
one line each without audio payloads.

    cd agent && uv run stage0_avatar.py
    # then open http://localhost:8765, click Join, and talk
"""

import asyncio
import base64
import json
import os
import pathlib
import time
from datetime import timedelta

import requests
import websockets
from aiohttp import web
from dotenv import load_dotenv
from livekit import api, rtc
from livekit.agents.voice.avatar import DataStreamAudioOutput

HERE = pathlib.Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")

ROOM = os.environ.get("VIVA_TEST_ROOM", "viva-stage0")
AGENT_IDENTITY = "viva-agent"
AVATAR_IDENTITY = "boson-avatar"
PRESENTER_IDENTITY = "presenter"
AVATAR_ID = os.environ.get("VIVA_AVATAR_ID", "builtin_claire_v1")
MODEL = os.environ.get("BOSON_REALTIME_MODEL", "higgs-realtime-1.5-preview")
USE_AVATAR = os.environ.get("VIVA_AVATAR", "1") != "0"
MAX_DURATION_SECONDS = 900
VIEWER_PORT = 8765

BOSON = {"Authorization": f"Bearer {os.environ['BOSON_API_KEY']}"}
BOSON_BASE_URL = os.environ.get("BOSON_BASE_URL", "https://api.boson.ai/v1")
BOSON_REALTIME_URL = os.environ.get("BOSON_REALTIME_URL", "wss://api.boson.ai/v1/realtime")

T0 = time.monotonic()


def log(message: str) -> None:
    print(f"{time.monotonic() - T0:7.2f}s  {message}", flush=True)


def livekit_token(identity, *, publish, subscribe, publish_on_behalf=None, ttl=MAX_DURATION_SECONDS + 300):
    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=ROOM,
                can_publish=publish,
                can_subscribe=subscribe,
                can_publish_data=True,
                can_publish_sources=["camera", "microphone"] if publish else None,
            )
        )
        .with_ttl(timedelta(seconds=ttl))
    )
    if publish_on_behalf:  # LiveKit UIs then show the avatar as part of the agent
        token = token.with_kind("agent").with_attributes({"lk.publish_on_behalf": publish_on_behalf})
    return token.to_jwt()


async def start_viewer() -> web.AppRunner:
    """Serve viewer.html and a presenter token for this room on localhost."""

    async def page(_request):
        return web.FileResponse(HERE / "viewer.html")

    async def token(_request):
        return web.json_response({
            "url": os.environ["LIVEKIT_URL"],
            "token": livekit_token(PRESENTER_IDENTITY, publish=True, subscribe=True, ttl=3600),
        })

    app = web.Application()
    app.router.add_get("/", page)
    app.router.add_get("/token", token)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", VIEWER_PORT).start()
    log(f"viewer ready: http://localhost:{VIEWER_PORT}  (room {ROOM})")
    return runner


def create_avatar_session() -> dict:
    r = requests.post(
        f"{BOSON_BASE_URL}/avatar/sessions",
        headers=BOSON,
        json={
            "avatar_id": AVATAR_ID,
            "transport": {
                "type": "livekit",
                "url": os.environ["LIVEKIT_URL"],
                "room_name": ROOM,
                "participant_token": livekit_token(
                    AVATAR_IDENTITY, publish=True, subscribe=False, publish_on_behalf=AGENT_IDENTITY
                ),
                "participant_identity": AVATAR_IDENTITY,
                "publisher_identity": AGENT_IDENTITY,
            },
            "max_duration_seconds": MAX_DURATION_SECONDS,
        },
        timeout=60,
    )
    if not r.ok:
        raise SystemExit(f"avatar session failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


async def main() -> None:
    viewer = await start_viewer()
    session = None
    if USE_AVATAR:
        session = create_avatar_session()
        log(f"avatar session {session['id']} {session['status']} ({AVATAR_ID})")
    else:
        log("VIVA_AVATAR=0: no avatar (this check needs the avatar to be audible)")

    room = rtc.Room()
    await room.connect(os.environ["LIVEKIT_URL"], livekit_token(AGENT_IDENTITY, publish=True, subscribe=True))
    log(f"agent joined room {ROOM}")
    to_avatar = DataStreamAudioOutput(
        room, destination_identity=AVATAR_IDENTITY, sample_rate=24000, wait_remote_track=rtc.TrackKind.KIND_AUDIO
    )

    try:
        async with websockets.connect(BOSON_REALTIME_URL, additional_headers=BOSON) as ws:
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "model": MODEL,
                    "instructions": "You are a friendly examiner with a face. Keep every answer to one short sentence.",
                    "audio": {
                        "input": {
                            "turn_detection": {"type": "server_vad"},
                            "transcription": {"model": os.environ.get("BOSON_CAPTION_MODEL", "higgs-stt-3.1")},
                        },
                        "output": {"voice": os.environ.get("BOSON_VOICE", "default")},
                    },
                },
            }))

            async def forward_user_audio(track, identity):
                log(f"forwarding microphone of {identity}")
                async for event in rtc.AudioStream(track, sample_rate=24000, num_channels=1):
                    try:
                        await ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(bytes(event.frame.data)).decode(),
                        }))
                    except websockets.ConnectionClosed:
                        return

            @room.on("track_subscribed")
            def on_track(track, _publication, participant):
                if participant.identity != AVATAR_IDENTITY and track.kind == rtc.TrackKind.KIND_AUDIO:
                    asyncio.create_task(forward_user_audio(track, participant.identity))

            for participant in room.remote_participants.values():
                for publication in participant.track_publications.values():
                    if publication.track is not None:
                        on_track(publication.track, publication, participant)

            speaking = False
            speech_stopped_at = None
            first_audio_logged = False
            audio_chunks = 0

            @to_avatar.on("playback_finished")
            def on_played(_event):
                nonlocal speaking
                speaking = False
                log("avatar playback finished")

            async for message in ws:
                event = json.loads(message)
                kind = event["type"]
                if kind == "response.output_audio.delta":
                    pcm = base64.b64decode(event["delta"])
                    await to_avatar.capture_frame(rtc.AudioFrame(pcm, 24000, 1, len(pcm) // 2))
                    speaking = True
                    audio_chunks += 1
                    if not first_audio_logged:
                        first_audio_logged = True
                        if speech_stopped_at is not None:
                            log(f"LATENCY end of user speech -> first audio: {(time.monotonic() - speech_stopped_at) * 1000:.0f} ms")
                elif kind == "response.created":
                    first_audio_logged, audio_chunks = False, 0
                    log("response.created")
                elif kind == "response.done":
                    if USE_AVATAR:
                        to_avatar.flush()
                    status = event.get("response", {}).get("status")
                    log(f"response.done status={status} audio_chunks={audio_chunks}")
                elif kind == "input_audio_buffer.speech_started":
                    log("user speech started" + (" (barge-in: clearing avatar)" if speaking else ""))
                    if speaking:
                        to_avatar.clear_buffer()
                        speaking = False
                elif kind == "input_audio_buffer.speech_stopped":
                    speech_stopped_at = time.monotonic()
                    log("user speech stopped")
                elif kind == "conversation.item.input_audio_transcription.completed":
                    log(f"USER: {event.get('transcript', '')}")
                elif kind == "response.output_audio_transcript.done":
                    log(f"AVATAR: {event.get('transcript', '')}")
                elif kind in ("session.created", "session.updated"):
                    log(f"{kind} model={event.get('session', {}).get('model')}")
                elif kind == "error":
                    err = event.get("error", {})
                    log(f"ERROR {err.get('type')}: {err.get('message')}")
    finally:
        if session:
            requests.delete(f"{BOSON_BASE_URL}/avatar/sessions/{session['id']}", headers=BOSON, timeout=30)
            log("avatar session released")
        await room.disconnect()
        await viewer.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
