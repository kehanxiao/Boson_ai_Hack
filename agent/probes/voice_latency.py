"""Why does the voice take ~1.7 s to its first audio after a brain decision (K2 measured ~0.45 s)?

Hypothesis: the voice response waits for the transcription of the chunk committed at that same pause.
Measures response.create -> first audio delta, with the agent's full per-response instructions.
The microphone keeps streaming silence the whole time, as in the live agent and the sim:
  a) commit, wait 0.45 s (the brain's decision), then response.create (what exam.py does at a pause)
  b) response.create with the presenter's audio left uncommitted
  c) commit, wait 3 s, then response.create

    cd agent && uv run probes/voice_latency.py [rounds] [--brain]

--brain adds the agent's brain session on a second WebSocket: it gets the same audio and commit, and
the voice is asked right after the brain's text answer, as in exam.py.
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


class Mic:
    """Silence in 20 ms frames whenever no speech is being streamed (an open microphone)."""

    def __init__(self, *probes: Probe):
        self.probes, self.quiet = probes, asyncio.Event()
        self.quiet.set()
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        frame = base64.b64encode(bytes(960)).decode()
        while True:
            await self.quiet.wait()
            for probe in self.probes:
                await probe.send({"type": "input_audio_buffer.append", "audio": frame})
            await asyncio.sleep(0.02)


async def stream_both(pcm: bytes, probes: list[Probe]) -> None:
    for i in range(0, len(pcm), 960):
        frame = base64.b64encode(pcm[i:i + 960].ljust(960, bytes(1))).decode()
        for probe in probes:
            await probe.send({"type": "input_audio_buffer.append", "audio": frame})
        await asyncio.sleep(0.02)


async def one(probe: Probe, mic: Mic, case: str, brain: Probe | None) -> float:
    mic.quiet.clear()
    if brain:
        await stream_both(tts_pcm(SPEECH), [probe, brain])
    else:
        await probe.stream(tts_pcm(SPEECH), "presenter")
    mic.quiet.set()
    await asyncio.sleep(0.6)
    if case in ("a", "c"):
        await probe.send({"type": "input_audio_buffer.commit"})
    if brain:
        t = now()
        await brain.send({"type": "input_audio_buffer.commit"})
        await brain.send({"type": "response.create", "response": {}})
        await brain.wait_for("response.done", t, timeout=10)
    else:
        await asyncio.sleep(0.45)
    if case == "c":
        await asyncio.sleep(2.5)
    t0 = now()
    await probe.send({"type": "response.create", "response": {
        "instructions": prompts.with_cue(CONFIG, "presentation", prompts.say_exactly(LINE)), "max_output_tokens": 100}})
    first = await probe.wait_for("response.output_audio.delta", t0, timeout=10)
    ms = (now() - t0) * 1000 if first else -1
    await probe.wait_for("response.done", t0, timeout=15)
    if case == "b":
        await probe.send({"type": "input_audio_buffer.commit"})  # keep the next round comparable
    await asyncio.sleep(1.0)
    return ms


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rounds = int(args[0]) if args else 3
    with_brain = "--brain" in sys.argv
    results: dict[str, list[float]] = {"a": [], "b": [], "c": []}
    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws,             websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws2:
        probe = Probe(ws)
        receiver = asyncio.create_task(probe.receive())
        await probe.send({"type": "session.update", "session": realtime_session(CONFIG)})
        brain = None
        if with_brain:
            brain = Probe(ws2)
            asyncio.create_task(brain.receive())
            await brain.send({"type": "session.update", "session": brain_session(CONFIG)})
        await asyncio.sleep(1.5)
        mic = Mic(*([probe, brain] if brain else [probe]))
        for _ in range(rounds):
            for case in ("a", "b", "c"):
                results[case].append(await one(probe, mic, case, brain))
        mic.task.cancel()
        receiver.cancel()
    print("with brain session" if with_brain else "voice session only")
    for case, label in (("a", "commit, brain, create"), ("b", "no commit"), ("c", "commit, 3 s, create")):
        ms = results[case]
        print(f"{label:24s} first audio median {statistics.median(ms):5.0f} ms  {[int(x) for x in ms]}")


if __name__ == "__main__":
    asyncio.run(main())
