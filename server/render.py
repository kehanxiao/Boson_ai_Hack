"""Render a slides PDF to PNGs plus per-slide text with PyMuPDF.

Output layout (inside out_dir):
    slides/<n>.png   1-based, rendered at `zoom`x (2x by default)
    slides.json      [{"index": n, "text": "..."}]

CLI: uv run python render.py ../demo/deck.pdf data/demo
"""

import json
import sys
from pathlib import Path

import pymupdf


def render_deck(pdf_path: Path, out_dir: Path, zoom: float = 2.0) -> list[dict]:
    slides_dir = out_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    matrix = pymupdf.Matrix(zoom, zoom)
    slides = []
    with pymupdf.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            page.get_pixmap(matrix=matrix).save(slides_dir / f"{index}.png")
            slides.append({"index": index, "text": page.get_text("text").strip()})
    (out_dir / "slides.json").write_text(
        json.dumps(slides, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return slides


def is_stale(pdf_path: Path, out_dir: Path) -> bool:
    """True when the render is missing or older than the PDF."""
    marker = out_dir / "slides.json"
    return not marker.exists() or marker.stat().st_mtime < pdf_path.stat().st_mtime


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python render.py <deck.pdf> <out_dir>")
    result = render_deck(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"rendered {len(result)} slides to {sys.argv[2]}")
