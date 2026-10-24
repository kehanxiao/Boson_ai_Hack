"""Per-slide deck analysis with Claude Haiku (kill test K6).

Each slide is analysed in parallel: slide PNG + its extracted text + a text outline
of the whole deck (so e.g. a feature on slide 4 can be checked against the target on slide 2).
Output per slide matches SessionConfig.slides: {index, image_url, summary, claims, weak_points, questions}.

CLI (from server/, after render.py has produced <session_dir>/slides.json + slides/*.png):
    uv run python prep.py data/demo --out ../demo/prepped-analysis.json
"""

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

import anthropic
from pydantic import BaseModel

from config import env

MODEL = env("VIVA_HAIKU_MODEL", "claude-haiku-5-5")
MAX_TOKENS = 4096
OUTLINE_CHARS_PER_SLIDE = 400
DENSE_LINES = 9  # more extracted text lines than this (title and page number included) = too dense

SYSTEM = """You prepare an examiner for a live oral defense of a slide presentation.
You see one slide (image and extracted text) plus a text outline of the whole deck for context.

Return:
- summary: one sentence (max 30 words) saying what the slide shows and argues.
- claims: the slide's checkable or arguable claims, close to the slide's wording (0-4). Skip titles and scene-setting.
- weak_points: specific problems an expert examiner would press on (0-3). Look for: comparisons with no baseline or metric; results without evidence; features or data that could leak the prediction target; unexplained data cleaning; statements about the outside world that are factually wrong (check names, dates and organisations against your own knowledge and state what is actually true); claims that generalise beyond the evidence; charts without labels; slides too dense to present (more than about 7 bullets, or text too small for an audience to read in time: say so, and ask which few points matter most). One concrete sentence each. Leave the list empty when the slide has no real weakness; never invent problems.
- questions: short spoken questions the examiner could ask about this slide (0-3), most important first. Under 20 words each, no preamble."""


class SlideAnalysis(BaseModel):
    summary: str
    claims: list[str]
    weak_points: list[str]
    questions: list[str]


class PrepError(RuntimeError):
    pass


def deck_outline(slides: list[dict]) -> str:
    return "\n".join(
        f"Slide {s['index']}: {' '.join(s['text'].split())[:OUTLINE_CHARS_PER_SLIDE]}" for s in slides
    )


def image_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


async def analyze_slide(
    client: anthropic.AsyncAnthropic, slide: dict, outline: str, image: Path | None, context: str
) -> SlideAnalysis:
    lines = [line for line in slide["text"].splitlines() if line.strip()]
    stats = f"{len(lines)} text lines, {len(slide['text'].split())} words"
    # The model flags density inconsistently (K6: about 1 run in 2), so measured density is stated as a fact.
    dense = (
        f"\nLayout check: {len(lines)} lines of text is too dense to present; include that as a weak point."
        if len(lines) > DENSE_LINES
        else ""
    )
    prompt = (
        f"{context}\n\nDeck outline:\n{outline}\n\n"
        f"Analyse slide {slide['index']} ({stats}).{dense} Its extracted text:\n{slide['text'] or '(no text)'}"
    ).strip()
    content = ([image_block(image)] if image else []) + [{"type": "text", "text": prompt}]
    response = await client.messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        # K6: adaptive thinking at low effort reasons a bit more carefully about leakage than
        # thinking disabled, and still finishes 8 slides in ~4-8 s. Thinking counts toward MAX_TOKENS.
        thinking={"type": "adaptive"},
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": content}],
        output_format=SlideAnalysis,
    )
    if response.stop_reason == "refusal":
        raise PrepError(f"slide {slide['index']}: refused ({response.stop_details})")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise PrepError(f"slide {slide['index']}: no complete analysis (stop_reason={response.stop_reason})")
    return response.parsed_output


def fallback(slide: dict) -> SlideAnalysis:
    """Used when a slide's call fails: keeps the session usable with the slide's own text."""
    first_line = next((line for line in slide["text"].splitlines() if line.strip()), f"Slide {slide['index']}")
    return SlideAnalysis(summary=first_line.strip(), claims=[], weak_points=[], questions=[])


async def analyze_deck(
    session_dir: Path, session_id: str, context: str = "", use_images: bool = True
) -> tuple[list[dict], list[str]]:
    """Returns (slides in SessionConfig shape, error messages for slides that fell back)."""
    slides = json.loads((session_dir / "slides.json").read_text(encoding="utf-8"))
    outline = deck_outline(slides)
    async with anthropic.AsyncAnthropic() as client:
        results = await asyncio.gather(
            *(
                analyze_slide(
                    client,
                    s,
                    outline,
                    session_dir / "slides" / f"{s['index']}.png" if use_images else None,
                    context,
                )
                for s in slides
            ),
            return_exceptions=True,
        )

    analysed, errors = [], []
    for slide, result in zip(slides, results):
        if isinstance(result, BaseException):
            errors.append(f"slide {slide['index']}: {type(result).__name__}: {result}")
            result = fallback(slide)
        analysed.append(
            {"index": slide["index"], "image_url": f"/api/sessions/{session_id}/slides/{slide['index']}.png"}
            | result.model_dump()
        )
    return analysed, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse a rendered deck with Claude Haiku.")
    parser.add_argument("session_dir", type=Path, help="folder with slides.json and slides/<n>.png")
    parser.add_argument("--session-id", help="defaults to the folder name")
    parser.add_argument("--out", type=Path, help="write the slides JSON here")
    parser.add_argument("--text-only", action="store_true", help="skip slide images")
    args = parser.parse_args()

    started = time.perf_counter()
    slides, errors = asyncio.run(
        analyze_deck(args.session_dir, args.session_id or args.session_dir.name, use_images=not args.text_only)
    )
    elapsed = time.perf_counter() - started

    for s in slides:
        print(f"\n[{s['index']}] {s['summary']}")
        for w in s["weak_points"]:
            print(f"    weak: {w}")
        for q in s["questions"][:1]:
            print(f"    ask:  {q}")
    print(f"\n{len(slides)} slides in {elapsed:.1f}s with {MODEL}; {len(errors)} failed")
    for e in errors:
        print(f"  ! {e}")
    if args.out:
        args.out.write_text(json.dumps(slides, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
