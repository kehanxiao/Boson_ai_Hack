"""Can the voice's delivery be steered per line? A listening check, not a pass/fail test.

The voice says the same line several ways, each from its per-response instructions as exam.py sends them:
plain (as today), with a tone hint after the words, and with a Higgs TTS tag inside the words
(docs/vendor/boson/models/higgs-tts/tags.md; the Realtime docs only mention prompting via instructions).
Each clip is saved as a WAV to listen to; the printed transcript shows whether a hint or a tag was read aloud.

    cd agent && uv run probes/tone_check.py [out_dir]
"""

import asyncio
import base64
import json
import pathlib
import sys
import wave

import websockets

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from common import AUTH, RATE, REALTIME_URL, Probe, now  # noqa: E402  (loads .env)
import instructions as prompts  # noqa: E402
from main import realtime_session  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CONFIG = json.loads((ROOT / "demo" / "session-config-demo3.json").read_text(encoding="utf-8"))
LINE = "You said bubble sort is the fastest. That's not right. What makes you say that?"
VARIANTS = {
    "1_plain": prompts.say_exactly(LINE),
    "2_firm": prompts.say_exactly(LINE) + " Deliver it firmly and seriously, a little slower: a strict examiner who "
                                          "will not let this pass. Do not say how you are delivering it.",
    "3_warm": prompts.say_exactly(LINE) + " Deliver it warmly and gently, like a kind supervisor. Do not say how you "
                                          "are delivering it.",
    "4_puzzled": prompts.say_exactly(LINE) + " Deliver it curious and genuinely puzzled. Do not say how you are "
                                             "delivering it.",
    "5_tag_determination": prompts.say_exactly("<|emotion:determination|>" + LINE),
    "6_tag_surprise": prompts.say_exactly("<|emotion:surprise|>" + LINE),
}


async def main() -> None:
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent / ".cache" / "tone"
    out.mkdir(parents=True, exist_ok=True)
    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws:
        probe = Probe(ws)
        receiver = asyncio.create_task(probe.receive())
        await probe.send({"type": "session.update", "session": realtime_session(CONFIG)})
        await asyncio.sleep(1.5)
        rows = []
        for name, cue in VARIANTS.items():
            t0 = now()
            await probe.send({"type": "response.create", "response": {
                "instructions": prompts.with_cue(CONFIG, "presentation", cue), "max_output_tokens": 100}})
            done = await probe.wait_for("response.done", t0, timeout=20)
            deltas = probe.seen("response.output_audio.delta", t0)
            first = probe.seen_at("response.output_audio.delta", t0)
            said = probe.seen("response.output_audio_transcript.done", t0)
            pcm = b"".join(base64.b64decode(d["delta"]) for d in deltas)
            path = out / f"{name}.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(pcm)
            rows.append((name, (first[0] - t0) * 1000 if first else -1, len(pcm) / (RATE * 2),
                         said[0].get("transcript", "") if said else "", (done or {}).get("response", {}).get("status")))
            await asyncio.sleep(1.0)
        receiver.cancel()
    print(f"\nclips in {out.resolve()}")
    for name, ms, secs, text, status in rows:
        print(f"{name:22s} first audio {ms:5.0f} ms  {secs:4.1f} s  {status}  said: {text!r}")


if __name__ == "__main__":
    asyncio.run(main())
