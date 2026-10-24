"""Could one Higgs session be both the brain and the voice? (The alternative to brain.py's second session.)

An audio response can't be silent, so a decision would need a text-only response inside the audio session:
  A) response.create with an undocumented per-response "output_modalities": ["text"]
  B) session.update output_modalities ["text"] -> decision -> session.update ["audio"] -> spoken line
For B it also measures the voice's first audio after the decision: two sessions on one key need a 0.8 s
settle after the brain (two_session_latency.py); within one session that delay may not exist.

    cd agent && uv run probes/single_session.py [rounds]
"""

import asyncio
import json
import pathlib
import statistics
import sys

import websockets

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from common import AUTH, REALTIME_URL, Probe, now, tts_pcm  # noqa: E402  (loads .env)
import instructions as prompts  # noqa: E402
from brain import parse  # noqa: E402
from main import realtime_session  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CONFIG = json.loads((ROOT / "demo" / "session-config-coding.json").read_text(encoding="utf-8"))
SPEECH = "We wrote our own bubble sort, because bubble sort is the fastest sorting algorithm."
BRAIN = prompts.brain(CONFIG, "presentation")


async def speak_and_commit(probe: Probe) -> None:
    await probe.stream(tts_pcm(SPEECH), "presenter")
    await probe.silence(0.6)
    await probe.send({"type": "input_audio_buffer.commit"})


async def case_a(probe: Probe) -> str:
    await speak_and_commit(probe)
    t = now()
    await probe.send({"type": "response.create", "response": {"instructions": BRAIN, "output_modalities": ["text"],
                                                               "max_output_tokens": 60}})
    done = await probe.wait_for("response.done", t, timeout=15)
    texts = [e.get("text", "") for e in probe.seen("response.output_text.done", t)]
    audio = len(probe.seen("response.output_audio.delta", t))
    errors = [e.get("error", {}).get("message", "") for e in probe.seen("error", t)]
    await asyncio.sleep(1.0)
    return f"text={texts!r} audio_deltas={audio} errors={errors} done={'yes' if done else 'no'}"


async def case_b(probe: Probe) -> tuple[str, float, float]:
    await speak_and_commit(probe)
    t = now()
    await probe.send({"type": "session.update", "session": {"output_modalities": ["text"]}})
    await probe.send({"type": "response.create", "response": {"instructions": BRAIN, "max_output_tokens": 60}})
    await probe.wait_for("response.done", t, timeout=15)
    decide_ms = (now() - t) * 1000
    texts = [e.get("text", "") for e in probe.seen("response.output_text.done", t)]
    errors = [e.get("error", {}).get("message", "") for e in probe.seen("error", t)]
    action, line = parse(texts[0] if texts else "")
    await probe.send({"type": "session.update", "session": {"output_modalities": ["audio"]}})
    t0 = now()
    await probe.send({"type": "response.create", "response": {
        "instructions": prompts.with_cue(CONFIG, "presentation", prompts.say_exactly(line or "Hang on.")),
        "max_output_tokens": 100}})
    first = await probe.wait_for("response.output_audio.delta", t0, timeout=10)
    audio_ms = (now() - t0) * 1000 if first else -1
    await probe.wait_for("response.done", t0, timeout=15)
    await asyncio.sleep(1.0)
    return f"{action}: {line!r} errors={errors}", decide_ms, audio_ms


async def main() -> None:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws:
        probe = Probe(ws)
        receiver = asyncio.create_task(probe.receive())
        await probe.send({"type": "session.update", "session": realtime_session(CONFIG)})
        await asyncio.sleep(1.5)
        print("A) per-response output_modalities:", await case_a(probe))
        decide, audio = [], []
        for _ in range(rounds):
            result, d, a = await case_b(probe)
            decide.append(d)
            audio.append(a)
            print(f"B) {result}  decide {d:.0f} ms, first audio {a:.0f} ms")
        receiver.cancel()
    print(f"B) median: decide {statistics.median(decide):.0f} ms, first audio {statistics.median(audio):.0f} ms")


if __name__ == "__main__":
    asyncio.run(main())
