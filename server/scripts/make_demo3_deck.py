"""Build demo/deck-demo3.pdf: GradeBook in 3 slides, for a demo of at most 3 minutes (session "demo3").

The weaknesses are deliberate (examiner targets). Don't fix them. Script: docs/demo-script-3min.md.

Run from server/: uv run python scripts/make_demo3_deck.py
"""

from pathlib import Path

import pymupdf

from make_coding_deck import results_slide
from make_placeholder_deck import H, INK, MUTED, W, bullets, textbox, title

OUT = Path(__file__).resolve().parents[2] / "demo" / "deck-demo3.pdf"

TASK = [
    "Read a CSV file of student names and scores",
    "Sort students from highest to lowest score",
    "Print the top 10 and the class average",
]
APPROACH = [  # planted: bubble sort is O(n^2) and slow; sorted() uses Timsort
    "We wrote our own bubble sort",
    "Bubble sort is the fastest sorting algorithm: O(n log n)",
    "Python's built-in sorted() uses quicksort, so ours is just as good",
]
CONCLUSION = [  # planted: three files can't show "bug-free"
    "Tested on 3 CSV files: all worked",
    "The program is bug-free and ready for any school",
]


def main() -> None:
    doc = pymupdf.open()

    page = doc.new_page(width=W, height=H)  # 1: title and task
    textbox(page, pymupdf.Rect(48, 40, W - 48, 100), "GradeBook: Ranking Student Grades in Python",
            fontsize=26, fontname="hebo", color=INK)
    textbox(page, pymupdf.Rect(48, 100, W - 48, 135), "Intro to Programming, Assignment 2  -  Presenter: Sam Lee",
            fontsize=15, color=MUTED)
    textbox(page, pymupdf.Rect(48, 175, W - 48, 207), "The task", fontsize=18, fontname="hebo", color=INK)
    bullets(page, TASK, size=18, top=212)

    page = doc.new_page(width=W, height=H)  # 2: approach
    title(page, "Our Approach", 2)
    bullets(page, APPROACH, size=20)

    page = doc.new_page(width=W, height=H)  # 3: results and conclusion
    title(page, "Results & Conclusion", 3)
    results_slide(page)  # "5x faster!", 500 students in 0.2 s, an unlabeled two-bar chart
    # base-14 Helvetica has no bullet glyph, hence "-"
    textbox(page, pymupdf.Rect(48, 270, 400, H - 30), "\n".join(f"-  {line}" for line in CONCLUSION),
            fontsize=15, color=INK, lineheight=1.5)

    doc.save(OUT)
    print(f"wrote {OUT} (3 slides)")


if __name__ == "__main__":
    main()
