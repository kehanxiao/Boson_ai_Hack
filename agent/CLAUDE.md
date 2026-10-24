# agent/: Role A, live examiner runtime (Python)

A hand-built worker: joins the LiveKit room, starts a Higgs Avatar session, and drives a raw Higgs Realtime WebSocket. It owns turn-taking: VAD commits, the director, holding the floor, the timer and phases. Design rationale: `PLAN.md` → "Core design decisions" and "Architecture".

## Files
**Two Higgs Realtime sessions hear the presenter** (since Sat 01:00; see "Higgs brain" below):
- the **brain** (`brain.py`, text only) decides what the examiner does;
- the **voice** speaks the brain's lines word for word through the avatar, transcribes for captions, and runs the web search.

- `main.py`: live entry point (`uv run main.py [session_id]`, `VIVA_AVATAR=0` for voice-only, `VIVA_FACTCHECK=0`). Joins the room, starts the avatar (429 retry), loads SessionConfig from the server (falls back to `demo/` for `demo` and `gradebook`), connects both sessions, forwards presenter audio, handles `viva.ctl`, releases the avatar with retries, uploads the log.
- `brain.py`: the brain session. When asked, it answers one line: `SILENT`, `SAY: <words>`, `CHECK: <claim>`, or (Q&A) `END: <words>`. It gets the same audio and commits as the voice, plus `[bracketed]` notes: the slide, what she said that it didn't write (greeting, reminders, search results), and being talked over.
- `exam.py`: `ExamController`, the exam logic around the brain. The rules it keeps:
  - **When the brain is asked:** at each presenter pause, except while she speaks, and for `GAP_S` (4 s for medium) after she has spoken. A pause inside the gap is judged when the gap ends.
    - The exception is an exchange: after she cuts in, the presenter's next pauses for 20 s are a reply, judged after an extra `REPLY_PATIENCE_S` (0.9 s) of silence.
    - An exchange allows up to `follow_ups` replies: 1, or 2 for strictness 5. Then the brain is told to let the point go until Q&A.
    - Q&A: at each pause after the patience delay, or after 8 s of silence. At least `MIN_QA_QUESTIONS` (2) before END.
  - **The brain learns each slide when it is shown** (summary and weak points in the slide note). It sees the full digest only in Q&A. Knowing every slide up front, it raised later slides' claims early.
  - **Never the same point a third time** (`said`, word overlap). Lines of 5 words or fewer are exempt ("Yes, go on."), and a cut-off line counts toward the follow-ups.
  - **She is "speaking" only while the room hears her** (`output.on_started` → `audible_at`, until playback finishes). The avatar reports `lk.playback_started` (`wait_playback_start=True`), or the start is estimated at 1.3 s after the first captured audio. The floor-hold, talked-over detection and the brain's order all use this clock.
    - **The brain's order:** `brain.mark()` commits the audio so far, then adds "[She starts speaking now.]" or "[She has finished speaking.]". When a decision is being written, the note waits behind the queued commit.
    - **Overlap:** while she is heard, presenter audio is held back from the brain. If they stopped before she finished (trailing off, "yeah"), it is dropped. If they were still talking as she finished, or talked over her (barge-in), it is passed on. Live run (Sat 04:30): the brain took overlap as their answer and her line as earlier than it was heard.
    - A talk-over → she stops, and the brain decides between "Let me finish, please." and answering what they said.
  - **Holding the floor:** 1.5 s. Reminder → acknowledgement (phrase / silence / jump to the last slide) → one escalation.
  - **Talked over:** her brain lines and Q&A questions stop when the presenter keeps talking past the hold window (cancel + clear + truncate). The brain is told what the presenter heard. Reminders, fact-checks and the verdict hold the floor.
    - Q&A: 0.8 s past the hold.
    - Presentation: 2.5 s past the hold, in one unbroken stretch, because she was the one who cut in. At 0.8 s, the presenter finishing their sentence cut every interjection after a word or two.
  - **Q&A time-up:** the exchange under way may finish (25 s grace), then the brain ENDs and the voice gives the verdict.
  - It tracks every utterance from request to finished playing, including the server's own follow-up after a web search.
- `realtime.py`: WS client for both sessions (`name` for logs). Queues commits during a response, refuses `response.create` while busy or while a server tool is pending. One-line logging, no base64.
- `director.py` + `prompts/director.md`: the former Haiku director, now only used by `probes/higgs_brain.py` for comparison.
- `instructions.py` + `prompts/`: the brain's instructions per phase (`brain.md` + `brain()`), and the voice's per-phase and per-response instructions (`examiner_base.md`, `say_exactly()`).
- `vad.py`: Silero pause detector (0.6 s). `output.py`: avatar / voice-only / simulated playback with per-utterance finished callbacks.
- `session_log.py`: JSONL in the contract format, uploaded as raw `application/x-ndjson`. `ui.py`: `viva.ui` publisher (LiveKit, or print for sims).
- `probes/exam_sim.py [demo|gradebook]`: headless end-to-end exam (real Higgs brain + voice, simulated playback).
- `probes/higgs_brain.py [runs]`: the brain experiment: Higgs (hears audio) vs the Haiku director (reads transcripts) on planted errors.
- `stage0_avatar.py` + `viewer.html`: the Stage 0 check, kept for quick avatar smoke tests.

Stack: uv, Python 3.12, `livekit-agents` 1.8.8 (for `DataStreamAudioOutput`), `livekit-plugins-silero` 1.8.8, `websockets`, `anthropic`, `python-dotenv`.

**Expected pause → interjection** ≈ 0.6 s VAD + ~0.45 s brain + ~0.45 s first audio ≈ **1.5 s**, plus the avatar render. No transcript is waited for: the brain hears the audio. (The Haiku director path was ≈ 2.5 s.)

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

## Stage 2 findings (Fri 22:25, `probes/exam_sim.py`, full headless exam, 8/8 checks pass)
- ⚠️ **Committing presenter audio while a server `web_search` runs makes the server drop the follow-up answer.** The exam stalled with no reminders and no Q&A. `realtime.py` now holds commits until the follow-up has started. The audio keeps buffering, so nothing is lost.
- **Watchdog** (`exam.py`), so nothing can leave the examiner "busy" forever:
  - `response.create` with no `response.created` in 8 s is dropped.
  - A search follow-up missing after 12 s gets an answer from memory instead, so the fact-check still lands.
  - A missing `playback_finished` is timed out (audio length + 4 s).
- **The server rejects commits under 100 ms of audio** (`invalid_request_error`, "buffer too small"). `commit()` skips them and returns `sent|queued|merged|skipped`.
- **Transcripts arrive ~0.4–1 s after the pause, often after the presenter has clicked on.** Chunks are tagged with the slide that was showing when that speech *began* (`commits` queue in `exam.py`).
- **The director queues the newest chunk while busy, instead of dropping it.** Dropping lost the "40%" claim in the first run.
- **Fact-checks have their own 10 s cooldown.** The 30 s interjection cooldown had blocked the LightGBM moment. The cue forces `web_search` ("do not answer from memory"), because B's slide digest already contains the correction.
- **Director latency in a live run: ~0.9–3.4 s, median ~2 s** (variable). Pause → interjection measured **2.0 s** ("40%") and **3.3 s** (fact-check), excluding the avatar. If that feels slow live, the fallback is a local model on the 5090 via LM Studio.
- **Q&A:** answer end → reply **~1.1 s**. Questions skip slides already handled by an interjection. The Q&A instructions list the points already raised, so she doesn't re-ask them.
- **The sim's Indonesian and Mandarin come from an English TTS voice and transcribe as English gibberish.** Real speech worked in Stage 0, so language checks in the sim are informational only.

## Higgs brain (Sat 00:30–02:30, `probes/higgs_brain.py`, `probes/exam_sim.py`)
- **Why:** in the live GradeBook run the Haiku director noticed the planted errors but labelled them minor or was held back by the cooldown. Talking over her did nothing, and it felt "programmed".
- **Experiment** (10 TTS chunks, 6 planted errors, 3 runs):
  - **Higgs** (text-only Realtime, hears the audio): caught 6/6 every run, 0 malformed answers, median ~0.45 s (max 0.58 s).
  - **Haiku** (reads transcripts): caught 5/6, 5/6 and 6/6, median ~1.5–1.9 s (max 4 s).
  - Higgs's 3 "false alarms" per run were fair examiner moves: a contradiction with "top twenty" said a minute earlier, the header-row bug, pressing after "um, so, yeah".
- **Why two sessions and not the voice deciding:**
  - An audio response can't be silent.
  - The voice refuses commits and responses while it speaks or searches.
  - Dozens of SILENT turns would fill her spoken conversation, and this model has read hidden notes aloud before.
- ⚠️ **Format compliance depends on prompt order.** Start the instructions with "Every answer you give is exactly one line that starts with SILENT, SAY: or CHECK:".
  - With the format block only at the end, after a speaking-style paragraph, Higgs wrote good spoken lines without the tag 8–10 times in 10 (ablation via `--prompt-file`).
  - With that first line it was 0 in 10.
  - Transcription on or off and a note before every chunk made no difference.
- **No transcription on the brain:** it hears the audio itself. Captions and the log come from the voice session's STT.
- **It prefers correcting from memory over CHECK** ("sorted uses Timsort, not quicksort"). The prompt asks for CHECK on outside-world facts, so the presenter sees the evidence.
- **Verdict:** asked with its own instructions (`brain(config, "verdict")`, `SAY: Verdict: …`). With the Q&A instructions it answered SILENT.
- **Voice responses can fail upstream** (`response.done status=failed`, "an upstream service call did not complete"). This happened about once per sim. Our requests are retried once.
- ⚠️ **A response asked for right after another response starts late.** A voice `response.create` sent within ~1 s of a brain `response.done` takes ~1.6–1.8 s to its first audio; 0.8 s later it takes ~0.36 s (`probes/two_session_latency.py`, 5 rounds).
  - The cause is not the voice's own commit (`probes/voice_latency.py`) and not the brain's commit.
  - Cancelling the brain's response doesn't help.
  - **Within one session it happens too:** a spoken response right after a text response and a `session.update` took ~1.65 s (`probes/single_session.py`).
  - `say()` therefore waits until 0.8 s after the brain's last response (`BRAIN_SETTLE_S`), which is faster overall.
  - **It is per key.** With the brain on its own key (`BOSON_BRAIN_API_KEY`), the voice's first audio is ~0.35 s even when asked right after the brain's `response.done` (4 rounds), so `say()` waits only when both share a key. Pause → first audio ≈ 0.45 s brain + 0.35 s voice, plus the avatar.
- **One session can't be both brain and voice:** a per-response `output_modalities: ["text"]` is ignored (the decision came back as audio), and switching the session to text mid-session returned no text (`probes/single_session.py`).

## Checks against the plan (Sat 04:00–04:20)
- **C3, headless:** `probes/c3_session.py` creates a session through the server, as the Setup page does: the GradeBook deck, fresh prep in 8.2 s, The Skeptic plus a custom brief, a supporting document.
  - `probes/exam_sim.py gradebook --session <id>` then runs the exam on that config, uploads the log and prints the server's scorecard.
  - Result: all sim checks pass, and the log uploads (HTTP 200). The scorecard came back with a verdict, 4 criteria, 6 moments (strong, weak, unacknowledged) and 3 improvements.
- **Supporting document:** the server puts the excerpt only inside `SessionConfig.instructions`, which the agent ignores. `instructions.support_excerpt()` reads it from there into both sessions' prompts (no contract change).
- **Live through LiveKit, headless:** `probes/live_room.py <session_id>` joins as the presenter with a TTS microphone, sends `viva.ctl`, and checks `viva.ui` and the examiner's audio. Voice-only and avatar both pass all 7 checks.
- ⚠️ **The avatar adds ~1.4 s** (1.36–1.66 s) from the agent's first audio to sound in the room. Voice-only adds ~0.1–0.2 s.
  - The end of the presenter's speech → her voice: ~1.4 s voice-only, ~2.8 s with the avatar.
  - For measuring this, the probe's `AudioSource` needs a small `queue_size_ms`. With the default 1 s queue, `capture_frame` returns ~1 s before the audio is sent.

## UI events
Publish `viva.ui` messages exactly as specified in `PLAN.md` → "Interfaces between A and B", via `room.local_participant.send_text(json, topic="viva.ui")`. Listen for `viva.ctl` with a text stream handler (pattern in `docs/vendor/higgs-realtime-tutorial/livekit/probe.py`).

## Testing without a human
Adapt the tutorial probe (`docs/vendor/higgs-realtime-tutorial/livekit/probe.py`, `tools/probe.ts --say`). Stream a synthesised presentation WAV containing a planted weak claim and print a compact event summary. Most loops shouldn't need "run it and tell me what you heard".
