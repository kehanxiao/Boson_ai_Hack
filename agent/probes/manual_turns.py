"""Kill tests K1, K2 and K4: manual turn control on Higgs Realtime. No LiveKit, no avatar, no human.

A synthetic presenter (Higgs TTS, cached under probes/.cache/) talks into a Realtime
session that has turn_detection: null, and the probe checks:

  K4   a slide note sent as conversation.item.create triggers no response
  K1   input_audio_buffer.commit yields a transcript and no automatic response
  K2   response.create while the presenter is still talking makes the examiner speak;
       audio keeps streaming in, the response is not cancelled; latency is measured
  K2b  commit during an active response is rejected (voice_output_task_ongoing)
  K1b  after response.done, a commit of the audio spoken meanwhile is accepted

    cd agent && uv run probes/manual_turns.py
"""

import asyncio

import websockets

from common import AUTH, EXAMINER, RATE, REALTIME_URL, Probe, log, now, print_results, session_update, tts_pcm

SEG_INTRO = "Hi everyone. Today I'm presenting ERwait, a system for forecasting emergency room wait times."
SEG_CLAIM = "And the headline result: our model is forty percent better, which is a big step forward for the hospital."
SEG_CONTINUE = (
    "Now let me walk you through the data. We used two years of triage records, about one point two million "
    "visits, and we removed the outliers before training. We also added weather and holiday features, and we "
    "split the data by time so that the model never sees the future."
)
CUE = (
    EXAMINER + " Interject now, while the presenter is mid-flow. In one short sentence, cut in and ask what the "
    "forty percent is relative to and on which metric."
)


async def main() -> None:
    log("generating presenter audio (cached after the first run)")
    intro, claim, cont = tts_pcm(SEG_INTRO), tts_pcm(SEG_CLAIM), tts_pcm(SEG_CONTINUE)
    results: dict[str, str] = {}

    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws:
        probe = Probe(ws)
        receiver = asyncio.create_task(probe.receive())
        await probe.send(session_update(EXAMINER + " During the presentation, stay silent unless you are explicitly asked to respond.", None))
        await asyncio.sleep(1.5)

        # K4: a slide note is context only.
        t = now()
        await probe.send({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "[Context note: the presenter is now on slide 3, which claims the model is 40% better with no baseline or metric.]"}]}})
        await asyncio.sleep(3)
        results["K4 slide note triggers no response"] = "PASS" if not probe.seen("response.created", t) else "FAIL (a response was generated)"

        # K1: commit yields a transcript and no automatic response.
        await probe.stream(intro, "intro")
        await probe.silence(0.6)
        t = now()
        await probe.send({"type": "input_audio_buffer.commit"})
        log("commit (intro)")
        await probe.silence(4.0)  # keep the mic 'open' with silence, like a live presenter pausing
        got_transcript = bool(probe.seen("conversation.item.input_audio_transcription.completed", t))
        auto_response = bool(probe.seen("response.created", t))
        results["K1 commit -> transcript, no auto-response"] = (
            "PASS" if got_transcript and not auto_response
            else f"FAIL (transcript={got_transcript}, auto_response={auto_response})"
        )

        # K2: the presenter makes the claim and keeps talking; we trigger an interjection mid-flow.
        await probe.stream(claim, "claim")
        await probe.send({"type": "input_audio_buffer.commit"})
        log("commit (claim)")
        cont_task = asyncio.create_task(probe.stream(cont, "keeps talking"))
        await asyncio.sleep(0.4)
        t_create = now()
        await probe.send({"type": "response.create", "response": {"instructions": CUE}})
        log("response.create (director cue) while the presenter is still talking")

        # K2b: a commit during the active response should be rejected.
        for _ in range(60):
            if probe.response_active:
                break
            await asyncio.sleep(0.05)
        t_commit_during = now()
        await probe.send({"type": "input_audio_buffer.commit"})
        log("commit during the active response (expect rejection)")

        await cont_task
        done = await probe.wait_for("response.done", t_create, timeout=20)
        status = done.get("response", {}).get("status") if done else None
        spoke = probe.first_audio_at is not None and probe.audio_bytes > 0
        lat_created = (probe.created_at - t_create) * 1000 if probe.created_at else None
        lat_audio = (probe.first_audio_at - t_create) * 1000 if probe.first_audio_at else None
        results["K2 interjection while presenter talks"] = (
            f"PASS (status={status}, response.created +{lat_created:.0f} ms, first audio +{lat_audio:.0f} ms, "
            f"spoke {probe.audio_bytes / (RATE * 2):.1f}s)" if spoke and status == "completed"
            else f"FAIL (spoke={spoke}, status={status})"
        )
        rejected = probe.errors("voice_output_task_ongoing", t_commit_during)
        results["K2b commit during response is rejected"] = "PASS (as documented)" if rejected else "NOT REJECTED (commit accepted mid-response)"

        # K1b: after the response, the audio spoken meanwhile can be committed.
        t = now()
        await probe.send({"type": "input_audio_buffer.commit"})
        log("commit after response.done")
        await probe.silence(4.0)
        results["K1b commit after response is accepted"] = (
            "PASS" if probe.seen("conversation.item.input_audio_transcription.completed", t) and not probe.errors("voice_output_task_ongoing", t)
            else "FAIL (no transcript or rejected)"
        )
        receiver.cancel()

    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
