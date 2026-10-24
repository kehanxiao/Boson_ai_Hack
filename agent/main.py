"""Viva examiner agent: joins a session's LiveKit room with a Higgs Avatar and runs the exam.

    cd agent && uv run main.py [session_id]        # default session: demo
    VIVA_AVATAR=0 uv run main.py demo              # voice-only fallback (no avatar slot used)

The browser (web/) joins the same room as "presenter" and sends viva.ctl messages; the
SessionConfig comes from the server (server/), or from demo/ for the fixed demo sessions
when the server is not running. Two Higgs Realtime sessions hear the presenter: the brain
decides (brain.py), the voice speaks through the avatar.
"""

import argparse
import asyncio
import json
import logging
import os
import pathlib
import time
from datetime import timedelta

import requests
from dotenv import load_dotenv
from livekit import api, rtc

HERE = pathlib.Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")

import instructions as prompts  # noqa: E402  (needs .env loaded first for the model names)
from brain import Brain  # noqa: E402
from exam import ExamController  # noqa: E402
from output import AvatarOutput, VoiceOutput  # noqa: E402
from realtime import RealtimeClient  # noqa: E402
from session_log import SessionLog  # noqa: E402
from ui import LiveKitUI  # noqa: E402

AGENT_IDENTITY = "viva-agent"
AVATAR_IDENTITY = "boson-avatar"
PRESENTER_IDENTITY = "presenter"
MAX_DURATION_S = 3600  # the account limit: the avatar leaves after this, so restart the agent for long sessions
DUPLICATE_START_S = 10  # a start this soon after the exam began is the web's retransmission

BOSON_KEY = os.environ["BOSON_API_KEY"]
BRAIN_KEY = os.environ.get("BOSON_BRAIN_API_KEY") or BOSON_KEY  # a second key may avoid cross-session delays
BOSON_BASE = os.environ.get("BOSON_BASE_URL", "https://api.boson.ai/v1")
BOSON_AUTH = {"Authorization": f"Bearer {BOSON_KEY}"}
REALTIME_URL = os.environ.get("BOSON_REALTIME_URL", "wss://api.boson.ai/v1/realtime")
MODEL = os.environ.get("BOSON_REALTIME_MODEL", "higgs-realtime-1.5-preview")
SERVER = os.environ.get("VIVA_SERVER_URL", "http://localhost:8000")
USE_AVATAR = os.environ.get("VIVA_AVATAR", "1") != "0"
FACTCHECK = os.environ.get("VIVA_FACTCHECK", "1") != "0"

log = logging.getLogger("viva")


# Fixed demo sessions that work from demo/ files even without the server.
DEMO_SESSIONS = {"demo": "session-config.json", "gradebook": "session-config-coding.json",
                 "demo3": "session-config-demo3.json"}


def load_config(session_id: str) -> dict:
    try:
        r = requests.get(f"{SERVER}/api/sessions/{session_id}", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        fallback = HERE.parent / "demo" / DEMO_SESSIONS.get(session_id, "")
        if session_id not in DEMO_SESSIONS or not fallback.exists():
            raise SystemExit(f"cannot load session {session_id} from {SERVER}: {exc}")
        log.warning("server unavailable (%s); using %s", exc, fallback.name)
        return json.loads(fallback.read_text(encoding="utf-8"))


def livekit_token(room: str, identity: str, *, publish_on_behalf: str | None = None, subscribe=True) -> str:
    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=subscribe,
                                     can_publish_data=True, can_publish_sources=["camera", "microphone"]))
        .with_ttl(timedelta(seconds=MAX_DURATION_S + 300))
    )
    if publish_on_behalf:
        token = token.with_kind("agent").with_attributes({"lk.publish_on_behalf": publish_on_behalf})
    return token.to_jwt()


def create_avatar(room: str, avatar_id: str) -> dict:
    body = {
        "avatar_id": avatar_id,
        "transport": {
            "type": "livekit",
            "url": os.environ["LIVEKIT_URL"],
            "room_name": room,
            "participant_token": livekit_token(room, AVATAR_IDENTITY, publish_on_behalf=AGENT_IDENTITY, subscribe=False),
            "participant_identity": AVATAR_IDENTITY,
            "publisher_identity": AGENT_IDENTITY,
        },
        "max_duration_seconds": MAX_DURATION_S,
    }
    for attempt in range(3):
        r = requests.post(f"{BOSON_BASE}/avatar/sessions", headers=BOSON_AUTH, json=body, timeout=60)
        if r.ok:
            return r.json()
        if r.status_code == 429 and attempt < 2:
            wait = int(r.headers.get("Retry-After", "5") or 5)
            log.warning("avatar: HTTP 429 %s; retrying in %ss", r.json().get("error", {}).get("code"), wait)
            time.sleep(min(wait, 20))
            continue
        raise SystemExit(f"avatar session failed: HTTP {r.status_code} {r.text[:300]}  (try VIVA_AVATAR=0)")
    raise SystemExit("avatar session failed after retries (try VIVA_AVATAR=0)")


def release_avatar(session_id: str) -> None:
    """DELETE can be rate-limited (Stage 0 finding): retry, honouring Retry-After."""
    for _ in range(6):
        try:
            r = requests.delete(f"{BOSON_BASE}/avatar/sessions/{session_id}", headers=BOSON_AUTH, timeout=30)
        except requests.RequestException as exc:
            log.warning("avatar release failed: %s", exc)
            time.sleep(3)
            continue
        if r.ok or r.status_code == 404:
            log.info("avatar session released")
            return
        time.sleep(min(int(r.headers.get("Retry-After", "5") or 5), 15))
    log.error("could not release avatar session %s; it ends at max_duration or when the room empties", session_id)


# The preset avatar's voice when the character has none: "default" is a female voice, which the male avatar
# (The Skeptic) was speaking with (live run, Sat 09:30). marcus is a male Higgs TTS preset.
AVATAR_VOICES = {"builtin_james_v1": "marcus"}


def voice_for(character: dict) -> str:
    voice = character.get("voice") or "default"
    return AVATAR_VOICES.get(character.get("avatar_id", ""), voice) if voice == "default" else voice


def realtime_session(config: dict) -> dict:
    session = {
        "model": MODEL,
        "instructions": prompts.for_phase(config, "presentation"),
        "audio": {
            "input": {
                "turn_detection": None,  # fixed for the whole session (K5): we own turn-taking
                "transcription": {"model": os.environ.get("BOSON_CAPTION_MODEL", "higgs-stt-3.1")},
            },
            "output": {"voice": voice_for(config["character"])},
        },
        # Also caps the server's own follow-up after a web search, which ignores our per-response caps
        # (at 220 a fact-check answer ran ~18 s in the sim).
        "max_output_tokens": 120,
    }
    if FACTCHECK:
        session["tools"] = [{"type": "web_search"}]
    return session


def brain_session(config: dict) -> dict:
    """Text only, manual turns, no transcription: it listens to the audio itself (the voice session's
    transcripts are the captions)."""
    return {
        "model": MODEL,
        "instructions": prompts.brain(config, "presentation"),
        "output_modalities": ["text"],
        "audio": {"input": {"turn_detection": None}},
        "max_output_tokens": 100,
    }


async def run(session_id: str) -> None:
    config = load_config(session_id)
    room_name = config.get("session_id", session_id)

    avatar = create_avatar(room_name, config["character"].get("avatar_id", "builtin_claire_v1")) if USE_AVATAR else None
    if avatar:
        log.info("avatar session %s %s", avatar["id"], avatar["status"])

    room = rtc.Room()
    realtime: RealtimeClient | None = None
    brain: Brain | None = None
    current: ExamController | None = None  # the exam in progress, or the next one waiting for Start
    try:
        await room.connect(os.environ["LIVEKIT_URL"], livekit_token(room_name, AGENT_IDENTITY))
        log.info("agent joined room %s (avatar=%s)", room_name, USE_AVATAR)
        if USE_AVATAR:
            output = AvatarOutput(room, AVATAR_IDENTITY)
        else:
            output = VoiceOutput(room)
            await output.start()

        async def on_event(kind, event):
            if current:
                await current.on_realtime_event(kind, event)

        async def on_decision(decision):
            if current:
                await current.on_brain_decision(decision)

        async def on_brain_closed():
            if current:
                await current.on_brain_closed()

        realtime = RealtimeClient(REALTIME_URL, BOSON_KEY, on_event)
        brain = Brain(REALTIME_URL, BRAIN_KEY, on_decision, on_brain_closed)

        def new_exam() -> ExamController:
            slog = SessionLog(HERE / "runs" / f"{room_name}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
            return ExamController(config, realtime, output, LiveKitUI(room), slog, brain, factcheck=FACTCHECK)

        current = new_exam()
        await realtime.connect(realtime_session(config))
        await brain.connect(brain_session(config))

        async def reset(reason: str) -> None:
            """Abort the exam in progress and get a fresh one ready (new Higgs conversation, new log)."""
            nonlocal current
            if current is None or current.phase == "waiting":
                return
            log.info("resetting the exam: %s", reason)
            old = current
            await old.abort()
            await old.aclose()
            await realtime.close()  # the next Start reconnects both with empty conversations
            await brain.close()
            current = new_exam()

        async def forward(track):
            try:
                async for event in rtc.AudioStream(track, sample_rate=24000, num_channels=1):
                    if current:
                        await current.on_presenter_audio(event.frame)
            except Exception:
                log.exception("presenter audio forwarding stopped")

        @room.on("track_subscribed")
        def on_track(track, _publication, participant):
            if participant.identity not in (AVATAR_IDENTITY, AGENT_IDENTITY) and track.kind == rtc.TrackKind.KIND_AUDIO:
                log.info("listening to %s", participant.identity)
                asyncio.create_task(forward(track))

        @room.on("participant_disconnected")
        def on_left(participant):
            if participant.identity not in (AVATAR_IDENTITY, AGENT_IDENTITY):
                asyncio.create_task(reset(f"{participant.identity} left the room"))

        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.track is not None:
                    on_track(publication.track, publication, participant)

        async def read_ctl(reader, _identity):
            try:
                msg = json.loads(await reader.read_all())
                if msg.get("type") == "start" and current.phase != "waiting":
                    if current.phase != "ended" and current.elapsed() < DUPLICATE_START_S:
                        return  # the web re-sends start until it hears from us: a duplicate, not a restart
                    await reset("Start pressed again")  # e.g. the page was reloaded
                await current.on_ctl(msg)
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                log.warning("bad viva.ctl message: %s", exc)
            except Exception:
                log.exception("viva.ctl handling failed")

        room.register_text_stream_handler("viva.ctl", lambda reader, identity: asyncio.ensure_future(read_ctl(reader, identity)))
        log.info("ready: waiting for the presenter's {type: start}")

        # One exam after another until Ctrl-C. Only completed exams are uploaded for the scorecard.
        while True:
            exam = current
            await exam.ended.wait()
            if exam.completed:
                await asyncio.sleep(1.0)  # let the last viva.ui messages go out
                exam.slog.upload(SERVER, room_name)
                await exam.aclose()
                await realtime.close()
                await brain.close()
                current = new_exam()
                log.info("exam complete; ready for the next Start")
            else:
                while current is exam:  # aborted: reset() is swapping in the next exam
                    await asyncio.sleep(0.1)
    finally:
        if current:
            await current.aclose()
        if realtime:
            await realtime.close()
        if brain:
            await brain.close()
        if avatar:
            release_avatar(avatar["id"])
        await room.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session_id", nargs="?", default="demo")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("livekit").setLevel(logging.WARNING)
    try:
        asyncio.run(run(args.session_id))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
