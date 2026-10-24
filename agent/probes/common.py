"""Shared pieces for the headless Realtime probes: config, logging, synthetic speech, event recorder.

Probes stream TTS audio at real-time pace into a Higgs Realtime WebSocket and log one line
per interesting event. Audio payloads are never logged.
"""

import asyncio
import base64
import hashlib
import json
import os
import pathlib
import time

import requests
from dotenv import load_dotenv

HERE = pathlib.Path(__file__).resolve().parent
load_dotenv(HERE.parent.parent / ".env")

MODEL = os.environ.get("BOSON_REALTIME_MODEL", "higgs-realtime-1.5-preview")
REALTIME_URL = os.environ.get("BOSON_REALTIME_URL", "wss://api.boson.ai/v1/realtime")
CAPTION_MODEL = os.environ.get("BOSON_CAPTION_MODEL", "higgs-stt-3.1")
AUTH = {"Authorization": f"Bearer {os.environ['BOSON_API_KEY']}"}
RATE = 24_000
FRAME_BYTES = RATE // 50 * 2  # 20 ms of 16-bit mono PCM
CACHE = HERE / ".cache"

EXAMINER = (
    "You are Dr. Claire Moreau, a rigorous but fair examiner at a project defense. You are the examiner, not an "
    "assistant. Speak in short spoken sentences. Never apologise for asking. Text in square brackets is a context "
    "note from the system, not something the presenter said; never read it aloud."
)

T0 = time.monotonic()


def now() -> float:
    return time.monotonic() - T0


def log(message: str) -> None:
    print(f"{now():7.2f}s  {message}", flush=True)


def tts_pcm(text: str, voice: str = "oliver") -> bytes:
    """Raw 24 kHz 16-bit mono PCM for text from Higgs TTS, cached by voice + text."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{hashlib.sha1((voice + text).encode()).hexdigest()[:16]}.pcm"
    if path.exists():
        return path.read_bytes()
    r = requests.post(
        "https://api.boson.ai/v1/audio/speech",
        headers=AUTH,
        json={"model": "higgs-tts-3", "input": text, "voice": voice, "response_format": "pcm", "stream": True},
        stream=True,
        timeout=120,
    )
    r.raise_for_status()
    pcm = b"".join(r.iter_content(8192))
    path.write_bytes(pcm)
    return pcm


def session_update(instructions: str, turn_detection, tools=None) -> dict:
    session = {
        "model": MODEL,
        "instructions": instructions,
        "audio": {
            "input": {"turn_detection": turn_detection, "transcription": {"model": CAPTION_MODEL}},
            "output": {"voice": "default"},
        },
    }
    if tools is not None:
        session["tools"] = tools
    return {"type": "session.update", "session": session}


class Probe:
    """Sends audio and events on one Realtime WebSocket and records everything it receives."""

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
        log(f"presenter: {label} ({len(pcm) / (RATE * 2):.1f}s)")
        start = time.monotonic()
        for i in range(0, len(pcm), FRAME_BYTES):
            await self.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm[i:i + FRAME_BYTES]).decode()})
            await asyncio.sleep(max(0.0, start + (i + FRAME_BYTES) / (RATE * 2) - time.monotonic()))

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
                self.response_active, self.created_at, self.first_audio_at, self.audio_bytes = True, now(), None, 0
                log("response.created")
            elif kind == "response.done":
                self.response_active = False
                response = event.get("response", {})
                outputs = ",".join(o.get("type", "?") for o in response.get("output", []))
                log(f"response.done status={response.get('status')} audio={self.audio_bytes / (RATE * 2):.1f}s outputs=[{outputs}]")
            elif kind == "conversation.item.input_audio_transcription.completed":
                log(f"TRANSCRIPT: {event.get('transcript', '')!r}")
            elif kind == "response.output_audio_transcript.done":
                log(f"EXAMINER: {event.get('transcript', '')!r}")
            elif kind == "conversation.item.added":
                item = event.get("item", {})
                if item.get("type") == "function_call":
                    log(f"item added: function_call {item.get('name')} executor={item.get('executor')} args={item.get('arguments', '')[:120]}")
                elif item.get("type") == "function_call_output":
                    log(f"item added: function_call_output ({len(item.get('output', ''))} chars)")
                else:
                    log(f"item added: {item.get('type')}/{item.get('role')} id={item.get('id')}")
            elif kind == "conversation.item.truncated":
                log(f"item truncated: {event.get('item_id')} audio_end_ms={event.get('audio_end_ms')}")
            elif kind == "conversation.item.retrieved":
                item = event.get("item", {})
                texts = [c.get("transcript") or c.get("text") for c in item.get("content", [])]
                log(f"item retrieved: {item.get('id')} content={texts!r}")
            elif kind in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped", "input_audio_buffer.committed"):
                log(kind)
            elif kind in ("session.created", "session.updated"):
                session = event.get("session", {})
                log(f"{kind} model={session.get('model')} turn_detection={session.get('audio', {}).get('input', {}).get('turn_detection')} tools={[t.get('type') for t in session.get('tools', []) or []]}")
            elif kind == "error":
                err = event.get("error", {})
                log(f"ERROR {err.get('type')}: {err.get('message')}")

    def seen(self, kind: str, after: float, before: float = 1e9) -> list[dict]:
        return [e for t, e in self.events if e["type"] == kind and after <= t <= before]

    def seen_at(self, kind: str, after: float) -> list[float]:
        return [t for t, e in self.events if e["type"] == kind and t >= after]

    def errors(self, error_type: str, after: float) -> list[dict]:
        return [e for t, e in self.events if t >= after and e["type"] == "error" and e.get("error", {}).get("type") == error_type]

    async def wait_for(self, kind: str, after: float, timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.seen(kind, after)
            if found:
                return found[0]
            await asyncio.sleep(0.05)
        return None


def print_results(results: dict[str, str]) -> None:
    print("\n=== RESULTS ===")
    for name, outcome in results.items():
        print(f"{name:48s} {outcome}")
