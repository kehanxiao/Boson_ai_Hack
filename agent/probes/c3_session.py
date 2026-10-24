"""C3 check, part 1: create an unseen session through the server, as the Setup page does.

Uploads a deck with a preset character plus a custom free-text brief and a supporting document, so the
server runs a fresh prep (not the cached analysis). Prints the session id and what the agent will see.
Part 2 runs the exam on it: uv run probes/exam_sim.py gradebook --session <id>

    cd agent && uv run probes/c3_session.py [deck.pdf]
"""

import json
import os
import pathlib
import sys
import time

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import instructions as prompts  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SERVER = os.environ.get("VIVA_SERVER_URL", "http://localhost:8000")
BRIEF = """Intro to Programming, Assignment 2: GradeBook.
Requirements: read names and scores from grades.csv, sort the students by score from highest to lowest,
print the top 10 students and the class average. The program must skip a header row if there is one.
Report: compare your sort's runtime against Python's built-in sorted() on the same data, over at least
five timed runs, and say which hardware you used."""


def main() -> None:
    deck = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "demo" / "deck-coding.pdf"
    started = time.perf_counter()
    r = requests.post(f"{SERVER}/api/sessions", timeout=180, files={
        "slides": (deck.name, deck.read_bytes(), "application/pdf"),
        "support_doc": ("assignment-brief.txt", BRIEF.encode(), "text/plain"),
    }, data={
        "scenario": "assignment_oral", "character": "skeptic", "time_limit_s": 240, "qa_s": 90,
        "notes": "Check that they met the assignment brief.",
        "custom_text": "A former industry engineer: keeps asking how the code would behave on real, messy data.",
    })
    r.raise_for_status()
    session_id = r.json()["session_id"]
    config = requests.get(f"{SERVER}/api/sessions/{session_id}", timeout=10).json()
    character = config["character"]
    print(f"session {session_id}: {len(config['slides'])} slides prepped in {time.perf_counter() - started:.1f} s")
    print(f"character: {character['name']} (interrupt_rate {character.get('interrupt_rate')}, "
          f"strictness {character.get('strictness')}, avatar {character.get('avatar_id')})")
    print(f"custom brief in persona: {'messy data' in character.get('persona', '')}")
    print(f"supporting document reaches the agent: {'five timed runs' in prompts.support_excerpt(config)}")
    weak = sum(len(s.get("weak_points", [])) for s in config["slides"])
    print(f"weak points: {weak}; questions: {len(prompts.qa_questions(config))}")
    print(json.dumps({"session_id": session_id}))


if __name__ == "__main__":
    main()
