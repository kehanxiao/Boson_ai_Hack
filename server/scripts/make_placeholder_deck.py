"""Build a placeholder demo/deck.pdf from demo/deck-outline.md.

Stand-in until the real deck is exported from PowerPoint / Google Slides.
The planted weaknesses are deliberate (see the outline). Don't fix them.

Run from server/: uv run python scripts/make_placeholder_deck.py
"""

from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parents[2] / "demo" / "deck.pdf"
W, H = 720, 405  # 16:9 in points, same as a PowerPoint PDF export
INK, MUTED, ACCENT = (0.1, 0.12, 0.16), (0.38, 0.42, 0.48), (0.15, 0.38, 0.72)

FEATURES = [
    "Lagged wait times (1h, 2h, 4h, 24h, 168h)",
    "Rolling arrival counts by triage level (CTAS 1-5)",
    "Statutory holidays, long weekends and school holidays",
    "Temperature, precipitation, snowfall and heat warnings",
    "Triage mix share per hour",
    "Staffing: scheduled physicians and nurses per shift",
    "Time to first physician",
    "Hour of day, day of week, month (cyclic encodings)",
    "Ambulance offload delays",
    "Inpatient census and admitted-no-bed counts",
    "Flu and COVID surveillance signals (weekly)",
    "Local events: concerts, sports, marathons",
    "Hospital site one-hot and site-level random effects",
    "Interaction terms: triage mix x staffing, weather x hour",
]

SLIDES = [
    ("ERwait: Forecasting ER Wait Times",
     ["MScAC internship project", "Toronto hospital network (fictional)", "Presenter: Alex Chen"]),
    ("The Problem",
     ["Emergency room waits are long and unpredictable",
      "~1 in 20 patients leave without being seen",
      "Goal: forecast the next 4 hours of wait time, per hospital"]),
    ("Headline Result", []),
    ("Data",
     ["2 years of triage records: 1.2M visits",
      "Features include arrival time, triage level and time to first physician",
      "We removed outliers"]),
    ("Method",
     ["Gradient-boosted trees",
      "LightGBM (released by Google in 2020)",
      "Rolling-window validation"]),
    ("Feature Engineering", FEATURES),
    ("Deployment",
     ["Ready for deployment across all Ontario hospitals"]),
    ("Conclusion & Future Work",
     ["4-hour-ahead wait forecasts per hospital",
      "Strong headline result",
      "Future work: add real-time bed data"]),
]


def textbox(page: pymupdf.Page, rect: pymupdf.Rect, text: str, **kwargs) -> None:
    """insert_textbox silently drops text that doesn't fit (negative return); fail loudly instead."""
    spare = page.insert_textbox(rect, text, **kwargs)
    if spare < 0:
        raise ValueError(f"text doesn't fit ({-spare:.0f} pt short): {text[:50]!r}")


def title(page: pymupdf.Page, text: str, n: int) -> None:
    page.draw_rect(pymupdf.Rect(0, 0, W, 6), color=None, fill=ACCENT)
    textbox(page, pymupdf.Rect(48, 34, W - 48, 90), text, fontsize=28, fontname="hebo", color=INK)
    textbox(page, pymupdf.Rect(W - 80, H - 30, W - 24, H - 12), str(n), fontsize=10, color=MUTED, align=2)


def bullets(page: pymupdf.Page, lines: list[str], size: float, top: float = 105) -> None:
    text = "\n".join(f"-  {line}" for line in lines)  # base-14 Helvetica has no bullet glyph
    textbox(page, pymupdf.Rect(56, top, W - 56, H - 36), text, fontsize=size, color=INK, lineheight=1.35)


def headline(page: pymupdf.Page) -> None:
    # Planted: "40% better" with no baseline or metric, and a chart with no axis labels.
    textbox(page, pymupdf.Rect(48, 110, 380, 250), "Our model is\n40% better.", fontsize=40, fontname="hebo", color=ACCENT)
    base = H - 70
    for i, height in enumerate([170, 102]):
        x = 440 + i * 110
        page.draw_rect(pymupdf.Rect(x, base - height, x + 70, base), color=None, fill=MUTED if i == 0 else ACCENT)
    page.draw_line((420, base), (660, base), color=INK, width=1)


def main() -> None:
    doc = pymupdf.open()
    for n, (heading, lines) in enumerate(SLIDES, start=1):
        page = doc.new_page(width=W, height=H)
        if n == 1:
            textbox(page, pymupdf.Rect(48, 130, W - 48, 200), heading, fontsize=34, fontname="hebo", color=INK)
            textbox(page, pymupdf.Rect(48, 210, W - 48, 300), "\n".join(lines), fontsize=16, color=MUTED, lineheight=1.4)
            continue
        title(page, heading, n)
        if n == 3:
            headline(page)
        elif n == 6:
            bullets(page, lines, size=9.5, top=95)  # Planted: text-crammed slide.
        else:
            bullets(page, lines, size=20)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"wrote {OUT} ({len(SLIDES)} slides)")


if __name__ == "__main__":
    main()
