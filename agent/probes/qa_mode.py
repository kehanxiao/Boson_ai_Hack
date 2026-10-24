"""Kill test K5: fact-check during the presentation, and the options for Q&A turn-taking.

Finding from the first run: turn_detection cannot be changed after session start
(invalid_request_error), so Q&A either stays on our manual turns or uses a second session.

Part 1, the presentation session (turn_detection: null):
  K5a  web_search with the fact-check cue delivered as a conversation item (response.input),
       so the server's follow-up answer still knows what to say
  K5f  mid-session session.update of instructions only (phase change) is accepted
  K5d  code-switched answers (English + Indonesian / Mandarin) on our manual turns get an on-topic reply

Part 2, a fresh session that starts with automatic turns (semantic_vad, fallback server_vad 1200 ms):
  K5b  automatic turn detection is accepted at session start
  K5c  a 2.5 s thinking pause mid-answer does not make the examiner jump in
  K5g  a code-switched answer gets an automatic reply
  K5e  native barge-in: presenter speech during the examiner's answer cancels it

    cd agent && uv run probes/qa_mode.py
"""

import asyncio

import websockets

from common import AUTH, EXAMINER, REALTIME_URL, Probe, log, now, print_results, session_update, tts_pcm

CLAIM = "For the model we used LightGBM, which Google released in 2020, with rolling-window validation."
FACT_CHECK_NOTE = (
    "[Director cue: the presenter just claimed LightGBM was released by Google in 2020. Use web search to check who "
    "released LightGBM and when, then state the correction to the presenter in one or two short sentences.]"
)
QA_INSTRUCTIONS = (
    EXAMINER + " This is the question-and-answer phase. The presenter may answer in Indonesian, Mandarin or a mix "
    "with English; understand them and reply in English. React to what they actually said, then ask one follow-up question."
)
QA_QUESTION = "[Director cue: ask the presenter whether 'time to first physician' is known at prediction time.]"
PAUSE_PART1 = "So the main reason we chose gradient boosting was"
PAUSE_PART2 = "that it handles missing values and mixed feature types without much preprocessing."
INDONESIAN = "Good question. Jujur saja, kami belum cek apakah waktu ke dokter itu masuk ke target, tapi kami bisa retrain tanpa fitur itu."
MANDARIN = "我们用的是滚动窗口验证, rolling origin, so no future data leaks into training."
LONG_CUE = EXAMINER + " Explain, in at least eight full sentences, what a rigorous external validation would involve."
BARGE_IN = "Sorry, can I stop you there? I think I already covered that."


def note(text: str) -> dict:
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def last_reply(probe: Probe, after: float) -> str:
    replies = [e.get("transcript", "") for e in probe.seen("response.output_audio_transcript.done", after)]
    return replies[-1] if replies else ""


async def part1(results: dict) -> None:
    claim, indonesian, mandarin = tts_pcm(CLAIM), tts_pcm(INDONESIAN), tts_pcm(MANDARIN)
    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws:
        probe = Probe(ws)
        receiver = asyncio.create_task(probe.receive())
        await probe.send(session_update(EXAMINER, None, tools=[{"type": "web_search"}]))
        await asyncio.sleep(1.5)

        # K5a: fact-check, cue as a conversation item.
        await probe.stream(claim, "claim")
        await probe.send({"type": "input_audio_buffer.commit"})
        t_fc = now()
        await probe.send({"type": "response.create", "response": {"input": [note(FACT_CHECK_NOTE)]}})
        log("response.create (fact-check cue as response.input)")
        await asyncio.sleep(20)
        calls = [e["item"] for e in probe.seen("conversation.item.added", t_fc) if e.get("item", {}).get("type") == "function_call"]
        spoken = [e.get("transcript", "") for e in probe.seen("response.output_audio_transcript.done", t_fc)]
        done_times = probe.seen_at("response.done", t_fc)
        searched = any(c.get("name") == "web_search" and c.get("executor") == "server" for c in calls)
        corrected = any("microsoft" in s.lower() for s in spoken)
        results["K5a fact-check (cue as conversation item)"] = (
            f"{'PASS' if searched and corrected else 'CHECK'} (searched={searched}, corrected={corrected}, "
            f"answer at +{(done_times[-1] - t_fc):.1f}s, spoken={spoken!r})" if done_times else f"FAIL (no response; spoken={spoken!r})"
        )

        # K5f: phase change by updating instructions only.
        t_up = now()
        await probe.send({"type": "session.update", "session": {"instructions": QA_INSTRUCTIONS}})
        await asyncio.sleep(1.5)
        errs = probe.seen("error", t_up)
        results["K5f instructions-only update mid-session"] = (
            "PASS" if probe.seen("session.updated", t_up) and not errs else f"FAIL (errors={[e['error'].get('message') for e in errs]})"
        )

        # K5d: code-switched answers on our manual turns.
        t_q = now()
        await probe.send({"type": "response.create", "response": {"input": [note(QA_QUESTION)]}})
        await probe.wait_for("response.done", t_q, timeout=15)
        log(f"examiner asked: {last_reply(probe, t_q)!r}")
        for label, pcm in (("Indonesian mix", indonesian), ("Mandarin mix", mandarin)):
            await probe.stream(pcm, label)
            await probe.silence(0.5)
            t_c = now()
            await probe.send({"type": "input_audio_buffer.commit"})
            await probe.send({"type": "response.create"})
            done = await probe.wait_for("response.done", t_c, timeout=15)
            first_audio = [t for t, e in probe.events if t >= t_c and e["type"] == "response.output_audio.delta"]
            lat = f"first audio +{(first_audio[0] - t_c) * 1000:.0f} ms after commit" if first_audio else "no audio"
            results[f"K5d {label} (manual turns)"] = f"PASS ({lat}; reply={last_reply(probe, t_c)!r})" if done else "FAIL (no reply)"
        receiver.cancel()


async def part2(results: dict) -> None:
    part_1, part_2, indonesian, barge = tts_pcm(PAUSE_PART1), tts_pcm(PAUSE_PART2), tts_pcm(INDONESIAN), tts_pcm(BARGE_IN)
    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws:
        probe = Probe(ws)
        receiver = asyncio.create_task(probe.receive())

        # K5b: automatic turns from the start.
        mode = "semantic_vad"
        await probe.send(session_update(QA_INSTRUCTIONS, {"type": "semantic_vad"}))
        await asyncio.sleep(2)
        if probe.seen("error", 0):
            mode = "server_vad (1200 ms)"
            log("semantic_vad rejected at start; trying server_vad")
            await ws.close()
            receiver.cancel()
            async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws2:
                await run_auto_checks(Probe(ws2), mode, {"type": "server_vad", "silence_duration_ms": 1200}, part_1, part_2, indonesian, barge, results)
            return
        results["K5b automatic turns accepted at start"] = f"PASS ({mode})"
        await run_auto_checks(probe, mode, None, part_1, part_2, indonesian, barge, results)
        receiver.cancel()


async def run_auto_checks(probe, mode, turn_detection, part_1, part_2, indonesian, barge, results) -> None:
    if turn_detection is not None:  # fresh fallback session
        _receiver = asyncio.create_task(probe.receive())  # referenced so it isn't collected; ends with the connection
        await probe.send(session_update(QA_INSTRUCTIONS, turn_detection))
        await asyncio.sleep(2)
        results["K5b automatic turns accepted at start"] = f"PASS ({mode})" if not probe.seen("error", 0) else f"FAIL ({mode})"

    # K5c: thinking pause.
    t_p = now()
    await probe.stream(part_1, "answer, part 1")
    await probe.silence(2.5)
    early = bool(probe.seen("response.created", t_p))
    await probe.stream(part_2, "answer, part 2")
    await probe.silence(4.0)
    replied = bool(probe.seen("response.created", t_p))
    results[f"K5c 2.5 s pause, no jump-in ({mode})"] = "PASS" if replied and not early else f"FAIL (jumped in during pause={early}, replied={replied})"
    await probe.wait_for("response.done", t_p, timeout=10)
    await probe.silence(1.0)

    # K5g: code-switched answer, automatic reply.
    t_a = now()
    await probe.stream(indonesian, "Indonesian mix")
    t_end = now()
    await probe.silence(4.0)
    await probe.wait_for("response.done", t_a, timeout=10)
    first_audio = [t for t, e in probe.events if t >= t_end and e["type"] == "response.output_audio.delta"]
    lat = f"first audio +{(first_audio[0] - t_end) * 1000:.0f} ms after speech end" if first_audio else "no audio"
    reply = last_reply(probe, t_a)
    results["K5g Indonesian mix, automatic reply"] = f"PASS ({lat}; reply={reply!r})" if reply else "FAIL (no reply)"
    await probe.silence(1.0)

    # K5e: barge-in during a long answer.
    t_b = now()
    await probe.send({"type": "response.create", "response": {"instructions": LONG_CUE}})
    for _ in range(300):
        if probe.first_audio_at is not None and probe.response_active:
            break
        await asyncio.sleep(0.01)
    await probe.stream(barge, "barge-in, right after the first audio")
    await probe.silence(3.0)
    statuses = [e.get("response", {}).get("status") for e in probe.seen("response.done", t_b)]
    started = bool(probe.seen("input_audio_buffer.speech_started", t_b))
    truncated = bool(probe.seen("conversation.item.truncated", t_b))
    results["K5e native barge-in"] = (
        f"{'PASS' if 'cancelled' in statuses else 'CHECK'} (speech_started={started}, statuses={statuses}, server truncated={truncated})"
    )


async def main() -> None:
    results: dict[str, str] = {}
    log("=== part 1: presentation session (manual turns) ===")
    await part1(results)
    log("=== part 2: fresh session with automatic turns ===")
    await part2(results)
    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
