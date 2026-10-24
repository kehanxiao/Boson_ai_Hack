# server/: Role B, FastAPI backend

Owns token minting, deck upload and prep, the session config the agent fetches, and the scorecard. API shapes are **fixed** by `PLAN.md` → "Interfaces between A and B". The sample responses are `demo/session-config.json` and `demo/sample-scorecard.json`.

Stack: uv, Python 3.12+, `fastapi`, `uvicorn`, `python-multipart`, `livekit-api` (token minting), `pymupdf` (PDF → PNG + text), `anthropic`, `python-dotenv`. Run: `uv run uvicorn main:app --port 8000`. Enable CORS for the Vite dev origin (`http://localhost:5173`).

## Endpoints (contract)
- `GET /token?room=&identity=` → `{url, token}`. A LiveKit AccessToken with roomJoin for `room`, publish/subscribe, and publish data. `url` = `LIVEKIT_URL`.
- `POST /api/sessions` (multipart) → `{session_id, slide_count}`.
  - Saves to `server/data/<session_id>/` (gitignored).
  - Renders slides to `slides/<n>.png` (1-based, ~2× scale) plus per-slide text.
  - Runs prep.
- `GET /api/sessions/{id}` → SessionConfig. Serve slide images so `image_url` resolves, e.g. `/api/sessions/{id}/slides/{n}.png`.
- `POST /api/sessions/{id}/agent` → `{ok: true}`: starts the examiner agent for the session (`agent_launcher.py`) unless LiveKit shows `viva-agent` already in the room, or one started here is still running. A presenter token request does the same. The agent's output goes to `agent/runs/agent-<id>-*.log`, and it leaves after `VIVA_AGENT_IDLE_EXIT_S` (300) with no presenter. `VIVA_AUTOSTART_AGENT=0` turns this off.
- `POST /api/sessions/{id}/log`: the agent uploads its JSONL log at the end, as the raw request body (`Content-Type: application/x-ndjson`). Save it as `server/data/<id>/log.jsonl` and return `{ok: true, lines: N}`.
- `GET /api/sessions/{id}/scorecard` → Scorecard (generated from the log + slide analysis, cached to disk).
- `session_id = "demo"` must always work, using the `demo/` sample files. This is a fallback if Haiku or the network fails.

## Prep (`prep.py`)
- **Per slide, in parallel:** Haiku (`VIVA_HAIKU_MODEL`, default `claude-haiku-5-5`) gets the slide PNG plus extracted text, and returns `{summary, claims[], weak_points[], questions[]}` through structured outputs (`output_config.format`).
  - Haiku 5.5 image support is assumed. Check it in K6; the fallback is a text-only prompt.
  - Keep each call small; use `max_tokens` around 1–2K.
- **Instructions:** `SessionConfig.instructions` is optional (contract, Fri 23:50). A builds the phase instructions in `agent/instructions.py` and reads only the supporting-document excerpt from this field (between `Supporting document (excerpt):` and `Slide digest:`), so keep those two markers. The server still fills it with a readable brief for debugging, independent of `agent/prompts/`.
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

## `POST /api/sessions` (built Fri 23:00, `session_create.py`)
- Pipeline: validate fields and PDF (≤ 30 MB, 1–40 pages) → `data/<id>/deck.pdf` → render → prep (Haiku) → `config.json` (SessionConfig) + `prep.json` (timing and per-slide errors, not part of the contract). About 3 s for 6 slides.
- `session_id` = `s` + 10 hex chars (also the LiveKit room name).
- **Character field:** `character` is a preset id. Optional free text (`custom_text`, or `character` itself when it isn't a preset id) is appended to the base preset's persona. With no preset given, the base is `supervisor`. `character.id` stays the base preset id. ⚠️ This is our reading of "`character` = preset id or `custom_text`"; confirm with A.
- **Instructions** (`instructions.py`): a fixed base brief + character + scenario + times + notes + support-doc excerpt (≤ 4000 chars) + a slide digest with weak points. Informational, except the support-doc excerpt, which the agent reads; it no longer reads `agent/prompts/`.
- If a slide's Haiku call fails, that slide falls back to its own text and the session is still created. If rendering fails, the folder is removed and the request returns 500.

## Scorecard (built Fri 23:30, `scorecard.py`)
- `GET /api/sessions/{id}/scorecard`: on the first request it generates from `log.jsonl` + `config.json` (Haiku, adaptive thinking, effort `medium`; **13–17 s**), caches to `scorecard.json`, and later requests return the cached copy. 404 until the log is uploaded; 502 if generation fails (not cached, so a retry works). Uploading a new log deletes the cached scorecard. `demo` always returns `sample-scorecard.json`.
- **Code owns what must be exact.** Quotes are checked against presenter log lines: `t`/`slide` come from the matching line, and quotes that aren't verbatim are dropped. `unacknowledged` moments come from `escalation` events (the presenter line between the reminder and the escalation). The four criteria names are fixed, scores are clamped to 1–5, and improvements are capped at 3.
- Timing facts (time used vs. limit, reminder/escalation/ack times) are computed from the log and given to the model; it doesn't do the arithmetic.
- Answering in another language never counts against the presenter (rule in the prompt; it was penalised before the rule).
- Presenter `chunk`s after the `debrief` phase are ignored (`exam_only`). In the first live run, the mic kept being transcribed during the verdict, including an STT hallucination from silence.
- CLI: `uv run python scorecard.py ../demo/sample-log.jsonl ../demo/session-config.json`.

## First live integration (Fri 23:55): web + server + A's agent (voice-only), headless
- Ran a full session in a fresh room: fake browser mic = TTS presenter track, Start → slides 2, 3 → Q&A → End. **Everything connected:** start handshake, greeting, presenter captions, slide changes, interjection, Q&A question, verdict, `ended`, log upload (27 lines), and a scorecard from the real log (14 s, all quotes verbatim). No browser console errors.
- `pause_to_interjection` arrived in the HUD: **2.4 s**.
- Fixed on the web side: voice-only audio comes from `viva-agent` (it was only played from `boson-avatar`), and "start" is re-sent every 2 s until the first `viva.ui` (the agent joins the room before it listens to `viva.ctl`).

## Built-in sessions (`fixed_sessions.py`, Sat 00:20)
- `demo` (ERwait, the contract examples) and `gradebook` (GradeBook, the demo-video deck, agreed with A) are served from `demo/` files: config, slides rendered from the deck PDF into `data/<id>/` at startup, and a log upload.
- Scorecard: `demo` always returns `sample-scorecard.json`. `gradebook` generates from the uploaded log like any other session (no sample to fall back on).
- `demo/session-config-coding.json` comes from `scripts/make_gradebook_session.py` (Supervisor, Assignment oral, 240 + 90 s); re-run it after regenerating `prepped-analysis-coding.json`. A's agent falls back to the same file when the server is down; so does the web app.
- `demo3` (A's 3-slide, 3-minute session with no Q&A, used for the demo video) is served the same way: `demo/session-config-demo3.json` from `scripts/make_demo3_session.py`, the deck from `scripts/make_demo3_deck.py`. The agent falls back to it too; the web app has no bundled copy.
- The scorecard drops a model "weak" moment on the same line as a code-detected "unacknowledged" one (it duplicated it in testing).
- ⚠️ **`uvicorn --reload` is unreliable on Windows here.** Twice it missed a change to `sessions.py`, and stopping it once left an orphaned worker still answering on port 8000 with old code. If behaviour doesn't match the code: stop every `uvicorn`/`multiprocessing.spawn` python process, then start without `--reload`.
- Deck scripts now fail loudly when text doesn't fit its box (`textbox()` in `make_placeholder_deck.py`). PyMuPDF silently dropped the GradeBook title before; deck, analysis and `gradebook` config were regenerated (all planted weaknesses still caught).
