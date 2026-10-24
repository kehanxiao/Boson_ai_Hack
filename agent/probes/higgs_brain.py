"""Experiment: Higgs Realtime as the examiner's brain, compared with the Haiku director.

A text-only Higgs Realtime session (output_modalities ["text"], manual turns) hears the presenter's
audio directly and, after each chunk, answers with one line: SILENT, SAY: <line>, or CHECK: <claim>.
The same chunks' transcripts go to the Haiku director for comparison. A synthetic presenter makes
correct statements, filler, and deliberate errors (some on the slides, some not).

    cd agent && uv run probes/higgs_brain.py [runs] [--prompt old|live] [--stt on|off] [--notes every|change] [--no-haiku]

--prompt live uses the agent's own brain instructions (instructions.brain); --stt off and --notes change
match the live brain session (no transcription; a slide note only when the slide changes).
"""

import argparse
import asyncio
import json
import pathlib
import statistics
import sys

import websockets

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from common import AUTH, CAPTION_MODEL, MODEL, REALTIME_URL, Probe, now, tts_pcm  # noqa: E402  (loads .env)
import instructions  # noqa: E402
from brain import parse as parse_live  # noqa: E402
from director import Director  # noqa: E402
from instructions import slide_digest  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CONFIG = json.loads((ROOT / "demo" / "session-config-coding.json").read_text(encoding="utf-8"))

# (slide, what the presenter says, should the examiner react?)
SCRIPT = [
    (1, "Hi everyone, I'm Sam Lee, and this is GradeBook, my Python program for ranking student grades.", False),
    (2, "The task had three steps: read a CSV of names and scores, sort the students from lowest to highest, and print the top twenty.", True),
    (2, "We wrote it in Python, which was created by Google in 2010.", True),
    (3, "We wrote our own bubble sort, because bubble sort is the fastest sorting algorithm. It's O of n log n.", True),
    (3, "Um, so, yeah.", False),
    (4, "The load function opens grades dot CSV and reads every row with the CSV reader.", False),
    (3, "Python's built-in sorted uses quicksort, so ours is just as good.", True),
    (5, "As a result, GradeBook is five times faster.", True),
    (5, "We sorted five hundred students and printed the top ten and the class average.", False),
    (6, "We tested it on three files, and it's bug-free and ready for any school.", True),
]

BRAIN = f"""You are the inner judgment of {CONFIG['character']['name']}, an examiner at an assignment oral exam.
You are not her voice: you listen to the presenter and decide, after each chunk, what she should do right now.
{CONFIG['character'].get('persona', '')}

The slides you have read:
{slide_digest(CONFIG)}

After each chunk of the presenter's speech, answer with exactly one line and nothing else:
SILENT
SAY: <what she says out loud, at most 20 words, natural spoken English, specific to what was just said>
CHECK: <the claim to verify on the web>

Speak up (SAY) when the presenter says something false, contradicts their own slides or something they said
earlier, makes a claim without evidence, or dodges a question. Use CHECK for a checkable fact about the outside
world (who made a tool, what algorithm a library uses, a date) that looks wrong. Stay SILENT for correct statements,
filler and ordinary presenting. Never explain your choice."""


def parse(text: str) -> tuple[str, str]:
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    for tag in ("SILENT", "SAY:", "CHECK:"):
        if line.upper().startswith(tag):
            return tag.rstrip(":"), line[len(tag):].strip()
    return "INVALID", line


async def run_once(director: Director | None, args) -> list[dict]:
    rows = []
    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws:
        probe = Probe(ws)
        receiver = asyncio.create_task(probe.receive())
        audio_in: dict = {"turn_detection": None}
        if args.stt == "on":
            audio_in["transcription"] = {"model": CAPTION_MODEL}
        prompt = BRAIN if args.prompt == "old" else instructions.brain(CONFIG, "presentation")
        if args.prompt_file:
            prompt = pathlib.Path(args.prompt_file).read_text(encoding="utf-8")
        await probe.send({"type": "session.update", "session": {
            "model": MODEL, "instructions": prompt, "output_modalities": ["text"], "max_output_tokens": 60,
            "audio": {"input": audio_in},
        }})
        await asyncio.sleep(1.5)
        recent: list[str] = []
        shown = None
        for slide, text, should in SCRIPT:
            if args.notes == "every" or slide != shown:
                note = f"[The presenter is on slide {slide}.]" if args.notes == "every" else f"[Slide {slide} is showing now.]"
                await probe.send({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": note}]}})
                shown = slide
            await probe.stream(tts_pcm(text), f"s{slide}")
            await probe.silence(0.6)
            t0 = now()
            await probe.send({"type": "input_audio_buffer.commit"})
            await probe.send({"type": "response.create"})
            done = await probe.wait_for("response.output_text.done", t0, timeout=10)
            higgs_ms = (now() - t0) * 1000
            action, line = (parse if args.prompt == "old" else parse_live)(done.get("text", "") if done else "")
            row = {"slide": slide, "said": text, "should": should, "higgs": action, "higgs_line": line,
                   "higgs_ms": int(higgs_ms), "raw": (done or {}).get("text", ""), "transcript": "",
                   "haiku": "-", "haiku_severity": "", "haiku_line": "", "haiku_ms": 0}
            if director:
                await probe.wait_for("conversation.item.input_audio_transcription.completed", t0, timeout=3)
                transcript = next((e.get("transcript", "") for e in probe.seen(
                    "conversation.item.input_audio_transcription.completed", t0)), "")
                d = await director.decide(slide=slide, latest=transcript or text, recent=recent[-6:], earlier=[], elapsed_s=60)
                recent.append(f"slide {slide}: {transcript or text}")
                row.update(transcript=transcript, haiku=d.action, haiku_severity=d.severity, haiku_line=d.cue or d.claim,
                           haiku_ms=d.ms)
            rows.append(row)
            await asyncio.sleep(0.5)
        receiver.cancel()
    return rows


def score(rows: list[dict], who: str) -> str:
    acted = lambda r: r[who] in (("SAY", "CHECK") if who == "higgs" else ("interject", "factcheck"))  # noqa: E731
    hits = sum(1 for r in rows if r["should"] and acted(r))
    misses = sum(1 for r in rows if r["should"] and not acted(r))
    false_alarms = sum(1 for r in rows if not r["should"] and acted(r))
    invalid = sum(1 for r in rows if who == "higgs" and r["higgs"] == "INVALID")
    ms = [r[f"{who}_ms"] for r in rows]
    return (f"{who:6s} caught {hits}/{hits + misses}, false alarms {false_alarms}, invalid {invalid}, "
            f"median {statistics.median(ms):.0f} ms (max {max(ms)})")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="?", type=int, default=1)
    parser.add_argument("--prompt", choices=["old", "live"], default="old")
    parser.add_argument("--stt", choices=["on", "off"], default="on")
    parser.add_argument("--notes", choices=["every", "change"], default="every")
    parser.add_argument("--no-haiku", action="store_true")
    parser.add_argument("--prompt-file", help="brain instructions from this file instead (prompt experiments)")
    args = parser.parse_args()
    director = None if args.no_haiku else Director(CONFIG)
    print(f"prompt={args.prompt} stt={args.stt} notes={args.notes}")
    for n in range(1, args.runs + 1):
        rows = await run_once(director, args)
        print(f"\n=== run {n} ===")
        for r in rows:
            print(f"s{r['slide']} {'ERR ' if r['should'] else 'ok  '}{r['said'][:58]:58s}")
            print(f"     higgs {r['higgs']:7s} {r['higgs_ms']:5d} ms  {r['higgs_line'][:90]!r}")
            print(f"     haiku {r['haiku']:9s} {r['haiku_ms']:5d} ms  {r['haiku_line'][:90]!r}   (heard: {r['transcript'][:60]!r})")
        print(score(rows, "higgs"))
        if director:
            print(score(rows, "haiku"))


if __name__ == "__main__":
    asyncio.run(main())
