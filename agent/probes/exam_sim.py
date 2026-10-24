"""Stage 2 end-to-end check, headless: a synthetic presenter defends the demo deck.

Real Higgs Realtime and a real Haiku director; no LiveKit, no avatar (playback is simulated
in real time). The presenter's microphone stays open (silence between sentences). The script
is event-driven: it waits for the examiner like a person would, except when it deliberately
ignores the time reminder.

Times are shortened: 140 s presentation, reminder at 95 s, 60 s of Q&A.

    cd agent && uv run probes/exam_sim.py
"""

import asyncio
import json
import logging
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import websockets  # noqa: E402
from livekit import rtc  # noqa: E402

from common import AUTH, REALTIME_URL, tts_pcm  # noqa: E402  (loads .env)
from director import Director  # noqa: E402
from exam import ExamController  # noqa: E402
from main import realtime_session  # noqa: E402
from output import SimulatedOutput  # noqa: E402
from realtime import RealtimeClient  # noqa: E402
from session_log import SessionLog  # noqa: E402
from ui import PrintUI  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RATE, FRAME = 24_000, 480  # 20 ms frames
T0 = time.monotonic()

SCRIPT_A = [  # (slide, text, wait for the examiner first)
    (1, "Hi everyone. Today I'm presenting ERwait, a system for forecasting emergency room wait times at a Toronto hospital network.", True),
    (2, "Long waits are a real problem. About one in twenty patients leave without being seen, so we forecast the next four hours of wait time.", True),
    (3, "And the headline result: our model is forty percent better, which is a big step forward for the hospital.", True),
    (3, "Sorry. The baseline is the hospital's current rolling average, and the metric is mean absolute error.", True),
    (4, "For data, we used two years of triage records, about one point two million visits, and we removed the outliers before training.", True),
    (5, "For the model we used LightGBM, which Google released in 2020, with rolling-window validation.", True),
    (5, "Right, thank you for checking.", True),
]
FILLER = [  # slide 6: rambles until the reminder, then keeps going (ignores it)
    "Then for feature engineering we built lag features of the wait time at one, two, four and twenty-four hours, rolling means and maximums over the last day, and the current queue length by triage level.",
    "We also added calendar features like the hour of day, the day of week, statutory holidays and school holidays, and then weather features such as temperature, rain and snowfall, and staffing levels per shift.",
    "And the next group is the triage mix, so the share of each acuity level in the last hour, plus ambulance arrivals, plus the number of admitted patients still waiting for a bed upstairs.",
]
SCRIPT_C = [
    (6, "Okay, noted. Moving on.", False),
    (7, "We believe ERwait is ready for deployment across all Ontario hospitals.", True),
    (8, "To conclude, ERwait forecasts wait times four hours ahead, and next we want to add real-time bed data.", True),
]
QA = [
    "Good question. Jujur saja, kami belum cek apakah waktu ke dokter itu masuk ke target, tapi kami bisa retrain tanpa fitur itu.",
    "我们用的是滚动窗口验证, rolling origin, so no future data leaks into training.",
    "We validated on one hospital network only, so the Ontario claim is aspirational for now.",
]
BARGE_IN = "Sorry, can I stop you there? I think I already answered that."


def now() -> float:
    return time.monotonic() - T0


class Mic:
    """An always-open microphone: queued speech, otherwise silence, at real-time pace."""

    def __init__(self, controller: ExamController):
        self.controller = controller
        self.queue: asyncio.Queue[tuple[bytes, asyncio.Event]] = asyncio.Queue()
        self.task = asyncio.create_task(self._pump())

    async def say(self, text: str) -> None:
        done = asyncio.Event()
        print(f"{now():7.2f}s  PRESENTER: {text[:90]}", flush=True)
        await self.queue.put((tts_pcm(text), done))
        await done.wait()

    async def _pump(self) -> None:
        silence = b"\x00\x00" * FRAME
        current, done, pos = b"", None, 0
        start, sent = time.monotonic(), 0
        while True:
            if pos >= len(current):
                if done:
                    done.set()
                    done = None
                try:
                    current, done = self.queue.get_nowait()
                    pos = 0
                except asyncio.QueueEmpty:
                    current, pos = b"", 0
            if current:
                chunk = current[pos:pos + FRAME * 2].ljust(FRAME * 2, b"\x00")
                pos += FRAME * 2
            else:
                chunk = silence
            await self.controller.on_presenter_audio(rtc.AudioFrame(chunk, RATE, 1, FRAME))
            sent += 1
            await asyncio.sleep(max(0.0, start + sent * 0.02 - time.monotonic()))


async def wait_examiner(c: ExamController, timeout=30.0) -> None:
    await asyncio.sleep(0.6)
    deadline = time.monotonic() + timeout
    while (c.engaged or c.director_busy) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.5)


async def presenter(c: ExamController, mic: Mic) -> None:
    await c.on_ctl({"type": "start"})
    for slide, text, wait in SCRIPT_A:
        await c.on_ctl({"type": "slide", "index": slide})
        if wait:
            await wait_examiner(c)
        await mic.say(text)
    await wait_examiner(c)
    await c.on_ctl({"type": "slide", "index": 6})
    i = 0
    while not (c.reminder and (c.reminder.get("played_at") or c.reminder.get("escalated"))):
        await mic.say(FILLER[i % len(FILLER)])  # ramble until the reminder has played
        i += 1
    if not c.reminder.get("escalated"):
        await mic.say(FILLER[i % len(FILLER)])  # ...and ignore it: keep talking
    await wait_examiner(c)  # the escalation
    for slide, text, wait in SCRIPT_C:
        if c.phase != "presentation":
            break
        await c.on_ctl({"type": "slide", "index": slide})
        if wait:
            await wait_examiner(c)
        await mic.say(text)
    while c.phase == "presentation":
        await asyncio.sleep(0.2)
    for answer in QA:
        await wait_examiner(c)
        if c.phase != "qa":
            return
        await mic.say(answer)
    # Barge in on the next examiner reply.
    while c.phase == "qa" and not c.examiner_audible:
        await asyncio.sleep(0.05)
    if c.phase == "qa":
        await asyncio.sleep(1.0)
        await mic.say(BARGE_IN)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("livekit", "httpx", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    config = json.loads((ROOT / "demo" / "session-config.json").read_text(encoding="utf-8"))
    config.update({"time_limit_s": 140, "qa_s": 60})
    log_path = pathlib.Path(__file__).resolve().parent / ".cache" / "exam-sim-log.jsonl"
    slog = SessionLog(log_path)

    controller: ExamController | None = None

    async def on_event(kind, event):
        if controller:
            await controller.on_realtime_event(kind, event)

    realtime = RealtimeClient(REALTIME_URL, AUTH["Authorization"].split(" ", 1)[1], on_event)
    controller = ExamController(config, realtime, SimulatedOutput(), PrintUI(now), slog, Director(config), reminder_before_s=45)
    await realtime.connect(realtime_session(config))
    await asyncio.sleep(1.5)
    mic = Mic(controller)
    script = asyncio.create_task(presenter(controller, mic))
    try:
        await asyncio.wait_for(controller.ended.wait(), timeout=330)
    except asyncio.TimeoutError:
        print("TIMEOUT: the exam did not end", flush=True)
    script.cancel()
    mic.task.cancel()
    await controller.aclose()
    await realtime.close()
    report(log_path)


def report(path: pathlib.Path) -> None:
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    kinds = [e["kind"] for e in entries]
    phases = [e["phase"] for e in entries if e["kind"] == "phase"]
    examiner = [e for e in entries if e["kind"] == "examiner"]
    fc_done = [e for e in entries if e["kind"] == "factcheck" and e.get("status") == "done"]
    after_fc = " ".join(e["text"] for e in examiner if fc_done and e["t"] >= fc_done[0]["t"] - 15)
    langs = {e.get("lang") for e in entries if e["kind"] == "chunk"}
    checks = {
        "interjection on slide 3": any(e["kind"] == "interjection" and e["slide"] == 3 for e in entries),
        "fact-check searched and finished": bool(fc_done),
        "fact-check names Microsoft": "microsoft" in after_fc.lower(),
        "reminder -> escalation -> ack": all(k in kinds for k in ("reminder", "escalation", "ack")),
        "phases presentation/qa/debrief/end": phases == ["presentation", "qa", "debrief", "end"],
        "verdict spoken": any(e["text"].lower().startswith("verdict") for e in examiner),
        "no 'already covered' question in Q&A": not any(("forty percent" in e["text"].lower() or "40%" in e["text"]) and e["t"] > (
            next((p["t"] for p in entries if p["kind"] == "phase" and p.get("phase") == "qa"), 1e9)) for e in examiner),
        "only contract log kinds": set(kinds) <= {"chunk", "examiner", "director", "interjection", "reminder", "ack",
                                                 "escalation", "phase", "slide", "factcheck"},
    }
    print("\n=== RESULTS ===")
    for name, ok in checks.items():
        print(f"{name:40s} {'PASS' if ok else 'FAIL'}")
    # Informational: the TTS voice's Indonesian/Mandarin accent decides what the STT hears.
    print(f"{'(info) chunk languages detected':40s} {sorted(langs)}")
    metrics = {}
    for e in entries:
        if e["kind"] == "director":
            metrics.setdefault("director_ms", []).append(e.get("ms"))
    print(f"{'(info) director call ms':40s} {metrics.get('director_ms')}")
    print(f"log: {path} ({len(entries)} lines); examiner lines:")
    for e in examiner:
        print(f"  {e['t']:6.1f}s  {e['text'][:140]}")


if __name__ == "__main__":
    asyncio.run(main())
