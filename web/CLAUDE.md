# web/: Role B, presenter-facing app (Vite + React + TypeScript)

Pages: `Setup` → `Session` → `Scorecard`. The message and API contract is **fixed** by `PLAN.md` → "Interfaces between A and B".

Stack: Vite, React, TS, `livekit-client`. Server base URL comes from `VITE_SERVER_URL`.

## Pages
- **Setup:** the 5 inputs:
  1. scenario preset
  2. character (presets from `demo/characters.json`, plus a custom text box), and face and voice or voice only (`avatar`)
  3. slides PDF + an optional support doc
  4. time limit + Q&A length
  5. notes

  Submit with `POST /api/sessions` → go to `Session` with the `session_id`.
- **Session:**
  - `AvatarStage`: video and audio of participant `boson-avatar`.
  - `SlideViewer`: images from SessionConfig `slides[].image_url`, with prev/next.
  - `Timer`
  - No transcript on screen: the interface is voice only (Sat 10:40). `caption` messages still arrive and the log keeps every line for the scorecard.
  - `ExaminerState` badge: listening / interjecting / holding the floor / Q&A / debrief.
  - `LatencyHud`
  - Fetch `GET /api/sessions/{id}`, then `GET /token?room={id}&identity=presenter`.
- **Scorecard:** `GET /api/sessions/{id}/scorecard`.
  - The verdict
  - criteria scores
  - timestamped moments (strong / weak / unacknowledged), with slide thumbnails
  - top 3 improvements

## LiveKit wiring
- Connect, then publish the microphone **with source = microphone**. The agent only listens to `SOURCE_MICROPHONE` tracks (tutorial note).
- **Send (`viva.ctl`):** `room.localParticipant.sendText(JSON.stringify(msg), { topic: "viva.ctl" })`. Send `{type:"start"}` on start, `{type:"slide", index}` on every slide change, `{type:"phase", ...}` on manual phase buttons.
- **Receive (`viva.ui`):** `room.registerTextStreamHandler("viva.ui", async (reader) => JSON.parse(await reader.readAll()))`.
- Check exact signatures against the installed `livekit-client` version.

## Build before the agent exists
Add a dev-only "fake agent" that replays `viva.ui` events, derived from `demo/sample-log.jsonl`, on a timer. Then the whole Session page can be built and styled without Role A. Use `session_id = "demo"` against the server.

## UX priorities (25% of judging)
- The examiner's *state* must always be obvious: listening, interjecting, holding the floor.
- Reminders should be visible as well as spoken.
- Big slide, clear timer.
- Keep components small, one per file.
