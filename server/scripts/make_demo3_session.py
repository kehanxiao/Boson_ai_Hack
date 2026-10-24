"""Build demo/session-config-demo3.json: the fixed "demo3" session (3-slide GradeBook, demo of at most 3 minutes).

Source: demo/prepped-analysis-demo3.json (Haiku prep of demo/deck-demo3.pdf) + the Supervisor preset.
qa_s = 0: the agent skips Q&A and the verdict, so the demo is all presentation and interruptions.
No organiser notes (in testing, "check their edge cases" turned into "the assignment requires...").

Run from server/: uv run python scripts/make_demo3_session.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from characters import resolve_character  # noqa: E402
from config import DEMO_DIR  # noqa: E402
from instructions import build_instructions  # noqa: E402

SESSION_ID = "demo3"
SCENARIO = "assignment_oral"
TIME_LIMIT_S, QA_S = 180, 0
NOTES = ""


def main() -> None:
    slides = json.loads((DEMO_DIR / "prepped-analysis-demo3.json").read_text(encoding="utf-8"))
    for s in slides:
        s["image_url"] = f"/api/sessions/{SESSION_ID}/slides/{s['index']}.png"
    character = resolve_character("supervisor")
    config = {
        "session_id": SESSION_ID,
        "scenario": SCENARIO,
        "time_limit_s": TIME_LIMIT_S,
        "qa_s": QA_S,
        "notes": NOTES,
        "instructions": build_instructions(
            character=character, scenario=SCENARIO, time_limit_s=TIME_LIMIT_S, qa_s=QA_S,
            notes=NOTES, support_excerpt="", slides=slides,
        ),
        "character": character,
        "slides": slides,
    }
    out = DEMO_DIR / "session-config-demo3.json"
    out.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(slides)} slides)")


if __name__ == "__main__":
    main()
