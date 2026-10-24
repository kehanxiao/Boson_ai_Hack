# Viva: the 10-minute talk (group round and finals)

The **15:00 group round** is 10 minutes including questions, and peers vote. The **17:00 finals** are 10 minutes plus Q&A, and the judges choose. The audience is fellow students as well as judges, so lead with the problem everyone in the room has had, and keep the Higgs internals for the second half.

Judging: Use of Higgs 30%, UX 25%, Innovation 25%, Technical Execution 20%.

## Before you go on
- Start the avatar agent early: `cd agent && uv run main.py demo3`, and wait for `ready`. Avatar slots are shared by every team at 3 PM.
- If no avatar slot is free, use `VIVA_AVATAR=0 uv run main.py demo3` (voice only). If the room or the network fails, play the video.
- Use a headset, and make sure nobody near the mic is talking: she hears every voice as yours.
- Open http://localhost:5173/session/demo3 and keep [`demo-script-3min.md`](demo-script-3min.md) next to you.

## Run of show (about 7 min of talk, then questions)

| Time | Part | Say / do |
|---|---|---|
| 0:00–1:00 | **The problem** | "Who here has a thesis defense, a capstone presentation or an assignment oral coming up? Every AI tool you have is built to be your assistant: it agrees with you. Practising a defense needs the opposite, an examiner who stops you at the weak claim and won't let you run over time." |
| 1:00–4:15 | **Live demo** (demo3, 3 min) | Follow the script. Let her interrupt and don't narrate over her. Point at the screen only when she gives the reminder or runs the search. |
| 4:15–5:00 | **What you just saw** | She cut in at your next breath, on claims grounded in your slides. She held the floor when you talked over her. She checked a fact on the web, kept time, escalated when you ignored her, and followed an answer in Indonesian. (If you went quiet for 4 s, she also urged you on.) |
| 5:00–7:00 | **How it uses Higgs** (for the judges) | See "The Higgs story" below. Show the architecture diagram from the README. |
| 7:00–7:30 | **Honest limits, and what's next** | Pick two: she cuts in at pauses, not mid-word (~2–3 s with the avatar); there's no speaker separation; she sometimes drills one topic. Next: speaker separation, a per-topic cap, and tone control once the Realtime voice supports it. |
| 7:30–10:00 | **Questions** | See the likely questions below. |

For the finals (10 min + Q&A) there is room to stretch "How it uses Higgs" and show the Setup page: upload a deck, pick an examiner, and the slides are analysed in 3–8 s.

## The Higgs story (5:00–7:00)
1. **Higgs is the examiner's brain, not just her voice.** A second, text-only Higgs Realtime session hears your audio directly. At each pause it answers one line: stay silent, say something, or check a fact. No transcript is waited for. On a talk with 6 planted errors it caught 6/6 at ~0.45 s per decision; Claude Haiku reading transcripts caught 5–6/6 at 1.5–1.9 s.
2. **We own the turn-taking.** Manual turns (`turn_detection: null`) on both sessions, with our own VAD. That's what lets her interrupt *you*, hold the floor for 1.5 s, and decide whether being talked over means "let me finish" or a real answer. Clean cancellation: `response.cancel` → avatar `clear_buffer()` → `conversation.item.truncate`.
3. **Tool calling:** server-executed `web_search`, so the fact-check is live and the presenter hears the evidence.
4. **Code-switching:** answer in Indonesian or Mandarin and she follows you in English.
5. **Higgs Avatar** on LiveKit Cloud gives her a face, with a voice-only fallback.
6. **Why it wouldn't work with a generic TTS:** the decision comes from a model that *hears* you (hesitation, a self-correction, talking over her), not from a transcript, and the same family of models speaks, searches and transcribes.

## Likely questions
- **Why two Realtime sessions and not one?** An audio response can't be silent, and the voice refuses new turns while it speaks or searches. Dozens of "stay silent" turns would also fill her spoken conversation. One session also can't switch to text output per response (tested).
- **How do you stop her from interrupting all the time?** The character sets it: after she speaks she waits 3–4 s before raising something new, presses a point once (twice for The Skeptic), and then lets it go. Most decisions are SILENT.
- **Does it work on any deck?** Yes: upload a PDF on the Setup page. Claude Haiku analyses each slide (claims, weak points, likely questions) in 3–8 s. She learns a slide's weak points only after you have talked about it for ~5 s, so she doesn't jump ahead.
- **How fast is it?** Pause → her decision ~1 s; you hear her ~2–3 s after you stop with the avatar (~1.4 s of that is the avatar), ~1.4 s voice-only.
- **What about the scorecard?** After the exam, Claude Haiku scores clarity, rigour, handling questions and time management from the session log. Every quote and timestamp is checked against the log in code.
- **What was hardest?** Turn-taking as concurrency: knowing exactly when the room hears her (the avatar doesn't report playback start), and keeping the brain's memory true to what was actually heard.
- **Could you control her tone?** We tested it: per-line tone instructions and Higgs TTS tags made no audible difference on the Realtime 1.5 preview voice, so her character comes from what she says and when.
