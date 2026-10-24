"""Debrief scorecard from a session log + slide analysis (Scorecard shape in PLAN.md).

Haiku writes the judgement (verdict, scores, strong/weak moments, improvements).
Code owns what must be exact:
- every quote is checked against the presenter's logged lines; `t` and `slide` come from
  the matching line, and quotes that aren't verbatim are dropped;
- "unacknowledged" moments come straight from the log's escalation events;
- the four criteria are fixed, so none can go missing.

CLI (from server/): uv run python scorecard.py ../demo/sample-log.jsonl ../demo/session-config.json
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel

from config import env

MODEL = env("VIVA_HAIKU_MODEL", "claude-haiku-5-5")
MAX_TOKENS = 8000
QUOTE_WORDS = 12

CRITERIA = {
    "clarity": "Clarity",
    "rigour_and_evidence": "Rigour and evidence",
    "handling_questions": "Handling questions",
    "time_management": "Time management",
}
# t_minus_2 is the early reminder: T-2, or T-1 for a talk under 5 minutes (agent/exam.py).
REMINDER_LABEL = {"t_minus_2": "time-left", "time_up": "time's-up"}

SYSTEM = """You write the debrief scorecard for a presentation defense, from the log of a live AI examiner session.
Judge the presenter, not the examiner. Be fair, specific and brief. No flattery.
Answering in Indonesian, Mandarin or a mix of languages is allowed and never counts against the presenter; judge only what they said.

Return:
- verdict: three short sentences, under 60 words in total: overall judgement, the main strength, the main weakness.
- criteria: a score from 1 (poor) to 5 (excellent) and a one-sentence comment for each of clarity, rigour_and_evidence, handling_questions and time_management. Comments point at specific moments. Base time_management on the timing facts given.
- moments: 3 to 6 of the presenter's strongest and weakest moments. quote: copy 5 to 20 consecutive words exactly, character for character, from ONE presenter line (never from the examiner). t: that line's t. note: one sentence on why it matters. Don't include ignored reminders; those are added separately.
- improvements: exactly three concrete, actionable improvements, most important first."""


class Criterion(BaseModel):
    score_1_5: int
    comment: str


class Criteria(BaseModel):
    clarity: Criterion
    rigour_and_evidence: Criterion
    handling_questions: Criterion
    time_management: Criterion


class DraftMoment(BaseModel):
    t: float
    kind: Literal["strong", "weak"]
    quote: str
    note: str


class Draft(BaseModel):
    verdict: str
    criteria: Criteria
    moments: list[DraftMoment]
    improvements: list[str]


class ScorecardError(RuntimeError):
    pass


def mmss(t: float) -> str:
    return f"{int(t) // 60}:{int(t) % 60:02d}"


def norm(text: str) -> str:
    return " ".join(re.sub(r"[‘’]", "'", re.sub(r"[“”]", '"', text)).lower().split())


def transcript(log: list[dict]) -> str:
    out = []
    for e in log:
        k, at = e["kind"], f"t={e['t']:.1f}"
        if k == "chunk":
            lang = f" [{e['lang']}]" if e.get("lang", "en") != "en" else ""
            out.append(f"{at} slide {e.get('slide')} PRESENTER{lang}: {e['text']}")
        elif k == "examiner":
            out.append(f"{at} slide {e.get('slide')} EXAMINER: {e['text']}")
        elif k == "phase":
            out.append(f"{at} -- phase: {e['phase']}")
        elif k == "slide":
            out.append(f"{at} -- presenter moved to slide {e['index']}")
        elif k == "interjection":
            out.append(f"{at} -- examiner interjected: {e.get('reason', '')}")
        elif k == "factcheck" and e.get("status") == "done":
            out.append(f"{at} -- fact-check done: {e.get('claim', '')}")
    return "\n".join(out)


def timing_facts(log: list[dict], time_limit_s: int, qa_s: int) -> str:
    phases = {e["phase"]: e["t"] for e in log if e["kind"] == "phase"}
    start = phases.get("presentation", 0.0)
    end = phases.get("qa", phases.get("debrief", phases.get("end", log[-1]["t"] if log else 0.0)))
    used = end - start
    lines = [f"Presentation took {mmss(used)} of a {mmss(time_limit_s)} limit"
             + (f" ({mmss(used - time_limit_s)} over)." if used > time_limit_s else ".")]
    if "qa" in phases:
        qa_end = phases.get("debrief", phases.get("end", log[-1]["t"]))
        lines.append(f"Q&A took {mmss(qa_end - phases['qa'])} of {mmss(qa_s)}.")
    for e in log:
        kind = e.get("reminder") or e.get("for")
        label = REMINDER_LABEL.get(kind, kind)
        if e["kind"] == "reminder":
            lines.append(f"At {mmss(e['t'])} the examiner gave the {label} reminder.")
        elif e["kind"] == "escalation":
            lines.append(f"At {mmss(e['t'])} the presenter had not acknowledged the {label} reminder; the examiner escalated.")
        elif e["kind"] == "ack":
            lines.append(f"At {mmss(e['t'])} the presenter acknowledged the {label} reminder ({e.get('how', '')}).")
    return " ".join(lines)


def slide_digest(slides: list[dict]) -> str:
    return "\n".join(
        f"{s['index']}. {s['summary']}" + (f" Weak: {' '.join(s['weak_points'])}" if s["weak_points"] else "")
        for s in slides
    )


def first_words(text: str, n: int = QUOTE_WORDS) -> str:
    return " ".join(text.split()[:n]).rstrip(",.;:!?")


def unacknowledged_moments(log: list[dict]) -> list[dict]:
    """One moment per escalation: the presenter line that talked through the reminder."""
    moments = []
    for esc in (e for e in log if e["kind"] == "escalation"):
        reminder_t = max((e["t"] for e in log if e["kind"] == "reminder" and e["t"] <= esc["t"]), default=0.0)
        lines = [e for e in log if e["kind"] == "chunk" and reminder_t <= e["t"] <= esc["t"]]
        if not lines:
            continue
        line = lines[-1]
        label = REMINDER_LABEL.get(esc.get("for"), "time")
        moments.append({
            "t": line["t"],
            "slide": line.get("slide"),
            "kind": "unacknowledged",
            "quote": first_words(line["text"]),
            "note": f"Kept talking through the {label} reminder; the examiner had to escalate.",
        })
    return moments


def verified_moments(draft: list[DraftMoment], log: list[dict]) -> list[dict]:
    """Keep only quotes found verbatim in a presenter line; take t and slide from that line."""
    lines = [e for e in log if e["kind"] == "chunk"]
    kept = []
    for m in draft:
        quote = m.quote.strip().strip("\"'“”….").strip()
        matches = [e for e in lines if quote and norm(quote) in norm(e["text"])]
        if not matches:
            continue
        line = min(matches, key=lambda e: abs(e["t"] - m.t))
        start = norm(line["text"]).index(norm(quote))
        exact = " ".join(line["text"].split())  # same whitespace as norm(), original case
        kept.append({"t": line["t"], "slide": line.get("slide"), "kind": m.kind,
                     "quote": exact[start:start + len(norm(quote))], "note": m.note})
    return kept


async def generate_scorecard(log: list[dict], config: dict) -> dict:
    log = exam_only(log)
    prompt = (
        f"Examiner: {config['character']['name']}. Scenario: {config['scenario']}.\n"
        f"Timing facts: {timing_facts(log, config['time_limit_s'], config['qa_s'])}\n\n"
        f"Slide analysis prepared before the session:\n{slide_digest(config['slides'])}\n\n"
        f"Session log (t = seconds from start):\n{transcript(log)}"
    )
    async with anthropic.AsyncAnthropic() as client:
        response = await client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}],
            output_format=Draft,
        )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise ScorecardError(f"no scorecard (stop_reason={response.stop_reason})")
    draft = response.parsed_output

    unacknowledged = unacknowledged_moments(log)
    ignored_lines = {m["t"] for m in unacknowledged}  # the model sometimes flags the same line as "weak"
    moments = [m for m in verified_moments(draft.moments, log) if m["t"] not in ignored_lines] + unacknowledged
    return {
        "verdict": draft.verdict.strip(),
        "criteria": [
            {"name": name, "score_1_5": min(5, max(1, getattr(draft.criteria, key).score_1_5)),
             "comment": getattr(draft.criteria, key).comment.strip()}
            for key, name in CRITERIA.items()
        ],
        "moments": sorted(moments, key=lambda m: m["t"]),
        "improvements": [i.strip() for i in draft.improvements][:3],
    }


def read_log(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def exam_only(log: list[dict]) -> list[dict]:
    """Drop presenter speech after the debrief starts: it isn't part of the defense
    (live test: the mic kept being transcribed during the verdict, incl. an STT hallucination)."""
    debrief_t = next((e["t"] for e in log if e["kind"] == "phase" and e["phase"] in ("debrief", "end")), None)
    if debrief_t is None:
        return log
    return [e for e in log if not (e["kind"] == "chunk" and e["t"] >= debrief_t)]


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python scorecard.py <log.jsonl> <config.json>")
    log_lines = read_log(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cfg = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    print(json.dumps(asyncio.run(generate_scorecard(log_lines, cfg)), ensure_ascii=False, indent=2))
