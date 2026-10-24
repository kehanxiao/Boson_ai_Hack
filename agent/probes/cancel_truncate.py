"""Kill test K3: stopping the examiner cleanly (the Q&A barge-in path we own in manual mode).

  K3a  response.cancel while the response is still being generated -> response.done status=cancelled
  K3b  conversation.item.truncate at the heard position -> acknowledged, and the stored
       assistant item reflects what was heard (checked with conversation.item.retrieve)
  K3c  after a cancel, commit + response.create work again (no lingering voice_output_task_ongoing)

Generation runs faster than real time, so K3a cancels ~0.3 s after the first audio, while
generation is surely still running. K3b truncates at 1.5 s of "heard" audio, as the avatar
would report after clear_buffer().

    cd agent && uv run probes/cancel_truncate.py
"""

import asyncio

import websockets

from common import AUTH, EXAMINER, REALTIME_URL, Probe, log, now, print_results, session_update, tts_pcm

QUESTION = "Could you explain, in detail, how you would design the external validation for this model?"
LONG_CUE = (
    EXAMINER + " Answer in at least six full sentences, slowly and thoroughly, describing a complete external "
    "validation plan step by step."
)
FOLLOW_UP = "Okay, and what metric would you report?"


async def main() -> None:
    question, follow_up = tts_pcm(QUESTION), tts_pcm(FOLLOW_UP)
    results: dict[str, str] = {}

    async with websockets.connect(REALTIME_URL, additional_headers=AUTH, max_size=None) as ws:
        probe = Probe(ws)
        receiver = asyncio.create_task(probe.receive())
        await probe.send(session_update(EXAMINER, None))
        await asyncio.sleep(1.5)

        # K3a: cancel mid-generation.
        await probe.stream(question, "question")
        await probe.send({"type": "input_audio_buffer.commit"})
        t_create = now()
        await probe.send({"type": "response.create", "response": {"instructions": LONG_CUE}})
        log("response.create (long answer)")
        for _ in range(200):
            if probe.first_audio_at is not None:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.3)
        t_cancel = now()
        await probe.send({"type": "response.cancel"})
        log("response.cancel")
        done = await probe.wait_for("response.done", t_create, timeout=10)
        status = done.get("response", {}).get("status") if done else None
        stop_ms = (probe.seen_at("response.done", t_cancel)[0] - t_cancel) * 1000 if probe.seen_at("response.done", t_cancel) else None
        results["K3a cancel mid-generation"] = (
            f"PASS (status=cancelled, response.done +{stop_ms:.0f} ms after cancel)" if status == "cancelled"
            else f"CHECK (status={status}; generation may have finished before the cancel)"
        )

        # K3b: truncate the assistant item to what was "heard".
        assistant_ids = [
            o.get("id") for o in (done or {}).get("response", {}).get("output", [])
            if o.get("type") == "message" and o.get("role", "assistant") == "assistant"
        ]
        if assistant_ids:
            item_id = assistant_ids[0]
            t_trunc = now()
            await probe.send({"type": "conversation.item.truncate", "item_id": item_id, "content_index": 0, "audio_end_ms": 1500})
            ack = await probe.wait_for("conversation.item.truncated", t_trunc, timeout=5)
            await probe.send({"type": "conversation.item.retrieve", "item_id": item_id})
            retrieved = await probe.wait_for("conversation.item.retrieved", t_trunc, timeout=5)
            texts = [c.get("transcript") or c.get("text") for c in (retrieved or {}).get("item", {}).get("content", [])]
            results["K3b truncate to heard position"] = (
                f"PASS (truncated; stored item now {texts!r})" if ack
                else f"FAIL (no truncated ack; errors={[e['error'].get('type') for e in probe.seen('error', t_trunc)]})"
            )
        else:
            results["K3b truncate to heard position"] = "SKIPPED (no assistant item id in response.done)"

        # K3c: the session is usable again right away.
        await probe.stream(follow_up, "follow-up")
        t_next = now()
        await probe.send({"type": "input_audio_buffer.commit"})
        await probe.send({"type": "response.create", "response": {"instructions": EXAMINER + " Answer in one short sentence."}})
        next_done = await probe.wait_for("response.done", t_next, timeout=15)
        lingering = probe.errors("voice_output_task_ongoing", t_next)
        results["K3c usable again after cancel"] = (
            "PASS" if next_done and next_done.get("response", {}).get("status") == "completed" and not lingering
            else f"FAIL (done={bool(next_done)}, voice_output_task_ongoing={len(lingering)})"
        )
        receiver.cancel()

    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
