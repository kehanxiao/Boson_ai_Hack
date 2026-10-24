"""Download the third-party docs this project relies on into docs/vendor/ (gitignored).

Run once per machine:  python docs/fetch_vendor_docs.py

Claude Code should read these local copies instead of re-fetching pages from the web.
Boson docs are fetched as raw markdown; tutorial files come from the
`realtime-1.5-preview` branch of boson-ai/higgs-realtime-tutorial (Apache-2.0).
"""

import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent / "vendor"

BOSON = "https://docs.boson.ai/"
BOSON_PAGES = [
    "models/higgs-realtime/overview.md",
    "models/higgs-realtime/quickstart.md",
    "models/higgs-realtime/guides/connections-and-sessions.md",
    "models/higgs-realtime/guides/audio-and-voices.md",
    "models/higgs-realtime/guides/turn-detection-and-interruptions.md",
    "models/higgs-realtime/guides/tool-calling.md",
    "api-reference/realtime/overview.md",
    "api-reference/realtime/client-secrets.md",
    "api-reference/realtime/client-events.md",
    "api-reference/realtime/server-events.md",
    "models/higgs-avatar/overview.md",
    "models/higgs-avatar/realtime-sessions.md",
    "models/higgs-avatar/input-options.md",
    "api-reference/avatar-realtime/overview.md",
    "api-reference/avatar-realtime/create-a-session.md",
    "api-reference/avatar-realtime/retrieve-a-session.md",
    "api-reference/avatar-realtime/release-a-session.md",
    "api-reference/avatar-realtime/list-avatars.md",
    "models/higgs-tts/overview.md",
    "models/higgs-tts/voices.md",
    "models/higgs-tts/languages.md",
    "models/higgs-tts/tags.md",
    "account-billing/usage-and-limits.md",
    "api-reference/errors.md",
]

TUTORIAL = "https://raw.githubusercontent.com/boson-ai/higgs-realtime-tutorial/realtime-1.5-preview/"
TUTORIAL_FILES = [
    "README.md",
    "LICENSE",
    "docs/part-2.md",
    "docs/part-3.md",
    "docs/part-4.md",
    "docs/part-7.md",
    "livekit/agent.py",
    "livekit/server_tools.py",
    "livekit/tools.py",
    "livekit/probe.py",
    "livekit/pyproject.toml",
    "livekit/.env.example",
    "server/index.ts",
    "src/realtime/RealtimeClient.ts",
    "src/realtime/events.ts",
    "src/realtime/sessionConfig.ts",
    "src/state/transcriptStore.ts",
    "tools/probe.ts",
]


def fetch(url: str, dest: pathlib.Path) -> bool:
    # docs.boson.ai answers 403 to urllib's default User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8.0 (viva fetch_vendor_docs)"})
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            data = resp.read()
    except Exception as exc:  # network errors should not abort the whole run
        print(f"  FAILED {url}: {exc}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def main() -> int:
    failures = 0
    for page in BOSON_PAGES:
        failures += not fetch(BOSON + page, ROOT / "boson" / page)
    for path in TUTORIAL_FILES:
        failures += not fetch(TUTORIAL + path, ROOT / "higgs-realtime-tutorial" / path)
    total = len(BOSON_PAGES) + len(TUTORIAL_FILES)
    print(f"Saved {total - failures}/{total} files under {ROOT}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
