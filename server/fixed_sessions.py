"""Built-in sessions served from demo/ files, so they work without an upload.

- "demo": the ERwait deck. Its files are the A<->B contract examples; the scorecard is always the sample.
- "gradebook": the easy GradeBook deck used for the demo video. Its scorecard is generated from the
  real session log like any other session (there is no sample to fall back on).
Generated session ids are "s" + hex, so they never collide with these names.
"""

from pathlib import Path

from config import DATA_DIR, DEMO_DIR
from render import is_stale, render_deck

FIXED = {
    "demo": {"config": "session-config.json", "deck": "deck.pdf", "scorecard": "sample-scorecard.json"},
    "gradebook": {"config": "session-config-coding.json", "deck": "deck-coding.pdf", "scorecard": None},
    # A's 3-slide demo (scripts/make_demo3_deck.py): 3 minutes, no Q&A (qa_s 0), at most 3 minutes of video.
    "demo3": {"config": "session-config-demo3.json", "deck": "deck-demo3.pdf", "scorecard": None},
}


def fixed_file(session_id: str, kind: str) -> Path | None:
    name = FIXED.get(session_id, {}).get(kind)
    return DEMO_DIR / name if name else None


def render_fixed_decks() -> None:
    """Keep data/<id>/slides in sync with each built-in deck PDF."""
    for session_id, files in FIXED.items():
        pdf, out = DEMO_DIR / files["deck"], DATA_DIR / session_id
        if pdf.exists() and is_stale(pdf, out):
            render_deck(pdf, out)
