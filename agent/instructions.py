"""Examiner instructions for each phase, assembled from prompts/ and the SessionConfig.

The agent assembles these itself (it owns the phases); SessionConfig.instructions from the
server is not needed for that and is ignored.
"""

import pathlib

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"

SCENARIOS = {
    "thesis_defense": "a thesis defense",
    "capstone_internship": "a capstone or internship project presentation",
    "assignment_oral": "an oral examination of an assignment",
}

PHASES = {
    "presentation": (
        "Phase: the presentation is running. Stay silent while the presenter talks. You only speak when you are "
        "explicitly told to: to interject, to acknowledge their answer to an interjection and let them continue, "
        "to give a time reminder, or to greet them."
    ),
    "qa": (
        "Phase: questions and answers. The presentation is over. Lead the questioning: react to what the presenter "
        "actually said in at most one sentence, then ask one question. Press on vague answers. Never ask a question "
        "you have already asked, and do not search the web or re-check facts now: the fact-checks are done."
    ),
    "debrief": "Phase: debrief. The examination is over. Give your verdict when asked, in at most three sentences.",
}


def slide_digest(config: dict) -> str:
    lines = []
    for slide in config.get("slides", []):
        line = f"Slide {slide['index']}: {slide.get('summary', '')}"
        if slide.get("weak_points"):
            line += " Weak points: " + "; ".join(slide["weak_points"])
        lines.append(line)
    return "\n".join(lines)


def core(config: dict) -> str:
    character = config["character"]
    minutes = max(1, round(config.get("time_limit_s", 300) / 60))
    qa_minutes = max(1, round(config.get("qa_s", 120) / 60))
    parts = [
        (PROMPTS / "examiner_base.md").read_text(encoding="utf-8").strip(),
        f"You are {character['name']}. {character.get('persona', '')}",
        f"This is {SCENARIOS.get(config.get('scenario', ''), 'a project presentation')}: {minutes} minutes of "
        f"presentation, then {qa_minutes} minutes of questions.",
    ]
    if config.get("notes"):
        parts.append(f"The organiser asked you to focus on: {config['notes']}")
    parts.append("What you know about the slides:\n" + slide_digest(config))
    return "\n\n".join(parts)


def for_phase(config: dict, phase: str, discussed: list[str] | None = None) -> str:
    text = core(config) + "\n\n" + PHASES[phase]
    if discussed and phase == "qa":
        text += "\n\nAlready dealt with during the talk; do not raise these again: " + "; ".join(discussed)
    return text


def with_cue(config: dict, phase: str, cue: str, discussed: list[str] | None = None) -> str:
    """Per-response instructions: the whole system prompt plus what to do right now."""
    return for_phase(config, phase, discussed) + "\n\nRight now: " + cue
