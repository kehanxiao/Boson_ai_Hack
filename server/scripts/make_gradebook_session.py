"""Build demo/session-config-coding.json: the fixed "gradebook" session (demo video deck).

Source: demo/prepped-analysis-coding.json (cached Haiku prep of demo/deck-coding.pdf) +
the Supervisor preset. Re-run after regenerating the analysis.

Run from server/: uv run python scripts/make_gradebook_session.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from characters import resolve_character  # noqa: E402
from config import DEMO_DIR  # noqa: E402
from instructions import build_instructions  # noqa: E402

SESSION_ID = "gradebook"
SCENARIO = "assignment_oral"
TIME_LIMIT_S, QA_S = 240, 90
NOTES = "Check that they understand algorithm complexity and have tested their edge cases."


def main() -> None:
    slides = json.loads((DEMO_DIR / "prepped-analysis-coding.json").read_text(encoding="utf-8"))
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
    out = DEMO_DIR / "session-config-coding.json"
    out.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(slides)} slides)")


if __name__ == "__main__":
    main()
