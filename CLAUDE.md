# Viva: AI examiner for presentation defenses

Hackathon project for the Boson AI × MScAC Higgs Audio Hackathon. **The form closes Sat Oct 24, 14:00: submit by 13:50.** Then the 15:00 group round and the 17:00 finals.
A presenter defends their slides; an avatar examiner (Higgs Realtime + Higgs Avatar) listens, knows the current slide, interrupts at the right moment, holds the floor, keeps time, fact-checks claims, runs Q&A (code-switching allowed) and produces a scorecard.

## Source of truth
- **`PLAN.md`**: design decisions, stages and checkpoints (C0–C6), risks. Read the relevant section before starting a task.
- **"Interfaces between A and B" in `PLAN.md` is a contract.** Don't change it unilaterally. If a change is unavoidable, update that section **and** the matching `demo/*.json` sample files in the same commit, and tell the other person.

## Roles and ownership
| Role | Owns | Notes |
|---|---|---|
| **A**: agent/runtime | `agent/` (incl. `agent/prompts/`) | `agent/CLAUDE.md` |
| **B**: web + server + content | `server/`, `web/`, `demo/` content | `server/CLAUDE.md`, `web/CLAUDE.md` |

Don't edit the other role's folder without asking. The agent assembles the examiner's instructions itself (`agent/instructions.py` + `agent/prompts/`). From the server's `instructions` field it reads only the supporting-document excerpt.

## Key facts
- Realtime model **`higgs-realtime-1.5-preview`** (hackathon preview) at `wss://api.boson.ai/v1/realtime`. The GA fallback `higgs-realtime` is selected via `BOSON_REALTIME_MODEL`. User-speech captions come from `higgs-stt-3.1`.
- Higgs Avatar realtime sessions need **LiveKit Cloud** (self-hosted is refused) and use **preset avatars only**: `builtin_claire_v1`, `builtin_emma_v1`, `builtin_james_v1`.
- Claude calls go through the official Anthropic SDK, model `claude-haiku-5-5` (`VIVA_HAIKU_MODEL`). Use structured outputs (`output_config.format`) for JSON.
- Identities: room name = `session_id`. Agent `viva-agent`, avatar `boson-avatar`, presenter `presenter`.
- Secrets live only in `.env` (see `.env.example`). Never print or commit keys.

## Docs: read locally, don't re-fetch
Run `python docs/fetch_vendor_docs.py` once per machine. It fills the gitignored `docs/vendor/`:
- `docs/vendor/boson/…`: raw markdown of the Realtime / Avatar / TTS docs and API reference.
- `docs/vendor/higgs-realtime-tutorial/…`: tutorial files from the `realtime-1.5-preview` branch. This branch is the only place the 1.5 preview is documented.

Search these with Grep and read only the section you need.

## Token hygiene (both roles)
- Never read raw Realtime event dumps. Audio events carry base64. Logs are one line per event, with audio payloads dropped.
- One task per conversation; `/clear` between unrelated tasks.
- Prefer small files and targeted reads (Grep, or Read with offset/limit) over whole-file reads.
- Screenshots only when layout matters.

## Git
- Small commits, `git pull --rebase` before pushing.
- Tag checkpoints: `mvp` (C2), `v1` (C3), `rc` (C4), `submission` (C6).
- The repo becomes public for judging: no secrets, and keep README "Known limitations" honest.
