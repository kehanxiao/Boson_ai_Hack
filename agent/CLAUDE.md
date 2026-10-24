# agent/: Role A, live examiner runtime (Python)

A hand-built worker: joins the LiveKit room, starts a Higgs Avatar session, and drives a raw Higgs Realtime WebSocket. It owns turn-taking: VAD commits, the director, holding the floor, the timer and phases. Design rationale: `PLAN.md` → "Core design decisions" and "Architecture".

## Planned files
- `main.py`: wiring.
- `realtime.py`: WS client; **one-line event logging, no base64**.
- `vad.py`: Silero pause detection → commits.
- `director.py`: Haiku "interject now?" decision with cooldowns.
- `floor.py`: holding the floor, acknowledgement, escalation.
- `timer.py`
- `phases.py`: presentation → Q&A → debrief.
- `session_log.py`: JSONL in the `PLAN.md` log format.
- `prompts/examiner_base.md`, `prompts/characters/*.md`.

Stack: uv, Python 3.11+, `livekit-agents` (PyPI, for `DataStreamAudioOutput`), `livekit` (rtc + api), `websockets`, `anthropic`, `python-dotenv`.

## Starting point
`docs/vendor/boson/models/higgs-avatar/realtime-sessions.md`, the hand-built `agent.py` walkthrough:
- `from livekit.agents.voice.avatar import DataStreamAudioOutput`
- `capture_frame` sends PCM to the avatar
- `flush()` at the end of an utterance (`response.done`)
- `clear_buffer()` to stop the avatar
- the `playback_finished` event means the avatar has *actually* stopped talking. The model generates faster than real time, so `response.done` is too early for this.
- avatar: `POST /v1/avatar/sessions` with `publisher_identity` = our agent identity; `DELETE` it in `finally`.

## Realtime protocol facts (verified in `docs/vendor/boson/api-reference/realtime/*.md`)
- **Audio:** 24 kHz, 16-bit, mono PCM, base64 in `input_audio_buffer.append`.
- **Manual turns:** `session.update` with `audio.input.turn_detection: null`.
  - `input_audio_buffer.commit` → transcription + user item, **no response**.
  - `response.create` asks for one.
- ⚠️ **With `turn_detection: null`, both `commit` and `response.create` are rejected (`voice_output_task_ongoing`) while a response is being generated.** Keep appending presenter audio while the examiner speaks, commit after `response.done`, and never queue a second `response.create`.
- **`response.create`** takes a `response` object with per-response `instructions`, `input` (message items, also appended to the conversation), `max_output_tokens` and `metadata`. Use it to deliver a director cue.
- **`conversation.item.create`** (text message) never triggers a response. Use it for "[Presenter is now on slide N: …]" context.
- **Cancel cleanly:** `response.cancel`, then `DataStreamAudioOutput.clear_buffer()`, then `conversation.item.truncate {item_id, content_index, audio_end_ms}`, so the transcript matches what was heard.
- **Q&A mode:** `session.update` → `turn_detection: {type: "server_vad"}`. With server VAD, presenter speech auto-cancels the examiner (native barge-in). Mid-session switching is unverified; see K5 in `PLAN.md`.
- **Transcription:** `audio.input.transcription: {model: "higgs-stt-3.1"}`. Only `conversation.item.input_audio_transcription.completed` exists (no deltas).
- **Function tools:** flow is `response.function_call_arguments.done` → `response.done` carries the `function_call` item → send `conversation.item.create {type: function_call_output, call_id, output}` → `response.create`.
- **Server web search:** declare `{"type": "web_search"}` in `session.tools` (optionally `allowed_domains` / `excluded_domains`, max 5, mutually exclusive). Calls arrive with `executor: "server"`. **Do not** answer them or send `response.create`; the server continues by itself. Never name a function tool `web_search`.
- Sessions close after 5 minutes without user speech (`session.idle_timeout`). Insufficient credit gives `error.type: insufficient_quota`, then close code 4429.

## Stage 0 findings (Fri 21:15, `stage0_avatar.py`)
- **It works:** preset avatar + `higgs-realtime-1.5-preview` + server VAD in LiveKit Cloud. The session reports `model=higgs-realtime-1.5-preview`.
- **Model latency** (end of user speech → first audio delta at the agent): **~420–600 ms** in English. Outliers of 1–2 s on Indonesian and on turns split by the VAD.
- **Perceived latency is ~1.2–2 s.** On top of model latency come the 500 ms VAD silence wait and the avatar render + LiveKit transport. Measure it in the browser (`LatencyHud`), and compare with `VIVA_AVATAR=0`.
- **Server VAD (`silence_duration_ms` 500) cuts thinking pauses** ("I think my."). Q&A needs a longer silence window or `semantic_vad` (K3).
- **Indonesian:** the model understands it and replied in English. `higgs-stt-3.1` transcripts of short Indonesian phrases are shaky ("Coba ngomong" became "Cebong ngomong"). Treat captions and scorecard quotes in Indonesian as approximate.
- **Barge-in on server VAD works:** `speech_started` → `clear_buffer()` stops the avatar.
- **`DELETE /v1/avatar/sessions/{id}` can return 429 `rate_limit_exceeded`.** Retry it with `Retry-After` in `finally`. If the process is killed (not Ctrl-C), release the session manually, or it holds a capacity slot until the room empties or `max_duration_seconds` runs out.
- **A minimal prompt makes the model repeat its self-description.** That's expected, and the real examiner prompt fixes it.

## Stage 1 results so far (Fri 21:35, `probes/manual_turns.py`, headless, all PASS)
- **K1:** with `turn_detection: null`, `commit` → `transcription.completed` in **~0.4–0.8 s**, and **no automatic response**.
- **K2:** `response.create {response: {instructions: <persona + cue>}}` *while presenter audio is still streaming* → `response.created` **+63 ms**, first audio **+453 ms**. The response finished `completed` and was **not cancelled** by ongoing presenter audio. The examiner said exactly the cue ("What is the forty percent relative to, and on which metric?").
- **K2b:** `commit` during an active response → `error voice_output_task_ongoing` ("Skipping"), as documented. **The audio isn't lost**: it stays in the buffer.
- **K1b:** `commit` after `response.done` is accepted, and its transcript covers everything said meanwhile (16 s).
- **K4:** a `user` text item "[Context note: …]" triggers no response, and the examiner didn't read it aloud. The instructions say bracketed text is a system note. Only `user` and `assistant` roles exist; there is no `system` item role.
- Generation runs faster than real time (4.2 s of speech in ~1.1 s), so the commit window reopens long before the avatar finishes speaking.
- **Interjection latency budget:** pause detection (~0.3 s) + transcript (~0.4 s) + director (Haiku, ~0.5–0.9 s?) + first audio (~0.45 s) + avatar render (~0.3–1 s) ≈ **2–3 s**. This fits the PLAN target of a cut-in at the next breath. Measure the director step for real.

## K3 + K5 results (Fri 21:55, `probes/cancel_truncate.py`, `probes/qa_mode.py`)
- **K3 cancel:** `response.cancel` mid-generation → `response.done status=cancelled` in **31 ms**.
  - `conversation.item.truncate {audio_end_ms}` works. The stored item becomes e.g. `'I need<|INTERRUPTED|>'`, so the model knows it was cut off.
  - The session is immediately usable again.
- ⚠️ **`turn_detection` cannot be changed after session start** (`invalid_request_error`). Pick manual (`null`) at session start and keep it. Q&A end-of-turn and barge-in are ours.
- **`semantic_vad`** is accepted at session start but jumped in during a 2.5 s pause and fragmented a 12 s Indonesian answer into 3 replies. Not used.
- **Instructions-only `session.update` mid-session works.** Use it for phase changes.
- **Code-switching on manual turns:** Indonesian- and Mandarin-mixed answers got on-topic English replies, first audio **+625–734 ms after commit**.
- **Server `web_search` works with manual turns:**
  - preamble ("Let me just double-check…") → `function_call executor=server` → output after ~0.5–4 s → the **server starts the follow-up response itself** (no `response.create`).
  - Seen once: "LightGBM was released by Microsoft, not Google… 2017."
  - **Unreliable wording:** the follow-up sometimes only repeats the preamble, sometimes restates the wrong claim first, and runs long (35 s). Fix with session-level rules plus a length cap. The follow-up response doesn't carry the per-response `instructions` of the request that triggered the search.
- ⚠️ **Never put director cues in conversation items.** As a `user` message the model read the cue aloud ("The director's cue is asking…") and answered it itself. Per-response `instructions` behaved perfectly (K2).
- **Verbosity:** without a cap, Q&A replies ran 17–54 s. Use per-response `max_output_tokens`, plus session `max_output_tokens` for server-initiated follow-ups (e.g. after a search).

## UI events
Publish `viva.ui` messages exactly as specified in `PLAN.md` → "Interfaces between A and B", via `room.local_participant.send_text(json, topic="viva.ui")`. Listen for `viva.ctl` with a text stream handler (pattern in `docs/vendor/higgs-realtime-tutorial/livekit/probe.py`).

## Testing without a human
Adapt the tutorial probe (`docs/vendor/higgs-realtime-tutorial/livekit/probe.py`, `tools/probe.ts --say`). Stream a synthesised presentation WAV containing a planted weak claim and print a compact event summary. Most loops shouldn't need "run it and tell me what you heard".
