# Viva: an AI examiner for presentation defenses (Higgs Audio Hackathon build plan)

> **Status (Fri 21:55):**
> - **A: C0 passed.** Avatar + `higgs-realtime-1.5-preview` working.
> - **K1–K4 passed (headless)**, and K5 is done:
>   - Turn mode can't change mid-session, so we use manual turns throughout (design decision 4 revised).
>   - Code-switching works.
>   - Web search fact-checking works but needs prompt tuning.
> - Details in `agent/CLAUDE.md`. **C1 go/no-go: GO** on the primary design.
> - **Next for A:** Stage 2 (VAD commits, director, floor policy), which needs `ANTHROPIC_API_KEY` in `.env`.
> - **B: K6 passed** (prep: 8 slides in ~4 s, all planted weaknesses caught; `demo/prepped-analysis.json` written). Details in `server/CLAUDE.md`.
> - **B: Stage 0 done.** `server/` (FastAPI via uv: `/token`, `GET /api/sessions/{id}` + slide PNGs + scorecard for `demo`) and `web/` (Vite + React + TS + livekit-client) are scaffolded. The `Session` page works against the fake agent at `/session/demo?fake=1`. `demo/deck.pdf` is a generated **placeholder** (`server/scripts/make_placeholder_deck.py`); replace it with the real export.
> - This file is the single source of truth. Update the status line when a checkpoint passes.

## Context
- **Event:** Boson AI × MScAC Higgs Audio Hackathon. Kickoff Fri Oct 23, 6 PM. **Submission deadline Sat 2 PM** (opening-ceremony slides p20-21), then a 3 PM group round (10 min incl. questions, peers vote) and 5 PM finals (10 min + Q&A, judges choose). Team of 2. About 18 hours left from 20:30 Fri.
- **Judging:**
  - **Use of Higgs (30%):** code-switching, expressive delivery, real-time turn-taking, interruption handling, tool calling. "If it'd work the same with any generic TTS engine, strengthen this."
  - **UX (25%):** "a rough prototype that feels good beats a polished one that doesn't."
  - **Innovation (25%):** bonus for solving a real problem.
  - **Technical Execution (20%):** judges read the repo; honest notes on what's unfinished help.
- **The team's concept:** a thesis / project / assignment defense examiner. You present your slides; the AI examiner hears you and knows which slide you're on.
  - It interrupts you, asks closed and open questions, and gives positive and negative comments.
  - It keeps time and makes sure you acknowledged its reminders.
  - It has a customisable character and internet access.
  - **It asserts authority.** It acts as your examiner, not your assistant.
- **Decisions made:**
  - Director-driven interruption is part of the core build.
  - Add code-switching answers (Indonesian / Mandarin), live web fact-check, a debrief scorecard, and a preset avatar examiner (LiveKit Cloud) with a voice-only fallback.
  - Python code / codebase uploads are cut.
- **Model:** `higgs-realtime-1.5-preview`, the hackathon preview. It uses the same `wss://api.boson.ai/v1/realtime` endpoint and is documented on the tutorial repo's **`realtime-1.5-preview`** branch. GA `higgs-realtime` stays one env var away (`BOSON_REALTIME_MODEL`).
- **Greenfield:** the working dir `C:\Users\Lenovo\Documents\!MScAC\Boson Hackathon` is empty.

## Core design decisions
1. **"Sees the presentation" means our own slide viewer, not screen vision.** The Realtime docs only show audio and text input.
   - **Before the session:** the PDF is rendered to slide images plus extracted text. Claude Haiku (`claude-haiku-5-5`, vision, structured output) produces, per slide: a summary, its claims, weak points and candidate questions.
   - **During the session:** each "next slide" click in our viewer sends the examiner a text item such as `"[Presenter is now on slide 5: <summary>]"`. This goes in with **no** `response.create`.
2. **Manual turn control during the presentation, so we own the turn-taking policy.**
   - Set `turn_detection: null`. Presenter audio streams continuously through `input_audio_buffer.append`.
   - A local VAD (Silero) commits a chunk at each breath pause (`input_audio_buffer.commit`). That produces `conversation.item.input_audio_transcription.completed` but **no automatic reply**.
   - The **director** (Haiku, fast settings) reads the rolling transcript, the current slide's weak points, elapsed time and cooldowns. It returns `{action: none | interject | remind, cue}`.
   - On `interject`, we add the cue as a text item and send `response.create`. The examiner cuts in at the next breath, about 2–3 s after the weak claim.
   - With server VAD off, the server never auto-cancels on presenter speech. **Barge-in policy belongs to us**, and that is what makes holding the floor possible.
   - **Protocol constraint (from the client-events reference):** with `turn_detection: null`, both `input_audio_buffer.commit` and `response.create` are **rejected** (`error.type: "voice_output_task_ongoing"`) while a response is being generated.
     - Keep appending presenter audio while the examiner speaks, and commit once `response.done` arrives.
     - Never queue a second `response.create` during an active response.
     - `response.create` accepts per-response `instructions` and `input` message items, so a director cue can ride along with the request itself.
3. **Holding the floor and acknowledgement (the team's insight, made a named feature).**
   - When the examiner interjects or reminds, presenter speech is ignored for about 1.5 s; the examiner keeps the floor.
   - **Acknowledgement** means one of: the presenter goes silent within about 2 s; an acknowledgement phrase appears in the transcript ("okay", "noted", "yes"); or the presenter jumps to the last slide when told to wrap up.
   - With no acknowledgement, the examiner **escalates once**, more firmly: "Let me stop you there."
   - Real cancellation (`response.cancel`, then avatar `clear_buffer()`, then `conversation.item.truncate`) only happens in Q&A, when the presenter talks for more than about 1 s past the hold window.
4. **One session, manual turns for the whole exam.** (Revised after K5: `turn_detection cannot be changed after session start`.)
   - **Presentation:** manual turns plus the director, as above.
   - **Q&A:** still manual. **We own end-of-turn.**
     - When the local VAD hears ~0.6 s of silence, make a *speculative commit*: it costs nothing and triggers no reply.
     - Send `response.create` once the silence reaches the character's patience threshold (~1.2–1.5 s), or earlier if the transcript reads as a complete answer.
     - If the presenter resumes, keep appending; several user items are fine.
   - **Barge-in:** also ours, via `response.cancel` → `clear_buffer()` → `truncate` (K3: stops in 31 ms).
   - **Why not Higgs's automatic modes:** `semantic_vad` is accepted at session start, but it jumped in during a 2.5 s thinking pause and split a long Indonesian answer into 3 replies (K5c/K5g). That's unsuitable for presenters.
   - **Phase changes** (presentation → Q&A → debrief) use an instructions-only `session.update`, which K5f showed works mid-session.
   - **Director cues** go in per-response `instructions`, never conversation items. As a user item, the model read the cue aloud ("The director's cue is asking…") and answered it itself.
   - **Brevity:** per-response `max_output_tokens`. Session instructions also carry the persistent rules (≤2 sentences, never mention notes or cues, after a web search state only the finding).
5. **Authority through behaviour, not rudeness.** UX counts.
   - The examiner holds the floor, presses with follow-ups and keeps strict time.
   - It doesn't over-praise and doesn't apologise for asking.
   - Default character: demanding but fair. Harsher characters are optional.
   - **Character drives the examiner's behaviour.** How often she interrupts, and for what, comes from the character, not from hard-coded rules. For the final version, tune the characters rather than the code:

     | Field | Controls (agent) | Current values |
     |---|---|---|
     | `interrupt_rate` | spacing between interruptions; Q&A patience before replying | low 45 s / 1.6 s · medium 30 s / 1.3 s · high 20 s / 1.0 s |
     | `strictness` | whether **minor** issues can interrupt the talk (the director labels each issue major or minor) | ≥ 5 (The Skeptic): minor too · < 5: major only, minor saved for Q&A |
     | `persona` | tone, phrasing, which questions she favours | free text (presets + custom) |

     The fixed rules for every character: no interruptions in the first 20 s, at most one per slide, fact-checks ≥ 10 s apart, hold the floor 1.5 s. The numbers live in `agent/exam.py`.
6. **Code-switching.** In Q&A the presenter may answer in Indonesian or Mandarin mid-sentence. The examiner follows and continues in the session's language; a character can also be set to examine in Indonesian. Mostly prompt work, checked in K5.
7. **Live web fact-check.** Declare the server-executed `{"type":"web_search"}` tool. The examiner says "let me check that" and verifies a claim. Skip `executor:"server"` calls in our tool handler, the way the tutorial's `livekit/server_tools.py` does.

## Architecture
```
web/ (React + livekit-client)  ◄──►  LiveKit Cloud room  ◄──►  agent/ (Python worker, hand-built)
  setup · slide viewer · timer ·         │  presenter mic ───────►  local VAD (Silero) ─► commit chunks
  avatar video · captions · scorecard    │  "viva.ctl" (slide, phase) ►  Realtime WS (higgs-realtime-1.5-preview)
                                         │  ◄── "viva.ui" (state, captions, reminders)   director (Haiku) · floor policy · timer
                                         │  ◄── avatar A/V (preset, DataStreamAudioOutput)   Higgs Avatar session
server/ (FastAPI): /token · /api/sessions (upload → prep via Haiku) · /api/sessions/{id}/scorecard (Haiku)
```

**Primary agent path: Boson's hand-built agent from the Avatar realtime-sessions guide.** It uses a raw Realtime WebSocket plus `DataStreamAudioOutput` (`livekit-agents` from PyPI):
- `flush()` on `response.done`
- `clear_buffer()` when we cancel
- `playback_finished` to track speaking state
- `POST/DELETE /v1/avatar/sessions`

We chose it over the LiveKit Agents plugin because manual commits, `response.create` on demand and our own barge-in policy *are* the product. Raw protocol control is the safe choice, and it avoids the tutorial's forked-plugin version pins.

**Reuse:**
- Tutorial @ `realtime-1.5-preview` (`git clone -b realtime-1.5-preview https://github.com/boson-ai/higgs-realtime-tutorial`):
  - the model name and session config shape (`src/realtime/sessionConfig.ts`)
  - event handling for out-of-order events (`src/realtime/events.ts`, `src/state/transcriptStore.ts`)
  - skipping server-executor tool calls (`livekit/server_tools.py`)
  - the headless probe approach (`livekit/probe.py`, `tools/probe.ts --say`)
- The Avatar guide's agent and `viewer.html`.

## Inputs (merged into five fields)
1. **Scenario preset:** Thesis defense / Capstone-internship presentation / Assignment oral. This sets the purpose, the examiner's role and domain framing.
2. **Character:** 3 presets plus a free-text custom box. Each preset maps to persona text, a voice preset, an avatar id, an interruption rate and a strictness level.
   - *The Skeptic:* interrupts often, presses on evidence.
   - *The Supervisor:* fair, constructive, moderate interruptions.
   - *The Industry Panelist:* asks "so what / cost / deployment", impatient with jargon.
3. **Upload:** slides PDF (required) plus one optional supporting document (PDF/text).
4. **Time limit** for the presentation, plus Q&A length.
5. **Anything else:** free text, e.g. "focus on methodology".

## Outputs
- During the presentation: interjections (closed or open question, or a positive or negative comment), time reminders with acknowledgement and escalation, and a web fact-check when a claim is checkable.
- Q&A: examiner-led questions from the prepared question bank and weak points, with code-switching allowed.
- **Debrief:**
  - A 3-sentence spoken verdict in character.
  - A **scorecard page** (Haiku, from the session log): per-criterion scores (clarity, rigour/evidence, handling questions, time management), timestamped strong and weak moments with quotes, top 3 improvements, and the times the presenter didn't acknowledge a reminder.

## Repo layout (new)
- `agent/`: uv project, Python 3.11+.
  - `main.py`: join room, avatar session, wiring.
  - `realtime.py`: WS client and events.
  - `vad.py`: Silero chunk commits.
  - `director.py`: Haiku decision, cooldowns.
  - `floor.py`: holding the floor, acknowledgement and escalation state machine.
  - `timer.py`
  - `phases.py`: presentation → Q&A → debrief, mode switching.
  - `session_log.py`: timestamped JSONL.
  - `prompts/`: `examiner_base.md`, `characters/*.md`.
- `server/`: FastAPI.
  - `main.py`: `/token` (livekit-api), `/api/sessions`, `/api/sessions/{id}`, `/api/sessions/{id}/scorecard`.
  - `prep.py`: PyMuPDF render and text, parallel Haiku per-slide analysis, question bank, examiner-instructions assembly.
  - `scorecard.py`
- `web/`: Vite + React + TS, `livekit-client` and `@livekit/components-react`.
  - Pages: `Setup`, `Session`, `Scorecard`.
  - Components: `SlideViewer`, `Timer`, `AvatarStage`, `Captions`, `ExaminerState`, `LatencyHud`.
- `demo/`: `deck.pdf`, an 8-slide internship-style project with planted weaknesses:
  - "40% better" with no baseline
  - one checkable dubious statistic
  - a text-crammed slide
  - a talk designed to run over time

  Also `characters.json`, cached `prepped-analysis.json` and `sample-scorecard.json` (fallbacks if Haiku or the network fails).
- `README.md`, `.env.example`, `docs/architecture.png`.

**How the agent gets its config:** room name = session id. The agent fetches `/api/sessions/{id}` on join (prepped analysis, instructions, character, time limit).

## Roles
- **A (agent/runtime):** the Realtime WS client, LiveKit room and avatar, VAD commits, director, floor policy, timer, phases, web_search, session log.
- **B (web + prep + content):** the React app, the FastAPI server (token, upload, prep, scorecard), the demo deck and characters, the video and the README.
- **Both:** kill tests, tuning, recording.

## Interfaces between A and B (pinned now, so both can build in parallel)
**Identities:**
- Room name = `session_id`.
- Agent = `viva-agent`, avatar = `boson-avatar`, presenter = `presenter`.

**LiveKit text topics:**
- **`viva.ctl` (web → agent):**
  - `{type:"start"}`
  - `{type:"slide", index}`
  - `{type:"phase", phase:"presentation"|"qa"|"end"}`
- **`viva.ui` (agent → web):**
  - `{type:"state", state:"listening"|"interjecting"|"holding_floor"|"qa"|"debrief"|"ended"}`
  - `{type:"caption", role:"presenter"|"examiner", text, lang?, t}`
  - `{type:"interjection", slide, reason, t}`
  - `{type:"reminder", kind:"t_minus_2"|"time_up", acknowledged: true|false|null}`
  - `{type:"factcheck", status:"searching"|"done", claim?, sources?}`. `claim` is the presenter's statement being checked, when known.
  - `{type:"latency", metric, ms}`. Measured by the agent; the web side may add its own browser-side metrics.
    - `pause_to_interjection`: local VAD detects the presenter's pause → first examiner audio frame sent to the avatar. Excludes avatar render and network.
    - `cancel_to_silence`: agent decides to cancel (barge-in) → avatar `playback_finished` after `clear_buffer()`. Falls back to `response.done` if there's no playback event.
    - `answer_end_to_reply`: Q&A, presenter's end of speech (VAD) → first examiner audio frame.
  - `{type:"ended", session_id}`

**Server API (B builds, A consumes):**
- `GET /token?room=&identity=` → `{url, token}`.
- `POST /api/sessions` (multipart: `scenario`, `character` = preset id or `custom_text`, `time_limit_s`, `qa_s`, `notes`, `slides` PDF, optional `support_doc`) → `{session_id, slide_count}`.
- `GET /api/sessions/{id}` → **SessionConfig**:
  - `{session_id, scenario, time_limit_s, qa_s, notes, instructions}`. **`instructions` is optional and ignored by the agent**, which assembles the phase instructions itself (`agent/instructions.py`: `agent/prompts/examiner_base.md` + character + scenario + notes + slide digest + phase rules). The server doesn't need to assemble them.
  - `character: {id, name, persona, voice, avatar_id, interrupt_rate, strictness}`
    - **Custom characters:** `id` stays the preset id. The server appends `custom_text` (or free text sent as `character`, on top of the Supervisor) to the preset's `persona`.
    - The agent uses `persona` as given. It has no per-character prompt files.
    - `interrupt_rate` (`low|medium|high`) sets the agent's interjection cooldown (45/30/20 s) and its Q&A patience (1.6/1.3/1.0 s).
  - `slides: [{index, image_url, summary, claims[], weak_points[], questions[]}]`. The same shape as `demo/prepped-analysis.json` (B's cached prep output, a JSON list of these objects).
- `POST /api/sessions/{id}/log`: the agent uploads its log at the end, as the **raw request body**. `Content-Type: application/x-ndjson`, one log object per line, exactly the `sample-log.jsonl` format. Response: `{ok: true, lines: N}`.
- `GET /api/sessions/{id}/scorecard` → **Scorecard**:
  - `{verdict, criteria:[{name, score_1_5, comment}], improvements:[3]}`
  - `moments: [{t, slide, kind:"strong"|"weak"|"unacknowledged", quote, note}]`

**Session log (JSONL, A writes):** one object per line, `{t, kind, ...}`. `kind` is one of `chunk|examiner|director|interjection|reminder|ack|escalation|phase|slide|factcheck`. `t` is seconds from session start. The fields for each kind are defined by example in `demo/sample-log.jsonl` (e.g. `chunk` has `slide`, `lang`, `text`; `ack` has `for`, `how`). Treat that file as part of the contract.

Both sides get fixtures in `demo/`: `session-config.json`, `sample-log.jsonl`, `sample-scorecard.json`. B can build the UI against fake `viva.ui` events before the agent exists, and A can run against a static SessionConfig before the server exists.

## Working with Claude Code (keeping token use down)
- **Never let Claude read raw Realtime event dumps.** `response.output_audio.delta` and `input_audio_buffer.append` carry base64 audio, so a few seconds of raw log is tens of thousands of tokens. `realtime.py` logs **one line per event** (type, ids, sizes, short text) and drops audio payloads.
- **Cache docs locally once.** Run `python docs/fetch_vendor_docs.py`. It saves 24 Boson doc pages (raw markdown) and 18 tutorial `realtime-1.5-preview` files into `docs/vendor/`, which is gitignored. Each folder's `CLAUDE.md` holds the API facts that matter. Read those local copies instead of fetching docs from the web or re-reading library source.
- **Let Claude test without a human (A):** a headless probe streams a synthesised presentation WAV and prints a compact event summary. Most loops then don't need "run it and tell me what you heard".
- **Keep UI iteration cheap (B):** one component per task, small files, and screenshots only when layout matters (each one costs about 1–2K tokens).
- Use `/clear` between unrelated tasks. Keep the plan file as the shared source of truth.

## Stages and checkpoints

### Stage 0: setup (Fri 20:30–21:30)
- **Both:** a LiveKit Cloud project (avatar requires Cloud), plus `.env` with `BOSON_API_KEY`, `LIVEKIT_URL`/`KEY`/`SECRET`, `ANTHROPIC_API_KEY`, `BOSON_REALTIME_MODEL=higgs-realtime-1.5-preview`.
- **A:** run the Avatar guide's hand-built agent with a preset avatar and the 1.5-preview model. Talk to it in `viewer.html`.
- **B:** scaffold `web/` and `server/`. Render `demo/deck.pdf` to PNGs and text with PyMuPDF.
- **✅ C0:** talking to a preset avatar powered by `higgs-realtime-1.5-preview`. The deck renders.

### Stage 1: kill tests (Fri 21:30 – Sat 00:00)
- **K1, manual commits:** with `turn_detection: null`, continuous append plus VAD-pause commits produce `transcription.completed` per chunk, with **no** auto-response.
- **K2, triggered interjection:** while the presenter is talking, a hotkey (later the director) sends `response.create`. The examiner speaks over the presenter, the avatar lip-syncs, and the server doesn't cancel. Measure trigger → first audio and trigger → avatar mouth moving. Target under 1.5 s.
- **K3, floor policy:** the hold window works; `response.cancel` + `clear_buffer()` + `truncate` stop the speech cleanly.
- **K4, slide awareness:** a text item "now on slide 5…" doesn't trigger a reply, and a later question correctly refers to slide 5. Check whether per-response instructions on `response.create` work, versus a cue text item.
- **K5, Q&A mode:** `session.update` → `server_vad` mid-session works. Answers mixing Indonesian and Mandarin are followed. Server `web_search` completes on its own (we skip `executor:"server"`).
- **K6, prep:** Haiku vision on the 8-slide deck, run in parallel, finishes in under 60 s with useful weak points. Check that Haiku 5.5 accepts images (Models API `capabilities`); fallback is text-only PyMuPDF extraction.
- **✅ C1 go/no-go:**
  - **K1 or K2 fail** → fallback: `server_vad` throughout, with interjections only at slide changes and timer events (inject text, then `response.create` at the next pause).
  - **K5 mode switch fails** → manual mode throughout, local VAD decides when a turn ends.
  - **Avatar latency over 3 s or `capacity_exhausted`** → `VIVA_AVATAR=0` voice-only mode becomes primary.

### Stage 2: MVP loop (Sat 00:00–04:00)
- **A:** the end-to-end session on the demo deck with a hard-coded Supervisor character and the cached `prepped-analysis.json`:
  - director interjections, with a cooldown of at least 25 s, none in the first 30 s, at most 1 per slide
  - time reminders at T−2 min and T−0, with acknowledgement and escalation
  - the switch to Q&A
  - a spoken verdict, then end
  - a session log
- **B:** the `Session` page: `SlideViewer` (sends `viva.ctl` slide events), `Timer`, `AvatarStage`, `Captions` and `ExaminerState` (listening / interjecting / holding the floor / Q&A), plus `/token`.
- **✅ C2 (the submittable floor):** a full 5-minute presentation plus 2-minute Q&A runs with no code edits mid-run. At least one real interjection, a reminder, an escalation and a Q&A exchange happen. Tag `mvp`.

**Sleep:** 04:00–08:30, staggered. Each person gets at least 4 hours.

### Stage 3: setup flow + debrief (Sat 08:30–11:00)
- **B:**
  - `Setup` page with the 5 fields.
  - `/api/sessions`: upload → `prep.py` (Haiku per-slide analysis in parallel, question bank, instructions from `examiner_base.md` + character + scenario + notes).
  - `Scorecard` page.
- **A:** load the config per session. Add custom characters (free text appended to the persona, with the closest preset as the base). Pass the log to `/scorecard`.
- **✅ C3:** an unseen deck and a custom character run end to end, with a scorecard. Tag `v1`.

### Stage 4: feel + tuning (Sat 09:30–11:30)
- Director thresholds per character, short sharp interjection phrasing, `LatencyHud` (pause → interjection, cancel → silence).
- A rehearsed code-switching moment in Q&A and a web fact-check moment.
- Check the voice-only fallback (`VIVA_AVATAR=0`). Use a wired headset mic.
- **✅ C4:** feature freeze at 11:30. Tag `rc`.

### Stage 5: demo video (Sat 11:30–13:00), 2:30 total
1. **Cold open:** the presenter claims "40% better" and the examiner cuts in at the next breath: "Better than *what*? What's your baseline?"
2. The problem: every AI is your assistant, and practising a defense needs an examiner.
3. Setup: scenario, character, upload.
4. The T−2 reminder is ignored, so the examiner escalates and holds the floor.
5. Web fact-check of the dubious statistic.
6. Q&A: the presenter answers partly in Indonesian and the examiner follows.
7. The debrief verdict and the scorecard with timestamps.
8. How it's built: Realtime 1.5 preview (manual turns, server turns, tools, web search), STT, Avatar.

Record with OBS, 2–3 takes, upload publicly.
- **✅ C5:** the link plays in incognito.

### Stage 6: repo + submission (Sat 13:00–13:50; the form closes at 2 PM)
- **README:**
  - problem and audience
  - setup (LiveKit Cloud, keys, `uv sync`, `npm i`, run commands)
  - architecture diagram
  - example inputs/outputs (`demo/`)
  - **known limitations** (e.g. interjections land at pauses, not mid-word; avatar latency; preview model)
- `.env.example`. Secret scan: `git grep -nE "bai-|sk-ant|LIVEKIT_API_SECRET="`. Tag `submission` and record the SHA.
- **Form:** track *Put a Face to the Voice*, one-liner, 200-word write-up, 200-word how-built (manual turn control plus director, holding the floor, mode switch, server web search), team + GitHub handles, limitations.
- **✅ C6:** fresh clone on the other laptop → README → it runs. Submitted by 13:50 (deadline 2 PM).

**15:00 group round (peers vote) and 17:00 finals (judges):**
- Live demo, with the video as backup.
- Create the avatar session early.
- Have the `VIVA_AVATAR=0` fallback ready.

## Risks and mitigations
| Risk | Mitigation |
|---|---|
| Manual turn control / triggered `response.create` behave differently in the preview | K1–K2 first thing tonight; fallback to slide/timer-triggered interjections |
| Director too chatty or too quiet | Per-character cooldowns and caps; hotkey override during the demo |
| Avatar slots exhausted at 3 PM (all teams) | `VIVA_AVATAR=0`, start the avatar session early, pre-recorded video |
| Interjection latency (director + model + avatar) | Haiku with thinking disabled and tiny prompts; measure in the HUD; fire the director on every committed chunk |
| Preview model unstable | `BOSON_REALTIME_MODEL` env switch back to `higgs-realtime` |
| Noisy venue / echo / false barge-ins | Wired headset, VAD threshold tuning |
| Haiku/network failure | Cached `prepped-analysis.json` and `sample-scorecard.json` in `demo/` |

## Verification
- **Kill tests K1–K6:** a headless probe (adapted from the tutorial's `probe.py` / `--say` approach) streams a synthesised 60-second "presentation" WAV containing a planted weak claim. Assert that chunk transcripts arrive, the director fires an interjection, and `viva.ui` events are emitted. Then check by ear and eye in the browser.
- **C2:** two full runs on the demo deck. Check the session log for every chunk, director decision, interjection, reminder, acknowledgement or escalation, and phase switch, with timestamps that match the video.
- **C3:** run prep on an unseen deck. Check that the analysis JSON validates against the schema and its slide indices exist. Check that scorecard quotes match transcript lines.
- **C4:** HUD median pause → interjection under about 2.5 s; cancel → silence under about 300 ms; one full run with `VIVA_AVATAR=0`.
- **C6:** fresh clone works on the second machine; secret scan clean. Check Boson usage after C2 (Haiku costs are pennies per session).
