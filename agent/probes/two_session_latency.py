"""The voice's first audio is ~1.7 s right after a brain decision, ~0.36 s otherwise (voice_latency.py --brain).
What in the brain session holds the voice up? response.create on the voice, then first audio, in four cases:
  base:    brain commit + text response; voice asked at the brain's response.done (what exam.py does)
  commit:  brain commit only (no response); voice asked 0.45 s later
  wait1:   as base, but the voice is asked 1 s after the brain's response.done
  textdone: as base, but the voice is asked at the brain's response.output_text.done
  cancel:  as textdone, after cancelling the brain's response

    cd agent && uv run probes/two_session_latency.py [rounds] [cases...]   (also wait0.2 ... wait0.8)
"""

import asyncio
import base64
import json
import pathlib
import statistics
import sys

import websockets

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from common import AUTH, REALTIME_URL, Probe, now, tts_pcm  # noqa: E402  (loads .env)
import instructions as prompts  # noqa: E402
from main import brain_session, realtime_session  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CONFIG = json.loads((ROOT / "demo" / "session-config-coding.json").read_text(encoding="utf-8"))
SPEECH = "We wrote our own bubble sort, because bubble sort is the fastest sorting algorithm."
LINE = "Hold on. Bubble sort is O of n squared, not the fastest. What makes you say that?"
CASES = ("base", "commit", "wait1", "textdone")
WAITS = {"wait0.2": 0.2, "wait0.4": 0.4, "wait0.6": 0.6, "wait0.8": 0.8, "wait1": 1.0}


async def stream(pcm: bytes, probes: list[Probe]) -> None:
    for i in range(0, len(pcm), 960):
        frame = base64.b64encode(pcm[i:i + 960].ljust(960, bytes(1))).decode()
        for probe in probes:
            await probe.send({"type": "input_audio_buffer.append", "audio": frame})
        await asyncio.sleep(0.02)


async def one(voice: Probe, brain: Probe, case: str) -> tuple[float, float]:
    await stream(tts_pcm(SPEECH) + bytes(24_000), [voice, brain])  # speech + 0.5 s of silence
    await voice.send({"type": "input_audio_buffer.commit"})
    t = now()
    await brain.send({"type": "input_audio_buffer.commit"})
    if case == "commit":
        await asyncio.sleep(0.45)
    else:
        await brain.send({"type": "response.create", "response": {}})
        await brain.wait_for("response.output_text.done" if case in ("textdone", "cancel") else "response.done", t, timeout=10)
        if case == "cancel":
            await brain.send({"type": "response.cancel"})
        if case in WAITS:
            await asyncio.sleep(WAITS[case])
    brain_ms = (now() - t) * 1000
    t0 = now()
    await voice.send({"type": "response.create", "response": {
        "instructions": prompts.with_cue(CONFIG, "presentation", prompts.say_exactly(LINE)), "max_output_tokens": 100}})
    first = await voice.wait_for("response.output_audio.delta", t0, timeout=10)
    ms = (now() - t0) * 1000 if first else -1
    await voice.wait_for("response.done", t0, timeout=15)
    await asyncio.sleep(3.0)  # let both sessions settle before the next case
    return ms, brain_ms


async def main() -> None:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    cases = [a for a in sys.argv[2:]] or list(CASES)
    results: dict[str, list[float]] = {c: [] for c in cases}
    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws, \
            websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws2:
        voice, brain = Probe(ws), Probe(ws2)
        tasks = [asyncio.create_task(voice.receive()), asyncio.create_task(brain.receive())]
        await voice.send({"type": "session.update", "session": realtime_session(CONFIG)})
        await brain.send({"type": "session.update", "session": brain_session(CONFIG)})
        await asyncio.sleep(1.5)
        for _ in range(rounds):
            for case in cases:
                ms, _ = await one(voice, brain, case)
                results[case].append(ms)
        for task in tasks:
            task.cancel()
    for case in cases:
        print(f"{case:9s} voice first audio median {statistics.median(results[case]):5.0f} ms  {[int(x) for x in results[case]]}")


if __name__ == "__main__":
    asyncio.run(main())
