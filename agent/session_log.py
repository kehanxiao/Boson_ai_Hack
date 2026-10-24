"""The session log: JSONL in the format of demo/sample-log.jsonl (part of the A/B contract)."""

import json
import logging
import pathlib
import time

import requests

log = logging.getLogger("viva.log")


class SessionLog:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self.t0: float | None = None

    def start(self) -> None:
        self.t0 = time.monotonic()

    def t(self) -> float:
        return round(time.monotonic() - self.t0, 2) if self.t0 is not None else 0.0

    def write(self, kind: str, **fields) -> dict:
        entry = {"t": self.t(), "kind": kind, **fields}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def upload(self, server_url: str, session_id: str) -> None:
        """POST the log as the raw request body (application/x-ndjson)."""
        try:
            r = requests.post(
                f"{server_url}/api/sessions/{session_id}/log",
                data=self.path.read_bytes(),
                headers={"Content-Type": "application/x-ndjson"},
                timeout=30,
            )
            log.info("log upload: HTTP %s %s", r.status_code, r.text[:120])
        except requests.RequestException as exc:
            log.warning("log upload failed (%s); the log is still at %s", exc, self.path)
