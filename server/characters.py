"""Examiner characters: presets from demo/characters.json, plus custom free text."""

import json
from functools import cache

from config import DEMO_DIR

DEFAULT_PRESET = "supervisor"
MAX_CUSTOM_CHARS = 1500


@cache
def presets() -> dict[str, dict]:
    items = json.loads((DEMO_DIR / "characters.json").read_text(encoding="utf-8"))
    return {c["id"]: c for c in items}


def resolve_character(character: str, custom_text: str = "") -> dict:
    """`character` is a preset id. Free text (in `custom_text`, or in `character` when it is
    not a preset id) is appended to the base preset's persona, keeping its voice and avatar."""
    character, custom_text = character.strip(), custom_text.strip()
    if character not in presets():
        custom_text = f"{character}\n{custom_text}".strip()
        character = DEFAULT_PRESET
    result = dict(presets()[character])
    if custom_text:
        result["persona"] += f"\n\nCustom brief from the presenter: {custom_text[:MAX_CUSTOM_CHARS]}"
    return result
