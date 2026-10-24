"""Kill tests K1, K2 and K4: manual turn control on Higgs Realtime. No LiveKit, no avatar, no human.

A synthetic presenter (Higgs TTS, cached under probes/.cache/) talks into a Realtime
session that has turn_detection: null, and the probe checks:

  K4   a slide note sent as conversation.item.create triggers no response
  K1   input_audio_buffer.commit yields a transcript and no automatic response
  K2   response.create while the presenter is still talking makes the examiner speak;
       audio keeps streaming in, the response is not cancelled; latency is measured
  K2b  commit during an active response is rejected (voice_output_task_ongoing)
  K1b  after response.done, a commit of the audio spoken meanwhile is accepted

    cd agent && uv run probes/manual_turns.py
"""

import asyncio
import base64
import hashlib
import json
import os
import pathlib
import time

import requests
import websockets
from dotenv import load_dotenv

HERE = pathlib.Path(__file__).resolve().parent
load_dotenv(HERE.parent.parent / ".env")

MODEL = os.environ.get("BOSON_REALTIME_MODEL", "higgs-realtime-1.5-preview")
REALTIME_URL = os.environ.get("BOSON_REALTIME_URL", "wss://api.boson.ai/v1/realtime")
AUTH = {"Authorization": f"Bearer {os.environ['BOSON_API_KEY']}"}
RATE = 24_000
FRAME_BYTES = RATE // 50 * 2  # 20 ms of 16-bit mono PCM
CACHE = HERE / ".cache"

PRESENTER_VOICE = "oliver"
SEG_INTRO = "Hi everyone. Today I'm presenting ERwait, a system for forecasting emergency room wait times."
SEG_CLAIM = "And the headline result: our model is forty percent better, which is a big step forward for the hospital."
SEG_CONTINUE = (
    "Now let me walk you through the data. We used two years of triage records, about one point two million "
    "visits, and we removed the outliers before training. We also added weather and holiday features, and we "
    "split the data by time so that the model never sees the future."
)

EXAMINER = (
    "You are Dr. Claire Moreau, a rigorous but fair examiner at a project defense. You are the examiner, not an "
    "assistant. Speak in short spoken sentences. Never apologise for asking. Text in square brackets is a context "
    "note from the system, not something the presenter said; never read it aloud."
)
CUE = (
    EXAMINER + " Interject now, while the presenter is mid-flow. In one short sentence, cut in and ask what the "
    "forty percent is relative to and on which metric."
)

T0 = time.monotonic()


def now() -> float:
    return time.monotonic() - T0


def log(message: str) -> None:
    print(f"{now():7.2f}s  {message}", flush=True)


def tts_pcm(text: str) -> bytes:
    """Raw 24 kHz 16-bit mono PCM for text, cached by content."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{hashlib.sha1((PRESENTER_VOICE + text).encode()).hexdigest()[:16]}.pcm"
    if path.exists():
        return path.read_bytes()
    r = requests.post(
        "https://api.boson.ai/v1/audio/speech",
        headers=AUTH,
        json={"model": "higgs-tts-3", "input": text, "voice": PRESENTER_VOICE, "response_format": "pcm", "stream": True},
        stream=True,
        timeout=120,
    )
    r.raise_for_status()
    pcm = b"".join(r.iter_content(8192))
    path.write_bytes(pcm)
    return pcm


class Probe:
    def __init__(self, ws):
        self.ws = ws
        self.events: list[tuple[float, dict]] = []
        self.response_active = False
        self.audio_bytes = 0
        self.first_audio_at: float | None = None
        self.created_at: float | None = None

    async def send(self, event: dict) -> None:
        await self.ws.send(json.dumps(event))

    async def stream(self, pcm: bytes, label: str) -> None:
        """Send PCM at real-time pace, like a microphone would."""
        log(f"presenter speaking: {label} ({len(pcm) / (RATE * 2):.1f}s)")
        start = time.monotonic()
        for i in range(0, len(pcm), FRAME_BYTES):
            await self.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm[i:i + FRAME_BYTES]).decode()})
            target = start + (i + FRAME_BYTES) / (RATE * 2)
            await asyncio.sleep(max(0.0, target - time.monotonic()))

    async def silence(self, seconds: float) -> None:
        await self.stream(b"\x00\x00" * int(RATE * seconds), f"silence {seconds}s")

    async def receive(self) -> None:
        async for message in self.ws:
            event = json.loads(message)
            kind = event["type"]
            self.events.append((now(), event))
            if kind == "response.output_audio.delta":
                self.audio_bytes += len(event.get("delta", "")) * 3 // 4
                if self.first_audio_at is None:
                    self.first_audio_at = now()
                continue  # never log audio
            if kind == "response.created":
                self.response_active = True
                self.created_at = now()
                self.first_audio_at = None
                self.audio_bytes = 0
                log("response.created")
            elif kind == "response.done":
                self.response_active = False
                status = event.get("response", {}).get("status")
                log(f"response.done status={status} audio={self.audio_bytes / (RATE * 2):.1f}s")
            elif kind == "conversation.item.input_audio_transcription.completed":
                log(f"TRANSCRIPT: {event.get('transcript', '')!r}")
            elif kind == "response.output_audio_transcript.done":
                log(f"EXAMINER: {event.get('transcript', '')!r}")
            elif kind == "error":
                err = event.get("error", {})
                log(f"ERROR {err.get('type')}: {err.get('message')}")
            elif kind in ("session.created", "session.updated", "input_audio_buffer.committed", "conversation.item.added"):
                extra = ""
                if kind.startswith("session"):
                    extra = f" model={event.get('session', {}).get('model')} turn_detection={event.get('session', {}).get('audio', {}).get('input', {}).get('turn_detection')}"
                elif kind == "conversation.item.added":
                    item = event.get("item", {})
                    extra = f" {item.get('type')}/{item.get('role')}"
                log(kind + extra)

    def seen(self, kind: str, after: float, before: float = 1e9, **match) -> list[dict]:
        out = []
        for t, e in self.events:
            if e["type"] == kind and after <= t <= before and all(e.get(k) == v for k, v in match.items()):
                out.append(e)
        return out

    def errors(self, error_type: str, after: float) -> list[dict]:
        return [e for t, e in self.events if t >= after and e["type"] == "error" and e.get("error", {}).get("type") == error_type]


async def main() -> None:
    log("generating presenter audio (cached after the first run)")
    intro, claim, cont = tts_pcm(SEG_INTRO), tts_pcm(SEG_CLAIM), tts_pcm(SEG_CONTINUE)
    results: dict[str, str] = {}

    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws:
        probe = Probe(ws)
        receiver = asyncio.create_task(probe.receive())
        await probe.send({
            "type": "session.update",
            "session": {
                "model": MODEL,
                "instructions": EXAMINER + " During the presentation, stay silent unless you are explicitly asked to respond.",
                "audio": {
                    "input": {"turn_detection": None, "transcription": {"model": os.environ.get("BOSON_CAPTION_MODEL", "higgs-stt-3.1")}},
                    "output": {"voice": "default"},
                },
            },
        })
        await asyncio.sleep(1.5)

        # K4: a slide note is context only.
        t = now()
        await probe.send({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "[Context note: the presenter is now on slide 3, which claims the model is 40% better with no baseline or metric.]"}]}})
        await asyncio.sleep(3)
        results["K4 slide note triggers no response"] = "PASS" if not probe.seen("response.created", t) else "FAIL (a response was generated)"

        # K1: commit yields a transcript and no automatic response.
        await probe.stream(intro, "intro")
        await probe.silence(0.6)
        t = now()
        await probe.send({"type": "input_audio_buffer.commit"})
        log("commit (intro)")
        await probe.silence(4.0)  # keep the mic 'open' with silence, like a live presenter pausing
        got_transcript = bool(probe.seen("conversation.item.input_audio_transcription.completed", t))
        auto_response = bool(probe.seen("response.created", t))
        results["K1 commit -> transcript, no auto-response"] = (
            "PASS" if got_transcript and not auto_response
            else f"FAIL (transcript={got_transcript}, auto_response={auto_response})"
        )

        # K2: the presenter makes the claim and keeps talking; we trigger an interjection mid-flow.
        await probe.stream(claim, "claim")
        await probe.send({"type": "input_audio_buffer.commit"})
        log("commit (claim)")
        cont_task = asyncio.create_task(probe.stream(cont, "presenter keeps talking"))
        await asyncio.sleep(0.4)
        t_create = now()
        await probe.send({"type": "response.create", "response": {"instructions": CUE}})
        log("response.create (director cue) while the presenter is still talking")

        # K2b: a commit during the active response should be rejected.
        for _ in range(60):
            if probe.response_active:
                break
            await asyncio.sleep(0.05)
        t_commit_during = now()
        await probe.send({"type": "input_audio_buffer.commit"})
        log("commit during the active response (expect rejection)")

        await cont_task
        for _ in range(200):
            if probe.seen("response.done", t_create):
                break
            await asyncio.sleep(0.1)
        done = probe.seen("response.done", t_create)
        status = done[0].get("response", {}).get("status") if done else None
        spoke = probe.first_audio_at is not None and probe.audio_bytes > 0
        lat_created = (probe.created_at - t_create) * 1000 if probe.created_at else None
        lat_audio = (probe.first_audio_at - t_create) * 1000 if probe.first_audio_at else None
        results["K2 interjection while presenter talks"] = (
            f"PASS (status={status}, response.created +{lat_created:.0f} ms, first audio +{lat_audio:.0f} ms, "
            f"spoke {probe.audio_bytes / (RATE * 2):.1f}s)" if spoke and status == "completed"
            else f"FAIL (spoke={spoke}, status={status})"
        )
        rejected = probe.errors("voice_output_task_ongoing", t_commit_during)
        results["K2b commit during response is rejected"] = "PASS (as documented)" if rejected else "NOT REJECTED (commit accepted mid-response)"

        # K1b: after the response, the audio spoken meanwhile can be committed.
        t = now()
        await probe.send({"type": "input_audio_buffer.commit"})
        log("commit after response.done")
        await probe.silence(4.0)
        results["K1b commit after response is accepted"] = (
            "PASS" if probe.seen("conversation.item.input_audio_transcription.completed", t) and not probe.errors("voice_output_task_ongoing", t)
            else "FAIL (no transcript or rejected)"
        )
        receiver.cancel()

    print("\n=== RESULTS ===")
    for name, outcome in results.items():
        print(f"{name:45s} {outcome}")


if __name__ == "__main__":
    asyncio.run(main())
