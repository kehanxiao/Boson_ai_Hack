# server/: Role B, FastAPI backend

Owns token minting, deck upload and prep, the session config the agent fetches, and the scorecard. API shapes are **fixed** by `PLAN.md` → "Interfaces between A and B". The sample responses are `demo/session-config.json` and `demo/sample-scorecard.json`.

Stack: uv, Python 3.11+, `fastapi`, `uvicorn`, `python-multipart`, `livekit-api` (token minting), `pymupdf` (PDF → PNG + text), `anthropic`, `python-dotenv`. Run: `uv run uvicorn main:app --reload --port 8000`. Enable CORS for the Vite dev origin (`http://localhost:5173`).

## Endpoints (contract)
- `GET /token?room=&identity=` → `{url, token}`. A LiveKit AccessToken with roomJoin for `room`, publish/subscribe, and publish data. `url` = `LIVEKIT_URL`.
- `POST /api/sessions` (multipart) → `{session_id, slide_count}`.
  - Saves to `server/data/<session_id>/` (gitignored).
  - Renders slides to `slides/<n>.png` (1-based, ~2× scale) plus per-slide text.
  - Runs prep.
- `GET /api/sessions/{id}` → SessionConfig. Serve slide images so `image_url` resolves, e.g. `/api/sessions/{id}/slides/{n}.png`.
- `POST /api/sessions/{id}/log`: the agent uploads its JSONL log at the end, as the raw request body (`Content-Type: application/x-ndjson`). Save it as `server/data/<id>/log.jsonl` and return `{ok: true, lines: N}`.
- `GET /api/sessions/{id}/scorecard` → Scorecard (generated from the log + slide analysis, cached to disk).
- `session_id = "demo"` must always work, using the `demo/` sample files. This is a fallback if Haiku or the network fails.

## Prep (`prep.py`)
- **Per slide, in parallel:** Haiku (`VIVA_HAIKU_MODEL`, default `claude-haiku-5-5`) gets the slide PNG plus extracted text, and returns `{summary, claims[], weak_points[], questions[]}` through structured outputs (`output_config.format`).
  - Haiku 5.5 image support is assumed. Check it in K6; the fallback is a text-only prompt.
  - Keep each call small; use `max_tokens` around 1–2K.
- **Instructions:** assemble `agent/prompts/examiner_base.md` (owned by A) + the character persona (`demo/characters.json` or custom text) + scenario + time limit + notes + a compact per-slide digest.
- Claude calls use the official Anthropic Python SDK only. No OpenAI-compatible shims.

## Scorecard (`scorecard.py`)
- **Input:** the JSONL session log (format in `PLAN.md`) plus the slide analysis.
- **Output:** structured JSON matching `demo/sample-scorecard.json`.
- Every quote must come verbatim from the log. Moments carry `t` (seconds from start) and `slide`.

## K6 results (Fri 22:30, `prep.py`)
- **Pass.** 8 demo slides analysed in parallel in **2.9–7.5 s** (target < 60 s), 0 failures. Every planted weakness is caught: no baseline (3), leakage + unexplained outliers (4), LightGBM is Microsoft's (5), too dense (6), Ontario overclaim (7). The title slide gets no weak points.
- **Haiku 5.5 takes images** (Models API: `capabilities.image_input.supported = true`; in SDK 2.3 `capabilities` is a typed object, so use attribute access). `--text-only` also works (3.4 s).
- **Settings:** `messages.parse(output_format=SlideAnalysis)`, `thinking: adaptive`, `effort: low`, `max_tokens` 4096 (thinking counts toward it). Thinking disabled was about as good and slightly faster; adaptive reasoned a bit more carefully about leakage.
- **Density is flagged in code, not left to the model.** Haiku flagged the crammed slide only about 1 run in 2. Slides with more than `DENSE_LINES` (9) extracted lines now get a "Layout check" line in the prompt, which made it 3/3.
- Each prompt carries a whole-deck text outline, so cross-slide issues are caught (e.g. a slide-4 feature that leaks the slide-2 target).
- `demo/prepped-analysis.json` = the cached output, in `SessionConfig.slides` shape.
