"""The exam controller: phases, timer, director, holding the floor, reminders and acknowledgement.

Inputs:  presenter audio frames, viva.ctl messages, Realtime events, playback-finished callbacks.
Outputs: Realtime requests, viva.ui messages, session log lines.
Design: PLAN.md "Core design decisions"; protocol facts: agent/CLAUDE.md.

Every examiner utterance is one Realtime response. Utterances we ask for are tracked from
request to "finished playing"; the server's own follow-up after a web search is tracked too.
"""

import asyncio
import base64
import logging
import re
import time
from collections import deque

import instructions as prompts
from vad import PauseDetector

log = logging.getLogger("viva.exam")

HOLD_S = 1.5  # the examiner keeps the floor this long after starting to speak
VAD_SILENCE_S = 0.6  # pause length that triggers a commit
COOLDOWN_S = {"high": 20, "medium": 30, "low": 45}  # minimum gap between interjections
FACTCHECK_COOLDOWN_S = 10  # fact-checks are worth it even soon after an interjection
MAX_CHUNK_S = 10  # force a commit during long unbroken speech so the director isn't blind
# Watchdog: nothing may leave the examiner stuck "busy" (that would silence reminders and phases).
REQUEST_TIMEOUT_S = 8  # response.create that never produced response.created
SEARCH_TIMEOUT_S = 12  # server web_search whose follow-up answer never came
PLAYBACK_SLACK_S = 4  # an utterance's playback_finished may be lost; give up this long after it should end
MERGED_REPORT_SLACK_S = 1.0  # one avatar report also finishes queued utterances due to end within this margin
PATIENCE_S = {"high": 1.0, "medium": 1.3, "low": 1.6}  # Q&A silence before the examiner replies
NO_INTERJECTION_BEFORE_S = 20
ACK_SILENCE_S = 1.0  # going quiet this long after a reminder counts as acknowledging it
IGNORE_AFTER_S = 3.5  # still talking this long after a reminder means it was ignored

STT_PLACEHOLDER = "the transcription is not available"  # seen live from higgs-stt-3.1 when it fails
BARGE_IN_S = 0.8  # presenter speech this long past the hold window cancels the examiner (Q&A); "um" is shorter
MIN_ANSWER_WORDS = 3  # a Q&A turn needs this many non-filler words before the examiner replies
AWAIT_REPLY_S = 25  # after an interjection, how long the examiner waits for the presenter's answer
DEFERRED_FACTCHECK_S = 30  # a fact-check held back by its spacing rule is dropped if it can't fire within this
# "Can I continue?" (live run: asked twice, ignored both times by the director as "procedural").
CONTINUE_ASK = re.compile(r"\b(can|may|shall|should|could) i (continue|go on|move on|carry on|proceed)\b|"
                          r"\b(is that (ok|okay|fine|enough)|boleh lanjut|bisa lanjut)\b|可以继续", re.I)
FILLERS = {"um", "uh", "uhm", "erm", "er", "ah", "oh", "hmm", "mm", "yeah", "yes", "no", "okay", "ok", "so", "well",
           "right", "sorry", "like", "the", "a", "and", "i", "oke", "ya", "eh", "嗯", "啊", "哦"}
ACK_WORDS = re.compile(r"\b(okay|ok|noted|yes|yep|got it|sure|understood|right|thanks|thank you|baik|oke|siap)\b", re.I)
ACK_CJK = ("好的", "明白", "知道")
URL = re.compile(r"https?://[^\s)\]>\"']+")
INDONESIAN = re.compile(r"\b(saya|kami|kita|tidak|belum|sudah|bisa|itu|ini|yang|dengan|untuk|karena|tapi|jujur|apakah|waktu)\b", re.I)


def content_words(text: str) -> int:
    """Words that carry an answer: fillers ("um", "yeah", "okay") don't count. CJK characters count as words."""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    words = [w for w in re.findall(r"[a-zA-Z']+", text.lower()) if w not in FILLERS]
    return len(words) + cjk // 2


def interrupts_on_minor(character: dict) -> bool:
    """Only the strictest characters (strictness 5, e.g. The Skeptic) cut in for minor issues too."""
    return int(character.get("strictness", 3)) >= 5


def guess_lang(text: str) -> str:
    if any("一" <= ch <= "鿿" for ch in text):
        return "zh"
    if len(INDONESIAN.findall(text)) >= 2:
        return "id"
    return "en"


class ExamController:
    def __init__(self, config, realtime, output, ui, slog, director, *, factcheck=True, reminder_before_s=120):
        self.config = config
        self.realtime = realtime
        self.output = output
        self.ui = ui
        self.slog = slog
        self.director = director
        self.factcheck_enabled = factcheck
        self.reminder_before_s = reminder_before_s

        # The character drives interruption behaviour (PLAN.md "Character drives the examiner's behaviour").
        character = config["character"]
        self.cooldown = COOLDOWN_S.get(character.get("interrupt_rate", "medium"), 30)
        self.patience = PATIENCE_S.get(character.get("interrupt_rate", "medium"), 1.3)
        self.minor_ok = interrupts_on_minor(character)
        self.last_slide = max((s["index"] for s in config.get("slides", [])), default=1)

        self.phase = "waiting"
        self.slide = 1
        self.started = 0.0
        self.ended = asyncio.Event()
        self.completed = False  # True only when the exam reached its verdict (abort() leaves it False)
        self.vad = PauseDetector(self.on_speech_start, self.on_pause, min_silence=VAD_SILENCE_S)

        # Presenter state
        self.presenter_speaking = False
        self.pause_at: float | None = None  # when the latest pause was detected
        self.silent_since: float | None = None
        self.last_speech_start = 0.0
        self.last_examiner_request = 0.0
        self.answer_words = 0
        # After an interjection has played the presenter owes an answer: {"since", "asked", "answer": [chunks]}.
        # The director judges the answer (acknowledge / keep waiting / fact-check) with that context.
        self.awaiting: dict | None = None
        self.pending_ack: str | None = None  # an acknowledgement decided while the presenter was still talking
        self.deferred: tuple | None = None  # (decision, meta, at): a fact-check blocked only by its spacing rule
        self.last_examiner_text = ""
        self.last_commit = 0.0
        self.chunk_slide = 1  # slide showing when the current chunk of speech began
        self.commits: deque[dict] = deque()  # per commit, in order: the chunk's slide and pause time
        self.recent: deque[str] = deque(maxlen=8)

        # Examiner utterances: requested -> generating -> playing -> finished
        self._requested: dict | None = None
        self._current: dict | None = None
        self.playing: deque[dict] = deque()
        self.hold_until = 0.0
        self.pending_metric: tuple[str, float] | None = None
        self.cancel_at: float | None = None

        # Director, reminders, Q&A, fact-check
        self.director_busy = False
        self._director_next: tuple[str, dict] | None = None  # newest chunk that arrived while busy
        self.interjections: list[str] = []
        self.interjected_slides: set[int] = set()
        self.last_interjection = -1e9
        self.last_factcheck = -1e9
        self.reminder: dict | None = None
        self.questions: list[str] = []
        self.qa_turn: asyncio.Task | None = None
        self.factcheck: dict | None = None
        self._tasks: list[asyncio.Task] = []

        output.on_finished(lambda played, interrupted: self._spawn(self._playback_finished(played, interrupted)))

    # ------------------------------------------------------------------ helpers
    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        if task in self._tasks:
            self._tasks.remove(task)
        if not task.cancelled() and task.exception():
            log.error("background task failed", exc_info=task.exception())

    def elapsed(self) -> float:
        return time.monotonic() - self.started if self.started else 0.0

    @property
    def engaged(self) -> bool:
        """The examiner is about to speak, speaking, or the server is preparing a follow-up."""
        return bool(self._requested or self._current or self.playing or self.realtime.busy)

    @property
    def examiner_audible(self) -> bool:
        return bool(self.playing) or bool(self._current and self._current.get("audio"))

    async def ui_state(self, state: str) -> None:
        await self.ui.publish({"type": "state", "state": state})

    async def idle_state(self) -> None:
        if not self.engaged:
            await self.ui_state({"presentation": "listening", "qa": "qa", "debrief": "debrief"}.get(self.phase, self.phase))

    async def metric(self, name: str, ms: float) -> None:
        log.info("metric %s %.0f ms", name, ms)
        await self.ui.publish({"type": "latency", "metric": name, "ms": int(ms)})

    async def wait_idle(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while self.engaged and time.monotonic() < deadline:
            await asyncio.sleep(0.1)

    async def say(self, kind: str, cue: str, *, hold=False, max_tokens: int | None = 120, metric: str | None = None,
                  ref: float | None = None) -> bool:
        if self.engaged:
            return False
        phase = self.phase if self.phase in prompts.PHASES else "presentation"
        self._requested = {"kind": kind, "hold": hold, "at": time.monotonic()}
        self.last_examiner_request = time.monotonic()
        self.answer_words = 0  # counts the presenter's real words since this request
        if not await self.realtime.create_response(prompts.with_cue(self.config, phase, cue, self.interjections), max_tokens):
            self._requested = None
            return False
        if metric:
            self.pending_metric = (metric, ref or self.pause_at or time.monotonic())
        if kind in ("interjection", "factcheck", "reminder", "escalation", "time_up"):
            await self.ui_state("interjecting")
        return True

    # ------------------------------------------------------------------ inputs
    async def on_ctl(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "start" and self.phase == "waiting":
            await self.begin()
        elif kind == "slide":
            await self.on_slide(int(msg["index"]))
        elif kind == "phase":
            if msg.get("phase") == "qa" and self.phase == "presentation":
                await self.enter_qa()
            elif msg.get("phase") == "end" and self.phase in ("presentation", "qa"):
                await self.enter_debrief()

    async def on_presenter_audio(self, frame) -> None:
        if self.phase in ("waiting", "ended") or not self.realtime.connected:
            return  # nothing to hear before Start; and never write to a closed connection
        await self.realtime.append(bytes(frame.data))
        self.vad.push(frame)
        if self.presenter_speaking and time.monotonic() - self.last_commit > MAX_CHUNK_S:
            await self._commit()  # long unbroken speech: chunk it anyway

    async def _commit(self) -> None:
        self.last_commit = time.monotonic()
        meta = {"slide": self.chunk_slide, "pause_at": self.last_commit}
        outcome = await self.realtime.commit()
        if outcome in ("sent", "queued"):
            self.commits.append(meta)
        elif outcome == "merged" and self.commits:
            self.commits[-1]["pause_at"] = meta["pause_at"]  # one transcript will cover both
        self.chunk_slide = self.slide

    async def on_speech_start(self) -> None:
        self.presenter_speaking = True
        self.silent_since = None
        self.last_speech_start = time.monotonic()
        if time.monotonic() - self.last_commit > 0.3:
            self.chunk_slide = self.slide
        if self.qa_turn:
            self.qa_turn.cancel()  # they are still answering
            self.qa_turn = None
        if self.examiner_audible:
            if time.monotonic() < self.hold_until:
                await self.ui_state("holding_floor")
            if self.phase == "qa":
                self._spawn(self._maybe_barge_in())

    async def on_pause(self) -> None:
        self.presenter_speaking = False
        self.pause_at = time.monotonic()
        self.silent_since = self.pause_at - VAD_SILENCE_S
        await self._commit()  # queued by the client if a response is being generated
        if self.phase == "qa":
            if self.qa_turn:
                self.qa_turn.cancel()
            self.qa_turn = self._spawn(self._qa_end_of_turn())
        elif self.phase == "presentation" and self.pending_ack and not self.engaged:
            cue, self.pending_ack = self.pending_ack, None  # decided while they were still talking
            await self.say("ack", f"Say, in character: \"{cue}\"", max_tokens=40, metric="answer_end_to_reply")

    async def on_slide(self, index: int) -> None:
        if index == self.slide:
            return
        self.slide = index
        self.slog.write("slide", index=index)
        summary = next((s.get("summary", "") for s in self.config.get("slides", []) if s["index"] == index), "")
        await self.realtime.add_note(f"[Context note: the presenter moved to slide {index}. {summary}]")
        if self.reminder and not self.reminder["acked"] and index == self.last_slide:
            await self.acknowledge("slide_jump")

    async def on_transcript(self, text: str) -> None:
        meta = self.commits.popleft() if self.commits else {"slide": self.slide, "pause_at": time.monotonic()}
        text = text.strip()
        if not text or text.lower().startswith(STT_PLACEHOLDER):
            return  # nothing said, or the STT service's placeholder when it fails
        lang = guess_lang(text)
        entry = self.slog.write("chunk", slide=meta["slide"], lang=lang, text=text)
        await self.ui.publish({"type": "caption", "role": "presenter", "text": text, "lang": lang, "t": entry["t"]})
        self.recent.append(f"slide {meta['slide']}: {text}")
        r = self.reminder
        if r and not r["acked"] and r["played_at"] and (ACK_WORDS.search(text) or any(w in text for w in ACK_CJK)):
            await self.acknowledge("phrase")
        if self.phase == "presentation" and CONTINUE_ASK.search(text) and not self.engaged:
            self.awaiting = self.pending_ack = None
            await self.say("ack", "The presenter asked whether they may continue. Tell them in a few words that "
                           "they may.", max_tokens=30)
        elif self.phase == "presentation":
            if self.awaiting:
                self.awaiting["answer"].append(text)
                if content_words(text) < 2:
                    return  # "okay", "haha": keep waiting, no director call
            self._spawn(self.maybe_direct(text, meta))
        elif self.phase == "qa":
            self.answer_words += content_words(text)
            # The transcript can land after the end-of-turn check ran: if this made it a real answer
            # and the presenter has stopped, check again so the examiner doesn't wait forever.
            if (self.answer_words >= MIN_ANSWER_WORDS and not self.presenter_speaking
                    and (self.qa_turn is None or self.qa_turn.done())):
                self.qa_turn = self._spawn(self._qa_end_of_turn())

    async def on_realtime_event(self, kind: str, event: dict) -> None:
        if kind == "response.created":
            # Ours, or the server's own follow-up after a web search.
            self._current = self._requested or {"kind": "factcheck_answer" if self.factcheck else "server", "hold": False}
            self._requested = None
        elif kind == "response.output_audio.delta":
            u = self._current
            if u is not None and u.get("finished"):
                return  # cancelled by a barge-in: drop audio still in flight
            if u is not None and not u.get("audio"):
                u["audio"] = True
                if u.get("hold"):
                    self.hold_until = time.monotonic() + HOLD_S
                if self.pending_metric:
                    name, ref = self.pending_metric
                    self.pending_metric = None
                    await self.metric(name, (time.monotonic() - ref) * 1000)
            pcm = base64.b64decode(event["delta"])
            if u is not None:
                u["audio_s"] = u.get("audio_s", 0.0) + len(pcm) / (24_000 * 2)
            await self.output.capture(pcm)
        elif kind == "response.done":
            u, self._current = self._current, None
            if u is not None and u.get("finished"):
                # Cancelled by a barge-in. Close its audio segment anyway: otherwise LiveKit's avatar
                # output folds the next reply into it and drops that reply's playback_finished.
                self.output.flush()
                return
            if u is None:
                return
            if u.get("audio"):
                # When it should have finished playing, with slack for the avatar (watchdog).
                start = max(time.monotonic(), self.playing[-1]["play_end"] if self.playing else 0.0)
                u["play_end"] = start + u.get("audio_s", 0.0)  # when it should finish playing
                u["expected_end"] = u["play_end"] + PLAYBACK_SLACK_S  # when the watchdog gives up waiting
                self.playing.append(u)
                self.output.flush()
            else:
                await self._utterance_finished(u, interrupted=False)
        elif kind == "response.output_audio_transcript.done":
            text = event.get("transcript", "").strip()
            if text:
                self.last_examiner_text = text  # what an answer would be answering
                entry = self.slog.write("examiner", slide=self.slide, text=text)
                await self.ui.publish({"type": "caption", "role": "examiner", "text": text, "t": entry["t"]})
        elif kind == "conversation.item.input_audio_transcription.completed":
            await self.on_transcript(event.get("transcript", ""))
        elif kind == "conversation.item.added":
            item = event.get("item", {})
            if item.get("type") == "function_call_output" and self.factcheck is not None:
                self.factcheck["sources"] = list(dict.fromkeys(URL.findall(item.get("output", ""))))[:3]
        elif kind == "connection.closed" and self.phase in ("presentation", "qa", "debrief"):
            self._spawn(self._reconnect())

    async def _reconnect(self) -> None:
        """Mid-exam drop: reconnect and carry on. The conversation history is lost, so re-seed context."""
        await asyncio.sleep(0.5)
        try:
            if await self.realtime.ensure_connected():
                self._requested, self._current = None, None
                if self.phase != "presentation":
                    await self.realtime.update_instructions(prompts.for_phase(self.config, self.phase, self.interjections))
                await self.realtime.add_note(f"[Context note: the connection was restored. The {self.phase} phase is under "
                                             f"way and the presenter is on slide {self.slide}. Continue the exam.]")
        except Exception as exc:
            log.error("realtime reconnect failed: %s", exc)
            await self.finish()

    # ------------------------------------------------------------------ playback
    async def _playback_finished(self, played: float, interrupted: bool) -> None:
        if interrupted:
            finished = list(self.playing) + ([self._current] if self._current else [])
            self.playing.clear()
            if self._current:
                self._current["finished"] = True  # its response.done may still arrive; ignore it then
            if self.realtime.assistant_item_id:
                await self.realtime.truncate(self.realtime.assistant_item_id, int(played * 1000))
            if self.cancel_at is not None:
                await self.metric("cancel_to_silence", (time.monotonic() - self.cancel_at) * 1000)
                self.cancel_at = None
            for u in finished:
                await self._utterance_finished(u, interrupted=True)
        elif self.playing:
            # The avatar reports once when playback goes idle, so back-to-back utterances (a fact-check's
            # "Let me check that." and its answer) share one report: finish the oldest, plus any others
            # that should have finished playing by now.
            now = time.monotonic()
            await self._utterance_finished(self.playing.popleft(), interrupted=False)
            while self.playing and self.playing[0]["play_end"] <= now + MERGED_REPORT_SLACK_S:
                await self._utterance_finished(self.playing.popleft(), interrupted=False)

    async def _utterance_finished(self, u: dict, interrupted: bool) -> None:
        kind = u["kind"]
        if kind in ("reminder", "escalation") and self.reminder and not interrupted:
            self.reminder["played_at"] = time.monotonic()
            self._spawn(self._watch_ack(self.reminder))
        elif kind == "time_up":
            await self.enter_qa()
            return
        elif kind == "factcheck_answer" and self.factcheck is not None:
            fc, self.factcheck = self.factcheck, None
            self.slog.write("factcheck", status="done", claim=fc["claim"], sources=fc["sources"])
            await self.ui.publish({"type": "factcheck", "status": "done", "claim": fc["claim"], "sources": fc["sources"]})
        elif kind == "verdict":
            await self.finish()
            return
        if kind in ("interjection", "factcheck_answer") and self.phase == "presentation" and not interrupted:
            # The presenter owes an answer; the director judges it when it comes.
            self.awaiting = {"since": time.monotonic(), "asked": self.last_examiner_text, "answer": [],
                             "index": len(self.interjections) - 1}
        elif kind == "ack":
            self.awaiting = None
        await self.idle_state()

    # ------------------------------------------------------------------ presentation
    async def begin(self) -> None:
        # The server closes a Realtime session after 5 idle minutes, so the one opened at launch
        # may be gone by the time the presenter presses Start.
        await self.realtime.ensure_connected()
        self.phase = "presentation"
        self.started = time.monotonic()
        # The web re-sends {type:"start"} every 2 s until its first viva.ui message: answer at once.
        await self.ui_state("listening")
        self.slog.start()
        self.slog.write("phase", phase="presentation")
        self.slog.write("slide", index=self.slide)
        minutes = max(1, round(self.config.get("time_limit_s", 300) / 60))
        await self.say("greeting", f"Greet the presenter in one sentence: good afternoon, they have {minutes} minutes, begin when ready.", max_tokens=50)
        self._spawn(self._timer())
        self._spawn(self._watchdog())

    async def _watchdog(self) -> None:
        while self.phase != "ended":
            await asyncio.sleep(1.0)
            now = time.monotonic()
            if self._requested and now - self._requested["at"] > REQUEST_TIMEOUT_S:
                log.warning("watchdog: response.create for %s never started; dropping it", self._requested["kind"])
                self._requested = None
                self.realtime.abandon_request()
                await self.idle_state()
            if self.realtime.server_tool_pending and now - self.realtime.server_tool_since > SEARCH_TIMEOUT_S:
                log.warning("watchdog: web search follow-up never came; answering from memory")
                self.realtime.abandon_server_tool()
                await self.realtime.flush_pending_commit()
                if self.factcheck is not None:
                    claim = self.factcheck["claim"]
                    await self.say("factcheck_answer", "Your web search did not return. In one or two short sentences, "
                                   f"say from what you know whether this claim is right, starting with the correction: {claim}",
                                   max_tokens=80)
            if self.awaiting and now - self.awaiting["since"] > AWAIT_REPLY_S:
                self.awaiting = None  # they carried on without answering; let the director back in
            if self.deferred and self.phase == "presentation":
                d, meta, at = self.deferred
                if now - at > DEFERRED_FACTCHECK_S:
                    self.deferred = None  # too late to be relevant
                elif not self.engaged and not self._reminder_open() and self._allowed(meta["slide"])[1]:
                    self.deferred = None
                    await self.interject(d, {**meta, "pause_at": now})
            while self.playing and now > self.playing[0]["expected_end"]:
                u = self.playing.popleft()
                log.warning("watchdog: no playback_finished for %s; assuming it finished", u["kind"])
                await self._utterance_finished(u, interrupted=False)

    def _allowed(self, slide: int) -> tuple[bool, bool]:
        """(interjection allowed, fact-check allowed) right now, by cooldowns and caps."""
        now = time.monotonic()
        interject = now - self.last_interjection >= self.cooldown and slide not in self.interjected_slides
        factcheck = self.factcheck_enabled and now - self.last_factcheck >= FACTCHECK_COOLDOWN_S \
            and now - self.last_interjection >= FACTCHECK_COOLDOWN_S
        return interject, factcheck

    async def maybe_direct(self, latest: str, meta: dict) -> None:
        if self.phase != "presentation" or self.elapsed() < NO_INTERJECTION_BEFORE_S:
            return
        if self.director_busy:
            self._director_next = (latest, meta)  # don't drop it: decide on it right after the current call
            return
        interject_ok, factcheck_ok = self._allowed(meta["slide"])
        awaiting = self.awaiting
        if awaiting:
            interject_ok = False  # one exchange at a time: the open interruption gets its answer first
        if self.engaged or self._reminder_open() or not (interject_ok or factcheck_ok or awaiting):
            return
        self.director_busy = True
        try:
            d = await self.director.decide(
                slide=meta["slide"], latest=latest, recent=list(self.recent)[:-1], earlier=self.interjections,
                elapsed_s=self.elapsed(), factcheck_only=not interject_ok,
                awaiting={"asked": awaiting["asked"], "answer": " ".join(awaiting["answer"])} if awaiting else None)
        except Exception as exc:
            log.warning("director failed: %s", exc)
            d = None
        finally:
            self.director_busy = False
            if self._director_next:
                nxt, self._director_next = self._director_next, None
                self._spawn(self.maybe_direct(*nxt))
        if d is None:
            return
        self.slog.write("director", action=d.action, severity=d.severity, reason=d.reason, cue=d.cue, ms=d.ms)
        log.info("director %s/%s (%d ms): %s", d.action, d.severity, d.ms, d.cue or d.reason)
        if d.action == "acknowledge":
            if not awaiting or self.awaiting is not awaiting or self.phase != "presentation":
                return  # stale: that exchange is already over
            self.awaiting = None
            # Record what they answered, so in Q&A she doesn't claim it was never addressed (seen in the sim).
            if 0 <= awaiting.get("index", -1) < len(self.interjections) and awaiting["answer"]:
                answer = " ".join(awaiting["answer"])[:200]
                self.interjections[awaiting["index"]] += f" (they answered: \"{answer}\")"
            cue = d.cue or "Fine. Carry on."
            if self.presenter_speaking or self.engaged:
                self.pending_ack = cue  # deliver it at their next pause
            else:
                await self.say("ack", f"Say, in character: \"{cue}\"", max_tokens=40,
                               metric="answer_end_to_reply", ref=meta["pause_at"])
            return
        interject_ok, factcheck_ok = self._allowed(meta["slide"])  # state may have moved on during the call
        if self.awaiting:
            interject_ok = False
        if d.action == "factcheck" and self.factcheck_enabled and not factcheck_ok and not self.deferred:
            self.deferred = (d, meta, time.monotonic())  # held back only by spacing: fire it when allowed
            return
        if (d.action == "interject" and not interject_ok) or (d.action == "factcheck" and not factcheck_ok):
            return
        if d.action == "interject" and d.severity != "major" and not self.minor_ok:
            return  # this character keeps minor points for the questions
        if d.action == "none" or self.phase != "presentation" or self.engaged or self._reminder_open():
            return
        await self.interject(d, meta)

    async def interject(self, d, meta: dict) -> None:
        slide = meta["slide"]
        self.last_interjection = time.monotonic()
        self.awaiting = self.pending_ack = None  # a new interruption replaces any open exchange
        # Phrased as what the examiner did, so in Q&A a wrong claim isn't read as a fact to re-check.
        self.interjections.append(f"you fact-checked and corrected: {d.claim}" if d.action == "factcheck"
                                  else f"you challenged: {d.cue or d.reason}")
        entry = self.slog.write("interjection", slide=slide, reason=d.reason)
        await self.ui.publish({"type": "interjection", "slide": slide, "reason": d.reason, "t": entry["t"]})
        if d.action == "factcheck":
            self.last_factcheck = self.last_interjection
            self.factcheck = {"claim": d.claim, "sources": []}
            self.slog.write("factcheck", status="searching", claim=d.claim)
            await self.ui.publish({"type": "factcheck", "status": "searching", "claim": d.claim})
            # The slide digest may already hold the correction; the demo wants a visible search.
            # Only a short preamble: the director sometimes writes the correction into the cue, which would
            # give the answer away before the visible search.
            preamble = d.cue if d.cue and len(d.cue.split()) <= 6 else "Let me check that."
            await self.say("factcheck", f"Cut in and say only \"{preamble}\", then call web_search to "
                           f"verify this claim: {d.claim}. You must search before stating any facts; do not answer from memory.",
                           hold=True, max_tokens=None, metric="pause_to_interjection", ref=meta["pause_at"])
        else:
            self.interjected_slides.add(slide)
            cue = d.cue or "What is your evidence for that?"
            await self.say("interjection", f"Interject now, cutting in while the presenter is mid-flow. Say, in character: \"{cue}\"",
                           hold=True, max_tokens=90, metric="pause_to_interjection", ref=meta["pause_at"])

    async def _timer(self) -> None:
        limit = self.config.get("time_limit_s", 300)
        if limit - self.reminder_before_s > NO_INTERJECTION_BEFORE_S:
            await asyncio.sleep(max(0.0, limit - self.reminder_before_s - self.elapsed()))
            if self.phase == "presentation":
                minutes = max(1, round(self.reminder_before_s / 60))
                await self.remind("t_minus_2", f"{minutes} minute{'s' if minutes > 1 else ''} left." )
        await asyncio.sleep(max(0.0, limit - self.elapsed()))
        if self.phase == "presentation":
            await self.remind("time_up", "Time is up. Stop there, please; we move to questions.")

    def _reminder_open(self) -> bool:
        return bool(self.reminder and not self.reminder["acked"])

    async def remind(self, kind: str, words: str) -> None:
        self.awaiting = self.pending_ack = None  # the reminder takes over the floor; no stale acknowledgement after it
        await self.wait_idle(timeout=8)
        self.slog.write("reminder", reminder=kind)
        await self.ui.publish({"type": "reminder", "kind": kind, "acknowledged": None})
        if kind == "t_minus_2":
            self.reminder = {"kind": kind, "played_at": None, "escalated": False, "acked": False}
        for _ in range(3):
            if await self.say("time_up" if kind == "time_up" else "reminder", f"Give a time reminder. Say only: \"{words}\"",
                              hold=True, max_tokens=40):
                return
            await self.wait_idle(timeout=4)

    async def _watch_ack(self, r: dict) -> None:
        """After a reminder has played: silence or an acknowledging phrase counts; talking on does not."""
        while self.reminder is r and not r["acked"] and self.phase == "presentation":
            await asyncio.sleep(0.2)
            now = time.monotonic()
            if self.silent_since is not None and not self.presenter_speaking and now - self.silent_since >= ACK_SILENCE_S:
                await self.acknowledge("silence")
                return
            if self.presenter_speaking and now - r["played_at"] >= IGNORE_AFTER_S:
                if not r["escalated"]:
                    await self.escalate(r)
                return

    async def acknowledge(self, how: str) -> None:
        r = self.reminder
        if not r or r["acked"]:
            return
        r["acked"] = True
        self.slog.write("ack", **{"for": r["kind"], "how": how})
        await self.ui.publish({"type": "reminder", "kind": r["kind"], "acknowledged": True})

    async def escalate(self, r: dict) -> None:
        if self.engaged:
            await self.wait_idle(timeout=4)
        r["escalated"], r["played_at"] = True, None
        self.slog.write("escalation", **{"for": r["kind"]})
        await self.ui.publish({"type": "reminder", "kind": r["kind"], "acknowledged": False})
        minutes = max(1, round(self.reminder_before_s / 60))
        await self.say("escalation", "The presenter ignored your time reminder and kept talking. Cut in firmly and hold "
                       f"the floor. Say: \"Let me stop you there. You have under {minutes} minute{'s' if minutes > 1 else ''}. "
                       "Move to your conclusion.\"", hold=True, max_tokens=60)

    # ------------------------------------------------------------------ Q&A
    def _pick_questions(self) -> list[str]:
        """Up to 4 questions: the main one of each weak slide not challenged during the talk, then follow-ups
        (second questions, including on challenged slides). The GradeBook live run had only one question left."""
        weak = [s for s in self.config.get("slides", []) if s.get("weak_points") and s.get("questions")]
        main = [s["questions"][0] for s in weak if s["index"] not in self.interjected_slides]
        follow_ups = [q for s in weak for q in s["questions"][1:2]]
        return list(dict.fromkeys(main + follow_ups))[:4]

    def next_question(self) -> str | None:
        return self.questions.pop(0) if self.questions else None

    async def enter_qa(self) -> None:
        if self.phase != "presentation":
            return
        self.phase = "qa"
        self.reminder = None
        self.questions = self._pick_questions()
        self.slog.write("phase", phase="qa")
        await self.ui_state("qa")
        # Web search off: in the first live run she re-ran the presentation's fact-check three times in Q&A.
        await self.realtime.update_instructions(prompts.for_phase(self.config, "qa", self.interjections), tools=[])
        await self.wait_idle(timeout=8)
        q = self.next_question() or "Ask your sharpest question about the weakest slide."
        await self.say("qa", f"Thank the presenter in at most three words, then ask your first question: {q}", max_tokens=90)
        self._spawn(self._qa_timer())

    async def _qa_timer(self) -> None:
        await asyncio.sleep(self.config.get("qa_s", 120))
        await self.enter_debrief()

    async def _qa_end_of_turn(self) -> None:
        await asyncio.sleep(max(0.0, self.patience - VAD_SILENCE_S))
        if self.engaged:  # e.g. the cancelled reply after a barge-in is still winding down
            await self.wait_idle(timeout=3)
        # Reply only to a real answer that began after the examiner last asked something: "um", "oh" or
        # "yeah" alone is not a turn (live run: each filler got a reply and the exchange turned rapid-fire).
        if (self.phase == "qa" and not self.presenter_speaking and not self.engaged
                and self.last_speech_start > self.last_examiner_request and self.answer_words >= MIN_ANSWER_WORDS):
            q = self.next_question()
            if q:
                await self.say("qa", f"React to the presenter's answer in at most one sentence, then ask: {q}",
                               max_tokens=110, metric="answer_end_to_reply")
            else:
                # Out of questions: straight to the verdict, reacting to this last answer first. (A separate
                # "that was my last question" line got cut off live and repeated, then she re-asked a question.)
                await self.enter_debrief(react_first=True)

    async def _maybe_barge_in(self) -> None:
        await asyncio.sleep(max(0.0, self.hold_until - time.monotonic()) + BARGE_IN_S)
        if self.phase == "qa" and self.presenter_speaking and self.examiner_audible:
            self.cancel_at = time.monotonic()
            await self.realtime.cancel()
            self.output.clear()

    # ------------------------------------------------------------------ debrief
    async def enter_debrief(self, react_first: bool = False) -> None:
        if self.phase not in ("presentation", "qa"):
            return
        self.phase = "debrief"
        if self.qa_turn and self.qa_turn is not asyncio.current_task():
            self.qa_turn.cancel()
        self.slog.write("phase", phase="debrief")
        await self.ui_state("debrief")
        await self.realtime.update_instructions(prompts.for_phase(self.config, "debrief"))
        await self.wait_idle(timeout=10)
        react = ("First react to the presenter's last answer in one short sentence and say that concludes the "
                 "questions. Then " if react_first else "")
        await self.say("verdict", f"{react}Give your verdict in at most three sentences: one genuine strength, the "
                       "biggest weakness, and one concrete fix. Start the verdict with the word Verdict.",
                       max_tokens=200, metric="answer_end_to_reply" if react_first else None)

    async def abort(self) -> None:
        """The presenter left or restarted: stop everything at once (the log is kept locally)."""
        if self.phase == "ended":
            return
        self.phase = "ended"
        for task in list(self._tasks):
            task.cancel()
        await self.realtime.cancel()
        self.output.clear()
        self.ended.set()

    async def finish(self) -> None:
        if self.phase == "ended":
            return
        self.completed = True
        self.phase = "ended"
        self.slog.write("phase", phase="end")
        await self.ui_state("ended")
        await self.ui.publish({"type": "ended", "session_id": self.config.get("session_id")})
        self.ended.set()

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await self.vad.aclose()
