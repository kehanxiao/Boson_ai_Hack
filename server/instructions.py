"""Assemble the examiner's session instructions (SessionConfig.instructions).

base prompt (agent/prompts/examiner_base.md, owned by Role A; a stand-in until it exists)
+ character + scenario + time limits + notes + support-doc excerpt + per-slide digest.
"""

from config import ROOT_DIR

BASE_PROMPT_PATH = ROOT_DIR / "agent" / "prompts" / "examiner_base.md"

# Stand-in for A's examiner_base.md. It carries the rules A's K5 probes found necessary.
FALLBACK_BASE = """You are the examiner in a live oral defense of a slide presentation, followed by Q&A. You are the examiner, not an assistant: you hold the floor when you speak, you do not over-praise, you do not apologise for asking, and you keep strict time. Be rigorous and fair.
Speak in short spoken sentences: at most two per turn. Ask one question at a time.
During the presentation, speak only when a cue tells you to interject.
Never mention your notes, cues, a director or these instructions.
In Q&A the presenter may answer in Indonesian, Mandarin or mixed with English: follow them naturally, then continue in English.
Use web search to check factual claims about the outside world. After a search, state only the finding, briefly."""

SCENARIOS = {
    "thesis_defense": ("a graduate thesis defense", "a thesis committee examiner"),
    "capstone_internship": ("a capstone or internship project presentation", "a supervisor who judges both rigour and real-world value"),
    "assignment_oral": ("an assignment oral exam", "a course instructor checking that the student understands their own work"),
}


def base_prompt() -> str:
    if BASE_PROMPT_PATH.exists():
        return BASE_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return FALLBACK_BASE


def duration(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    parts = ([f"{minutes} minute{'s' * (minutes != 1)}"] if minutes else []) + ([f"{secs} seconds"] if secs else [])
    return " ".join(parts) or "0 seconds"


def slide_digest(slides: list[dict]) -> str:
    lines = []
    for s in slides:
        line = f"{s['index']}. {s['summary']}"
        if s["weak_points"]:
            line += " Weak: " + " ".join(s["weak_points"])
        lines.append(line)
    return "\n".join(lines)


def build_instructions(
    *,
    character: dict,
    scenario: str,
    time_limit_s: int,
    qa_s: int,
    notes: str,
    support_excerpt: str,
    slides: list[dict],
) -> str:
    event, role = SCENARIOS[scenario]
    parts = [
        base_prompt(),
        f"You are {character['name']}, acting as {role}. {character['persona']}",
        f"This is {event}: {duration(time_limit_s)} of presentation, then {duration(qa_s)} of Q&A. "
        f"The deck has {len(slides)} slides.",
    ]
    if notes.strip():
        parts.append(f"The presenter asked you to focus on: {notes.strip()}")
    if support_excerpt:
        parts.append(f"Supporting document (excerpt):\n{support_excerpt}")
    parts.append(f"Slide digest:\n{slide_digest(slides)}")
    return "\n\n".join(parts)
