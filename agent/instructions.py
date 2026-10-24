"""Instructions for the examiner's two Higgs sessions, per phase, from prompts/ and the SessionConfig.

- The brain (brain.py) hears the presenter and decides what she does: brain(config, phase).
- The voice speaks the brain's lines and runs web searches: for_phase() and with_cue().

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

PHASES = {  # the voice
    "presentation": (
        "Phase: the presentation is running. Stay silent while the presenter talks. You only speak when you are "
        "explicitly told to, and then you say exactly the words you are given. After a web search, say what you "
        "found in one or two short spoken sentences."
    ),
    "qa": (
        "Phase: questions and answers. The presentation is over. You only speak when you are told to, and then you "
        "say exactly the words you are given. Do not search the web now: the fact-checks are done."
    ),
    "debrief": "Phase: debrief. The examination is over. Say exactly the words you are given.",
}

INTERRUPT_STYLE = {
    "high": "She cuts in often: for anything false, vague or unsupported, small things included.",
    "medium": "She cuts in when something matters: a false statement, a contradiction, a claim with no evidence. "
              "Small things wait for the questions.",
    "low": "She rarely cuts in: only for a clearly false statement or a serious contradiction.",
}

BRAIN_PHASES = {
    "presentation": """Right now the presentation is running.
She cuts in (SAY) when the presenter says something false or wrong (anything, from their introduction on); contradicts their slides or something they said earlier; makes a claim with no evidence, baseline or metric; rambles or drifts off the point; asks her something ("May I start?", "Can I go on?", "Can you repeat that?"); answers her question badly (push back once and name what is missing; if the answer is right, a short "Okay, go on." or SILENT; while they are still in the middle of answering, an unfinished sentence or "give me a moment", SILENT: let them finish); moves on without answering her question (insist); or talks over her (insist on finishing, or respond to what they said).
CHECK is for a checkable fact about the outside world that looks wrong (who made a tool, what algorithm a library uses, a date, a published number): she says "let me check" and searches the web, so the presenter sees the evidence. She never corrects such a fact from memory, even when she is sure: if your SAY would correct a fact about the outside world (an algorithm a library uses, who made something, a date, a number), answer CHECK: <their claim> instead.
One point per SAY: never pile several issues into one line; the others can come later. Hold the presenter only to what they said, never to what she said, and never to a slide they haven't talked about yet: wait until they make the claim. For example, if the slide says "our model is 40% better" and they have only said "here are our results", answer SILENT; they are about to say it.
SILENT for correct statements, filler ("um, so, yeah"), ordinary presenting, and small things that can wait for the questions. Most of the time the answer is SILENT.

Answer with exactly one line, in one of these three forms, and nothing else:
SILENT
SAY: <her words>
CHECK: <the claim to look up>
For example: "SILENT", or "SAY: Hang on. Better than what? What's your baseline?", or "CHECK: TensorFlow was released by Meta in 2019". Never explain your choice.""",
    "qa": """Right now it is question time: the talk is over and she leads the questioning for about {qa_minutes}.
Ask first about anything they never answered properly during the talk. Then the slides' weak points that haven't come up yet, most important first. Never re-ask a point that was settled during the talk.
Each turn: react to their answer in a few words (accept it, or say what is still wrong or missing), then ask the next question, at most 20 words. Repeat or rephrase the question when they ask; answer a clarifying question; press once on a vague answer. Never ask the same thing twice. No web searches now.

Answer with exactly one line, in one of these three forms, and nothing else:
SILENT  (they are still in the middle of answering, or thinking: wait)
SAY: <her words>
END: <her words>  (when she has asked enough, about three or four questions, or a note says time is up: a short reaction to their last answer, then "That's all my questions.")
For example: "SILENT", or "SAY: Fair enough. So what happens with an empty file?", or "END: Okay, noted. That's all my questions." Never explain your choice.""",
}

SUPPORT_HEADER = "Supporting document (excerpt):\n"  # as server/instructions.py writes it


def support_excerpt(config: dict) -> str:
    """The optional supporting document (a report, the assignment brief) the presenter uploaded. The server puts
    it only inside SessionConfig.instructions, which the agent otherwise ignores, so it is read from there."""
    text = config.get("instructions") or ""
    start = text.find(SUPPORT_HEADER)
    if start < 0:
        return ""
    body = text[start + len(SUPPORT_HEADER):]
    end = body.find("\n\nSlide digest:")
    return (body[:end] if end >= 0 else body).strip()


def slide_line(slide: dict) -> str:
    line = f"Slide {slide['index']}: {slide.get('summary', '')}"
    if slide.get("weak_points"):
        line += " Weak points: " + "; ".join(slide["weak_points"])
    return line


def slide_digest(config: dict) -> str:
    return "\n".join(slide_line(slide) for slide in config.get("slides", []))


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
    if support_excerpt(config):
        parts.append("The presenter's supporting document (excerpt):\n" + support_excerpt(config))
    parts.append("What you know about the slides:\n" + slide_digest(config))
    return "\n\n".join(parts)


def for_phase(config: dict, phase: str) -> str:
    return core(config) + "\n\n" + PHASES[phase]


def with_cue(config: dict, phase: str, cue: str) -> str:
    """Per-response instructions for the voice: the whole system prompt plus what to do right now."""
    return for_phase(config, phase) + "\n\nRight now: " + cue


def say_exactly(line: str) -> str:
    return f"Say exactly this, word for word, and nothing else: \"{line}\""


def qa_questions(config: dict) -> list[str]:
    """Candidate questions from the slide analysis: the main one of each weak slide, then second ones."""
    weak = [s for s in config.get("slides", []) if s.get("weak_points") and s.get("questions")]
    return list(dict.fromkeys([s["questions"][0] for s in weak] + [q for s in weak for q in s["questions"][1:2]]))[:8]


def brain(config: dict, phase: str) -> str:
    """The brain's instructions: who she is, what she knows, how she talks, and what to answer in this phase."""
    character = config["character"]
    minutes = max(1, round(config.get("time_limit_s", 300) / 60))
    qa_s = config.get("qa_s", 120)
    qa_minutes = f"{qa_s // 60} minutes" if qa_s % 60 == 0 else f"{qa_s / 60:.1f} minutes"
    # The format must come first: with only the closing format block, Higgs wrote the spoken line without
    # its tag 8-10 times in 10 (probes/higgs_brain.py --prompt-file ablation); with this line first, 0 in 10.
    tags = "SILENT, SAY: or CHECK:" if phase == "presentation" else "SILENT, SAY: or END:"
    parts = [
        f"Every answer you give is exactly one line that starts with {tags}",
        (PROMPTS / "brain.md").read_text(encoding="utf-8").strip(),
        f"She is {character['name']}. {character.get('persona', '')} "
        + INTERRUPT_STYLE.get(character.get("interrupt_rate", "medium"), INTERRUPT_STYLE["medium"]),
        f"This is {SCENARIOS.get(config.get('scenario', ''), 'a project presentation')}: {minutes} minutes of "
        f"presentation, then {qa_minutes} of questions. Time reminders are handled for her.",
    ]
    if config.get("notes"):
        parts.append(f"The organiser asked her to focus on: {config['notes']}")
    if support_excerpt(config):
        # A claim in the talk that contradicts the presenter's own document is worth a cut-in.
        parts.append("The presenter's supporting document, which she has read (excerpt):\n" + support_excerpt(config))
    if phase == "presentation":
        # One slide at a time, as it is shown: knowing every slide's weak points from the start, the brain raised
        # claims from later slides before the presenter had made them ("You said bug-free..." on slide 5).
        parts.append("A note says when the presenter moves to a slide. Its content and weak points come in a second "
                     "note once they have talked about it for a few seconds. Judge what they say against the slides "
                     "you know so far.")
    else:
        parts.append("The slides:\n" + slide_digest(config))
    task = BRAIN_PHASES[phase]
    if phase == "qa":
        # No prepared question list: with one, she re-asked "why bubble sort over sorted()?" a third time although
        # it was settled in the talk (live run, Sat 04:28). The weak points are in the slides above.
        task = task.format(qa_minutes=qa_minutes)
    parts.append(task)
    return "\n\n".join(parts)
