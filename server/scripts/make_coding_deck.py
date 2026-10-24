"""Build demo/deck-coding.pdf: an easy 6-slide intro-programming assignment for demos.

Outline, planted weaknesses and presenter script: demo/deck-coding-outline.md.
The weaknesses are deliberate (examiner targets). Don't fix them.

Run from server/: uv run python scripts/make_coding_deck.py
"""

from pathlib import Path

import pymupdf

from make_placeholder_deck import ACCENT, H, INK, MUTED, W, bullets, title

OUT = Path(__file__).resolve().parents[2] / "demo" / "deck-coding.pdf"
CODE_BG = (0.11, 0.13, 0.17)
CODE_INK = (0.86, 0.89, 0.93)

# Planted: hard to read on a slide, and it crashes on a header row or an empty file.
CODE = """import csv

def bubble_sort(rows):
    n = len(rows)
    for i in range(n):
        for j in range(0, n - i - 1):
            if rows[j][1] < rows[j + 1][1]:
                rows[j], rows[j + 1] = rows[j + 1], rows[j]
    return rows

def load(path):
    rows = []
    with open(path) as f:
        for name, score in csv.reader(f):
            rows.append((name, int(score)))
    return rows

rows = bubble_sort(load("grades.csv"))
print("Top 10:", rows[:10])
print("Average:", sum(s for _, s in rows) / len(rows))"""

SLIDES = [
    ("GradeBook: Ranking Student Grades in Python",
     ["Intro to Programming, Assignment 2", "Presenter: Sam Lee"]),
    ("The Task",
     ["Read a CSV file of student names and scores",
      "Sort students from highest to lowest score",
      "Print the top 10 and the class average"]),
    ("Our Approach",
     ["We wrote our own bubble sort",
      "Bubble sort is the fastest sorting algorithm: O(n log n)",
      "Python's built-in sorted() uses quicksort, so ours is just as good"]),
    ("The Code", []),
    ("Results", []),
    ("Testing & Conclusion",
     ["Tested on 3 CSV files: all worked",
      "The program is bug-free",
      "Ready for any school to use"]),
]


def code_slide(page: pymupdf.Page) -> None:
    box = pymupdf.Rect(48, 92, W - 48, H - 30)
    page.draw_rect(box, color=None, fill=CODE_BG, radius=0.03)
    page.insert_textbox(box + (14, 10, -14, -8), CODE, fontsize=9.2, fontname="cour", color=CODE_INK, lineheight=1.18)


def results_slide(page: pymupdf.Page) -> None:
    # Planted: "5x faster" with no baseline or input size, and a chart with no labels.
    page.insert_textbox(pymupdf.Rect(48, 110, 380, 250), "5x faster!", fontsize=44, fontname="hebo", color=ACCENT)
    page.insert_textbox(pymupdf.Rect(48, 190, 380, 260), "Sorted 500 students in 0.2 seconds", fontsize=16, color=MUTED)
    base = H - 70
    for i, height in enumerate([180, 36]):
        x = 440 + i * 110
        page.draw_rect(pymupdf.Rect(x, base - height, x + 70, base), color=None, fill=MUTED if i == 0 else ACCENT)
    page.draw_line((420, base), (660, base), color=INK, width=1)


def main() -> None:
    doc = pymupdf.open()
    for n, (heading, lines) in enumerate(SLIDES, start=1):
        page = doc.new_page(width=W, height=H)
        if n == 1:
            page.insert_textbox(pymupdf.Rect(48, 130, W - 48, 210), heading, fontsize=32, fontname="hebo", color=INK)
            page.insert_textbox(pymupdf.Rect(48, 230, W - 48, 300), "\n".join(lines), fontsize=16, color=MUTED, lineheight=1.4)
            continue
        title(page, heading, n)
        if heading == "The Code":
            code_slide(page)
        elif heading == "Results":
            results_slide(page)
        else:
            bullets(page, lines, size=20)
    doc.save(OUT)
    print(f"wrote {OUT} ({len(SLIDES)} slides)")


if __name__ == "__main__":
    main()
