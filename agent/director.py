"""The director: a fast Haiku call that decides whether the examiner should cut in now.

It reads the presenter's latest chunk in context (current slide, its weak points, recent
transcript, earlier interjections) and returns a structured decision. Cooldowns and caps
are enforced by the caller, not by the model.
"""

import json
import os
import pathlib
import time
from dataclasses import dataclass

from anthropic import AsyncAnthropic

from instructions import slide_digest

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
MODEL = os.environ.get("VIVA_HAIKU_MODEL", "claude-haiku-5-5")

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["none", "interject", "factcheck"]},
        "kind": {
            "type": "string",
            "enum": ["none", "question_closed", "question_open", "comment_negative", "comment_positive", "factcheck"],
        },
        "severity": {"type": "string", "enum": ["major", "minor"]},
        "reason": {"type": "string"},
        "cue": {"type": "string"},
        "claim": {"type": "string"},
    },
    "required": ["action", "kind", "severity", "reason", "cue", "claim"],
    "additionalProperties": False,
}


@dataclass
class Decision:
    action: str
    kind: str
    severity: str  # "major" interrupts the talk; "minor" waits for the questions
    reason: str
    cue: str
    claim: str
    ms: int  # how long the call took


class Director:
    def __init__(self, config: dict):
        self.config = config
        self.client = AsyncAnthropic()
        character = config["character"]
        minor_ok = int(character.get("strictness", 3)) >= 5  # same rule as exam.interrupts_on_minor
        # Stable across the session, so it goes first (cacheable prefix).
        self.system = "\n\n".join([
            (PROMPTS / "director.md").read_text(encoding="utf-8").strip(),
            f"Examiner character: {character['name']}. {character.get('persona', '')} "
            f"Interruption rate: {character.get('interrupt_rate', 'medium')}; strictness {character.get('strictness', 3)}/5. "
            + ("This examiner is strict enough to interrupt for minor issues too."
               if minor_ok else "This examiner interrupts only for major issues."),
            "Slides:\n" + slide_digest(config),
        ])

    async def decide(self, *, slide: int, latest: str, recent: list[str], earlier: list[str], elapsed_s: float,
                     factcheck_only: bool = False) -> Decision:
        current = next((s for s in self.config.get("slides", []) if s["index"] == slide), {})
        user = "\n".join([
            *(["Right now only a factcheck is allowed (the examiner interjected recently); otherwise choose none."]
              if factcheck_only else []),
            f"Elapsed: {elapsed_s:.0f}s of {self.config.get('time_limit_s', 300)}s. Current slide: {slide}.",
            f"Current slide weak points: {'; '.join(current.get('weak_points', [])) or 'none listed'}",
            "Earlier interjections: " + (" | ".join(earlier) if earlier else "none"),
            "Recent transcript:\n" + ("\n".join(recent) if recent else "(none)"),
            f"Latest chunk (just said): {latest}",
        ])
        started = time.monotonic()
        response = await self.client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=self.system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        ms = int((time.monotonic() - started) * 1000)
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        data = json.loads(text)
        return Decision(
            action=data.get("action", "none"),
            kind=data.get("kind", "none"),
            severity=data.get("severity", "minor"),
            reason=data.get("reason", ""),
            cue=data.get("cue", ""),
            claim=data.get("claim", ""),
            ms=ms,
        )
