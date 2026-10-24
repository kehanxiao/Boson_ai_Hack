"""Live check through LiveKit, headless: a synthetic presenter joins a session's room with the real agent.

Start the agent first (voice-only: VIVA_AVATAR=0 uv run main.py <session_id>). This joins as "presenter",
publishes TTS speech as its microphone, sends viva.ctl start and slide changes, and reports the viva.ui
messages that arrive and whether the examiner's voice (the agent's audio track, or the avatar's) carries
sound. It checks the path the browser uses, without a browser, and measures what a presenter perceives:
the end of their speech -> the first sound of her voice in the room (avatar vs voice-only).

    cd agent && uv run probes/live_room.py <session_id> [--wait-qa]
"""

import asyncio
import json
import os
import pathlib
import sys
import time

import numpy as np
from livekit import rtc

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from common import tts_pcm  # noqa: E402  (loads .env)
from main import AGENT_IDENTITY, AVATAR_IDENTITY, livekit_token  # noqa: E402

RATE, FRAME = 24_000, 480
T0 = time.monotonic()
LINES = [  # (slide, text)
    (1, "Hi, may I start?"),
    (2, "The task had three steps: read a CSV of scores, sort the students from lowest to highest, and print the top twenty."),
    (3, "We wrote our own bubble sort, because bubble sort is the fastest sorting algorithm."),
]


def now() -> float:
    return time.monotonic() - T0


async def main() -> None:
    session_id = sys.argv[1]
    room = rtc.Room()
    ui: list[dict] = []
    voice = {"frames": 0, "loud": 0, "from": set()}
    heard = {"line_end": None, "ms": []}  # the presenter's speech end -> her first sound after it
    sent = {"at": None, "ms": []}  # the agent's first audio (its latency message) -> her first sound here

    def on_ui(reader, identity):
        async def read():
            msg = json.loads(await reader.read_all())
            ui.append(msg)
            if msg.get("type") == "latency" and msg.get("metric") in ("pause_to_interjection", "answer_end_to_reply"):
                sent["at"] = time.monotonic()
            if msg.get("type") in ("caption", "interjection", "reminder", "factcheck", "latency", "ended"):
                detail = msg.get("text") or msg.get("reason") or msg.get("metric") or msg.get("kind") or ""
                print(f"{now():6.1f}s  viva.ui {msg['type']:12s} {msg.get('role', '')[:9]:9s} "
                      f"{str(detail)[:90]} {msg.get('ms', '')}", flush=True)
        asyncio.ensure_future(read())

    room.register_text_stream_handler("viva.ui", on_ui)

    async def listen(track, identity):
        async for event in rtc.AudioStream(track, sample_rate=RATE, num_channels=1):
            samples = np.frombuffer(bytes(event.frame.data), dtype=np.int16)
            voice["frames"] += 1
            if samples.size and np.abs(samples).mean() > 300:
                voice["loud"] += 1
                voice["from"].add(identity)
                if sent["at"] is not None:
                    sent["ms"].append((time.monotonic() - sent["at"]) * 1000)
                    sent["at"] = None
                    print(f"{now():6.1f}s  OUTPUT her first sound {sent['ms'][-1]:.0f} ms after the agent sent it", flush=True)
                if heard["line_end"] is not None:
                    ms = (time.monotonic() - heard["line_end"]) * 1000
                    heard["ms"].append(ms)
                    heard["line_end"] = None
                    print(f"{now():6.1f}s  HEARD her voice {ms:.0f} ms after the presenter stopped", flush=True)

    @room.on("track_subscribed")
    def on_track(track, _pub, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity in (AGENT_IDENTITY, AVATAR_IDENTITY):
            print(f"{now():6.1f}s  hearing {participant.identity}", flush=True)
            asyncio.ensure_future(listen(track, participant.identity))

    await room.connect(os.environ["LIVEKIT_URL"], livekit_token(session_id, "presenter"))
    source = rtc.AudioSource(RATE, 1, queue_size_ms=40)  # small queue: capture_frame returns when the audio is sent
    mic = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    print(f"{now():6.1f}s  joined {session_id} as presenter", flush=True)

    async def speak(pcm: bytes) -> None:
        for i in range(0, len(pcm), FRAME * 2):
            chunk = pcm[i:i + FRAME * 2].ljust(FRAME * 2, bytes(1))
            await source.capture_frame(rtc.AudioFrame(chunk, RATE, 1, FRAME))

    async def silence(seconds: float) -> None:
        await speak(bytes(int(seconds * RATE) * 2))

    async def ctl(msg: dict) -> None:
        await room.local_participant.send_text(json.dumps(msg), topic="viva.ctl")

    await silence(1.0)
    for _ in range(5):  # the web re-sends start until the first viva.ui message
        await ctl({"type": "start"})
        await silence(2.0)
        if ui:
            break
    await silence(4.0)  # her greeting
    for slide, text in LINES:
        await ctl({"type": "slide", "index": slide})
        print(f"{now():6.1f}s  PRESENTER (slide {slide}): {text[:80]}", flush=True)
        await speak(tts_pcm(text))
        heard["line_end"] = time.monotonic()  # capture_frame paces in real time, so this is the end of speech
        await silence(9.0)  # room for her to cut in
    if "--wait-qa" in sys.argv:
        await ctl({"type": "phase", "phase": "qa"})
        await silence(20.0)
    await ctl({"type": "phase", "phase": "end"})
    for _ in range(40):  # the verdict, then "ended"
        await silence(1.0)
        if any(m.get("type") == "ended" for m in ui):
            break
    await room.disconnect()

    kinds = [m.get("type") for m in ui]
    states = sorted({m.get("state") for m in ui if m.get("type") == "state"})
    checks = {
        "start handshake (viva.ui received)": bool(ui),
        "examiner captions": any(m.get("type") == "caption" and m.get("role") == "examiner" for m in ui),
        "presenter captions": any(m.get("type") == "caption" and m.get("role") == "presenter" for m in ui),
        "an interjection": "interjection" in kinds,
        "pause_to_interjection latency": any(m.get("metric") == "pause_to_interjection" for m in ui),
        "examiner audio heard": voice["loud"] > 50,
        "ended": "ended" in kinds,
    }
    print("\n=== RESULTS ===")
    for name, ok in checks.items():
        print(f"{name:38s} {'PASS' if ok else 'FAIL'}")
    print(f"(info) states {states}; audio frames {voice['frames']}, with sound {voice['loud']} from {sorted(voice['from'])}")
    print(f"(info) presenter stops -> her voice heard: {[int(x) for x in heard['ms']]} ms")
    print(f"(info) agent's first audio -> heard here (output path: avatar or voice): {[int(x) for x in sent['ms']]} ms")


if __name__ == "__main__":
    asyncio.run(main())
