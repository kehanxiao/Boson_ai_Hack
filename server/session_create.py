"""POST /api/sessions: upload a deck, render it, run prep, save the SessionConfig.

Multipart fields (contract, PLAN.md): scenario, character, time_limit_s, qa_s, notes,
slides (PDF), optional support_doc. `custom_text` is optional free text for a custom character.
Response: {session_id, slide_count}. Takes a few seconds (prep runs before returning).
"""

import asyncio
import json
import logging
import secrets
import shutil
import time

import pymupdf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from characters import resolve_character
from config import DATA_DIR
from instructions import SCENARIOS, build_instructions
from prep import analyze_deck
from render import render_deck

router = APIRouter(prefix="/api/sessions")
log = logging.getLogger("viva.sessions")

MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_SUPPORT_BYTES = 10 * 1024 * 1024
MAX_SLIDES = 40
SUPPORT_EXCERPT_CHARS = 4000


async def read_limited(upload: UploadFile, limit: int, what: str) -> bytes:
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{what} is larger than {limit // (1024 * 1024)} MB")
    return data


def check_pdf(data: bytes) -> int:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise HTTPException(400, "slides PDF is password-protected")
            pages = doc.page_count
    except pymupdf.FileDataError as err:
        raise HTTPException(400, "slides must be a valid PDF") from err
    if not 1 <= pages <= MAX_SLIDES:
        raise HTTPException(400, f"slides PDF must have 1-{MAX_SLIDES} pages (got {pages})")
    return pages


def support_text(data: bytes, filename: str) -> str:
    """Plain text from a PDF or text file, trimmed to an excerpt."""
    if data[:5] == b"%PDF-" or filename.lower().endswith(".pdf"):
        try:
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                text = "\n".join(page.get_text("text") for page in doc)
        except pymupdf.FileDataError as err:
            raise HTTPException(400, "support_doc is not a readable PDF") from err
    else:
        text = data.decode("utf-8", errors="replace")
    return " ".join(text.split())[:SUPPORT_EXCERPT_CHARS]


@router.post("")
async def create_session(
    slides: UploadFile = File(...),
    scenario: str = Form(...),
    character: str = Form(...),
    time_limit_s: int = Form(..., ge=60, le=3600),
    qa_s: int = Form(..., ge=0, le=1800),
    notes: str = Form("", max_length=2000),
    custom_text: str = Form("", max_length=2000),
    avatar: bool = Form(True),
    support_doc: UploadFile | None = File(None),
) -> dict:
    if scenario not in SCENARIOS:
        raise HTTPException(400, f"scenario must be one of {sorted(SCENARIOS)}")
    pdf = await read_limited(slides, MAX_PDF_BYTES, "slides PDF")
    check_pdf(pdf)
    excerpt = ""
    if support_doc and support_doc.filename:
        excerpt = support_text(await read_limited(support_doc, MAX_SUPPORT_BYTES, "support_doc"), support_doc.filename)
    resolved = resolve_character(character, custom_text)

    session_id = "s" + secrets.token_hex(5)  # also the LiveKit room name
    session_dir = DATA_DIR / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "deck.pdf").write_bytes(pdf)

    started = time.perf_counter()
    context = f"Scenario: {SCENARIOS[scenario][0]}."
    if notes.strip():
        context += f" The presenter asked the examiner to focus on: {notes.strip()}"
    if excerpt:
        context += f"\nSupporting document (excerpt): {excerpt}"
    try:
        await asyncio.to_thread(render_deck, session_dir / "deck.pdf", session_dir)
        # Per-slide Claude failures don't raise: those slides fall back to their own text.
        analysed, errors = await analyze_deck(session_dir, session_id, context=context)
    except Exception:
        shutil.rmtree(session_dir, ignore_errors=True)  # no half-made sessions
        log.exception("session %s: render/prep failed", session_id)
        raise HTTPException(500, "could not prepare the deck") from None
    prep_s = round(time.perf_counter() - started, 1)

    config = {
        "session_id": session_id,
        "scenario": scenario,
        "time_limit_s": time_limit_s,
        "qa_s": qa_s,
        "notes": notes.strip(),
        "avatar": avatar,
        "instructions": build_instructions(
            character=resolved,
            scenario=scenario,
            time_limit_s=time_limit_s,
            qa_s=qa_s,
            notes=notes,
            support_excerpt=excerpt,
            slides=analysed,
        ),
        "character": resolved,
        "slides": analysed,
    }
    write_json(session_dir / "config.json", config)
    # Not part of SessionConfig: prep diagnostics for debugging and the README.
    write_json(session_dir / "prep.json", {"seconds": prep_s, "errors": errors})
    if errors:
        log.warning("session %s: %d slides fell back: %s", session_id, len(errors), errors)
    log.info("session %s: %d slides prepped in %.1fs", session_id, len(analysed), prep_s)
    return {"session_id": session_id, "slide_count": len(analysed)}


def write_json(path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
