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

## UI events
Publish `viva.ui` messages exactly as specified in `PLAN.md` → "Interfaces between A and B", via `room.local_participant.send_text(json, topic="viva.ui")`. Listen for `viva.ctl` with a text stream handler (pattern in `docs/vendor/higgs-realtime-tutorial/livekit/probe.py`).

## Testing without a human
Adapt the tutorial probe (`docs/vendor/higgs-realtime-tutorial/livekit/probe.py`, `tools/probe.ts --say`). Stream a synthesised presentation WAV containing a planted weak claim and print a compact event summary. Most loops shouldn't need "run it and tell me what you heard".
