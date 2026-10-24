"""Prepared interjections ("traps"): the examiner reads the slides before the talk.

At agent start (before the presenter presses Start), one Haiku call turns each slide's major
weak points into a trap: phrases the presenter is likely to say when making the weak claim,
plus a ready-made cue. During the talk a transcript chunk is matched against the traps in
microseconds, so a predicted weak claim gets its interjection without waiting ~1-4 s for the
director (live runs: she often cut in after the presenter had moved to the next slide).
Unpredicted claims still go through the director.
"""

import json
import logging
import os
import pathlib
import re
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic

from instructions import slide_digest

log = logging.getLogger("viva.traps")
MODEL = os.environ.get("VIVA_HAIKU_MODEL", "claude-haiku-5-5")

SCHEMA = {
    "type": "object",
    "properties": {
        "traps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slide": {"type": "integer"},
                    "action": {"type": "string", "enum": ["interject", "factcheck"]},
                    "phrases": {"type": "array", "items": {"type": "string"}},
                    "cue": {"type": "string"},
                    "claim": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["slide", "action", "phrases", "cue", "claim", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["traps"],
    "additionalProperties": False,
}

PROMPT = """You prepare a live examiner for a presentation defense. Below are the slides and their weak points.
For every MAJOR weak point that the presenter is likely to state out loud (a missing baseline or metric, a wrong
complexity or wrong outside-world fact, data leakage, an overclaim, a contradiction), write one trap:
- "slide": the slide number.
- "action": "factcheck" if it is a checkable fact about the outside world (who made a tool, what algorithm a library
  uses, a date); otherwise "interject".
- "phrases": 3 to 8 short phrases (1 to 4 words) the presenter would say when making that claim, lowercase, as a
  speech-to-text system would write them. Include variants: digits and words ("40%", "40 percent", "forty
  percent"), spacing variants ("n log n", "o n log n"), synonyms ("bug-free", "bug free", "no bugs"). Each phrase
  must be specific to this claim; never a common word on its own.
- "cue": what the examiner says, at most 20 words, sharp and specific, the way a professor actually talks in a room:
  contractions, plain words, no formal written English ("Hang on. Faster than what? What's the baseline?"). For a
  factcheck: a short preamble only, such as "Hm, let me check that."
- "claim": the claim being challenged, in a few words.
- "reason": a few words for the log.
Skip minor issues (dense slides, uncited motivation statistics) and slides with no weak points."""


@dataclass
class Trap:
    slide: int
    action: str
    phrases: list[str]
    cue: str
    claim: str
    reason: str
    used: bool = field(default=False)


def normalize(text: str) -> str:
    """Lowercase, '%' -> ' percent', punctuation -> spaces, single spaces (as phrases are matched)."""
    text = text.lower().replace("%", " percent").replace("²", " squared")
    text = re.sub(r"[^\w\s]", " ", text)
    return " " + re.sub(r"\s+", " ", text).strip() + " "


async def build(config: dict, cache_path: pathlib.Path | None = None,
                curated_path: pathlib.Path | None = None) -> list[Trap]:
    """Curated traps for a fixed demo session if there are any (so the demo behaves the same every run);
    otherwise one Haiku call for the whole deck, cached per session so restarts don't pay for it again."""
    if curated_path and curated_path.exists():
        data = json.loads(curated_path.read_text(encoding="utf-8"))
        log.info("traps: using curated %s", curated_path.name)
    elif cache_path and cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        client = AsyncAnthropic()
        response = await client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": PROMPT + "\n\nSlides:\n" + slide_digest(config)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text) if response.stop_reason != "max_tokens" else {"traps": []}
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    traps = []
    for t in data.get("traps", []):
        phrases = [p for p in (normalize(p).strip() for p in t.get("phrases", [])) if len(p) >= 4]
        if phrases:
            traps.append(Trap(t["slide"], t["action"], phrases, t["cue"], t["claim"], t["reason"]))
    log.info("traps: %d prepared (%s)", len(traps), ", ".join(f"s{t.slide}:{t.action}" for t in traps))
    return traps


def match(traps: list[Trap], text: str, slide: int) -> Trap | None:
    """An unused trap for this slide (or the one just before or after: people say things early or late)
    whose phrase occurs in the text."""
    norm = normalize(text)
    squashed = norm.replace(" ", "")  # speech-to-text writes "quick sort" for "quicksort", "n log n" for "nlogn"
    for trap in traps:
        if trap.used or abs(trap.slide - slide) > 1:
            continue
        if any(f" {p} " in norm or (" " in p and p.replace(" ", "") in squashed) or p.replace(" ", "") in squashed
               for p in trap.phrases if len(p.replace(" ", "")) >= 6):
            return trap
    return None
