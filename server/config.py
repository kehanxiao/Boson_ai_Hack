"""Paths and environment. Secrets come only from the repo-root .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parent
ROOT_DIR = SERVER_DIR.parent
DEMO_DIR = ROOT_DIR / "demo"
DATA_DIR = SERVER_DIR / "data"  # gitignored: uploads, rendered slides, logs

load_dotenv(ROOT_DIR / ".env")

WEB_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()
