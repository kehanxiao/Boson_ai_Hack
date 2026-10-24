"""The exam controller: phases, timer, reminders, and turn-taking around the examiner's brain.

Inputs:  presenter audio frames, viva.ctl messages, Realtime events, brain decisions, playback-finished callbacks.
Outputs: Realtime requests, viva.ui messages, session log lines.
Design: PLAN.md "Core design decisions"; protocol facts: agent/CLAUDE.md.

Two Higgs Realtime sessions hear the presenter:
- the brain (brain.py) decides what the examiner does: stay silent, say a line, or check a claim on the web;
- the voice speaks the brain's lines word for word through the avatar, and runs the web search.
The code keeps a few rules around the brain: when it is asked (not right after she has spoken,
unless the presenter is replying to her), time reminders and their acknowledgement, holding the
floor, and stopping when the presenter talks over her.

Every examiner utterance is one voice response. Utterances we ask for are tracked from request
to "finished playing"; the server's own follow-up after a web search is tracked too.
"""

import asyncio
import base64
import logging
import random
import re
import time
from collections import deque

import instructions as prompts
from brain import LOOKUP, Brain, Decision
from vad import PauseDetector

log = logging.getLogger("viva.exam")

HOLD_S = 1.5  # the examiner keeps the floor this long after starting to speak
VAD_SILENCE_S = 0.6  # pause length that triggers a commit
# After she has spoken, this long before she cuts in on something new. A pause inside the gap is judged when the
# gap ends (live run, Sat 03:06: "we print the top twenty" fell 7.8 s after her "Go on." and was never judged at 8 s).
GAP_S = {"high": 3, "medium": 4, "low": 8}
# When the presenter is replying to her, a 0.6 s pause is often mid-thought ("Because." ... ): wait this much longer.
REPLY_PATIENCE_S = 0.9
# ...but only at the start of a reply, where thinking pauses are. A presenter who carries on fluently (gaps under
# 1.5 s) cancelled every delayed ask, so the brain heard nothing for the whole exchange (sim, Sat 05:10).
REPLY_START_S = 3.0
PRESSED_QUIET_S = 8
# The brain learns a new slide's content and weak points only once the presenter has spoken this long on it.
# Told them at the switch, she challenged them 0.6 s and 4 s later, before the presenter had made the claim
# ("You say bug-free..." live run, Sat 04:28). Delaying the asking instead (sim, Sat 05:12) lost claims made just
# before a click: the pause landed on the new slide.
SLIDE_SETTLE_S = 5.0
# While she is heard, the presenter's speech is held back from the brain: a short overlap (trailing off, a reflex
# "yeah") is dropped when she finishes, and only a real talk-over (barge-in) is passed on. Taken as their answer,
# overlap made her react to words said while she was talking (live run, Sat 04:30).
OVERLAP_MAX_BYTES = 20 * 24_000 * 2  # at most 20 s held  # after she has pressed a point as far as her character does, she lets the presenter move on
EXCHANGE_S = 20  # after she cuts in, the presenter's next words are a reply: the brain hears every pause
FACTCHECK_SPACING_S = 10  # between two web searches
MAX_CHUNK_S = 10  # force a commit during long unbroken speech so the brain isn't deaf
# Watchdog: nothing may leave the examiner stuck "busy" (that would silence reminders and phases).
REQUEST_TIMEOUT_S = 8  # response.create that never produced response.created
SEARCH_TIMEOUT_S = 12  # server web_search whose follow-up answer never came
PLAYBACK_SLACK_S = 4  # an utterance's playback_finished may be lost; give up this long after it should end
MERGED_REPORT_SLACK_S = 1.0  # one avatar report also finishes queued utterances due to end within this margin
QA_PATIENCE_S = {"high": 1.6, "medium": 2.0, "low": 2.5}  # silence before a Q&A answer is judged: thinking time
QA_SILENCE_S = 8  # nothing said this long in Q&A: the brain decides (rephrase, move on)
QA_NUDGES = 3  # at most this many silence prompts per question
QA_GRACE_S = 25  # past the Q&A time, the exchange under way may finish within this
MIN_QA_QUESTIONS = 2  # live run (Sat 03:08): the brain ENDed question time before asking anything
ACK_SILENCE_S = 1.0  # going quiet this long after a reminder counts as acknowledging it
IGNORE_AFTER_S = 3.5  # still talking this long after a reminder means it was ignored
# Q&A: presenter speech this long past the hold window stops her. A "Yeah." keeps the VAD on "speaking" for its
# 0.6 s silence tail too: at 0.8 s a one-word backchannel cut her question (live run, Sat 03:46).
BARGE_IN_S = 1.5
# Presentation: she cut in, so the presenter finishing their sentence is not talking over her. Live run (Sat 03:06):
# at 0.8 s every interjection was cut after a word or two ("So, yeah.", "Because.", "Oh.").
BARGE_IN_TALK_S = 2.5
BARGEABLE = {"interjection", "qa", "greeting"}  # reminders, fact-checks and the verdict hold the floor
GREETING_DELAY_S = 1.2  # Start was just clicked: let the presenter look up first
# On one API key, a voice response asked for within ~1 s of a brain response starts ~1.6-1.8 s later; after 0.8 s
# it starts in ~0.36 s, so waiting is faster overall. With the brain on its own key (BOSON_BRAIN_API_KEY) there is
# no delay: ~0.35 s even right after the brain (probes/two_session_latency.py), so no wait.
BRAIN_SETTLE_S = 0.8

STT_PLACEHOLDER = "the transcription is not available"  # seen live from higgs-stt-3.1 when it fails
ACK_WORDS = re.compile(r"\b(okay|ok|noted|yes|yeah|yep|got it|sure|understood|right|i know|will do|thanks|thank you|"
                       r"baik|oke|siap)\b", re.I)
ACK_CJK = ("好的", "明白", "知道")
URL = re.compile(r"https?://[^\s)\]>\"']+")
INDONESIAN = re.compile(r"\b(saya|kami|kita|tidak|belum|sudah|bisa|itu|ini|yang|dengan|untuk|karena|tapi|jujur|apakah|waktu)\b", re.I)
PREAMBLES = ("Hm, let me check that.", "Hang on, let me look that up.", "Wait, is that right? Let me check.")


def follow_ups(character: dict) -> int:
    """How many replies she gets within one exchange (acknowledge, push back, insist): 2 (strictness 5), else 1.
    Live run (Sat 03:06): with 2 for The Supervisor, a dodged question was raised three times, which felt nagging."""
    strictness = int(character.get("strictness", 3))
    return 2 if strictness >= 5 else 1


STOP_WORDS = {"the", "a", "an", "and", "or", "is", "it", "its", "it's", "you", "your", "you're", "what", "if", "of",
              "to", "in", "on", "that", "this", "there", "there's", "do", "does", "how", "so", "but", "with", "as"}


def content_set(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", text.lower()) if w not in STOP_WORDS}


def similar(a: set[str], b: set[str]) -> bool:
    """The same point reworded: "Your code unpacks each row as exactly two fields..." and "You unpack each CSV
    row as exactly two fields..." (live run, Sat 03:44) share most of their content words."""
    return bool(a and b) and len(a & b) / len(a | b) >= 0.5


def heard_part(text: str, fraction: float) -> str:
    words = text.split()
    return " ".join(words[:max(1, round(len(words) * min(1.0, max(0.0, fraction))))])


def guess_lang(text: str) -> str:
    if any("一" <= ch <= "鿿" for ch in text):
        return "zh"
    if len(INDONESIAN.findall(text)) >= 2:
        return "id"
    return "en"


class ExamController:
    def __init__(self, config, realtime, output, ui, slog, brain: Brain | None, *, factcheck=True,
                 reminder_before_s=120):
        self.config = config
        self.realtime = realtime  # the voice
        self.brain = brain
        self.output = output
        self.ui = ui
        self.slog = slog
        self.factcheck_enabled = factcheck
        # T-2 for a long talk; for a short one a third of it (3-minute demo: "1 minute left" at 2:00).
        self.reminder_before_s = min(reminder_before_s, max(30, config.get("time_limit_s", 300) // 3))
        self.qa_enabled = prompts.has_qa(config)  # qa_s 0: no question time and no verdict

        # The character drives interruption behaviour (PLAN.md "Character drives the examiner's behaviour").
        character = config["character"]
        self.gap = GAP_S.get(character.get("interrupt_rate", "medium"), 8)
        self.follow_ups = follow_ups(character)
        self.qa_patience = QA_PATIENCE_S.get(character.get("interrupt_rate", "medium"), 2.0)
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
        self.slide_changed_at = 0.0
        self.slide_speech = 0.0  # presenter speech on the current slide, finished stretches only
        self.revealed: set[int] = set()  # slides whose content and weak points the brain has been given
        self.reply_speech = 0.0  # presenter speech since her last utterance finished
        self.chunk_started_at = 0.0  # when the speech in the current chunk began
        self.last_commit = 0.0
        self.chunk_slide = 1  # slide showing when the current chunk of speech began
        self.commits: deque[dict] = deque()  # per commit, in order: the chunk's slide and pause time
        self.recent: deque[str] = deque(maxlen=12)  # transcripts, to re-seed a brain that reconnected

        # Examiner utterances: requested -> generating -> playing -> finished
        self._requested: dict | None = None
        self._current: dict | None = None
        self.playing: deque[dict] = deque()
        self.hold_until = 0.0
        self.pending_metric: tuple[str, float] | None = None
        self.cancel_at: float | None = None

        # Turn-taking around the brain
        self.last_spoke_end = 0.0  # when her last utterance ended
        self.exchange: dict | None = None  # {"until", "depth"}: the presenter is replying to her
        self._reask: tuple | None = None  # a pause that came while the brain was deciding
        self.overlap = bytearray()  # presenter audio while she is heard: dropped, or passed on if they talk over her
        self.overlap_released = False
        self._gap_pending: dict | None = None  # a pause that came during the gap: judged when the gap ends
        self.said: deque[set[str]] = deque(maxlen=12)  # her brain lines' content words: no point a third time
        self._qa_instructions: str | None = None
        self.raised: list[str] = []  # her points during the talk, so Q&A doesn't ask them again

        # Reminders, Q&A, fact-check
        self.reminder: dict | None = None
        self.quiet_until = 0.0  # after a reminder: the presenter's reaction is judged by the reminder logic
        self.factcheck: dict | None = None
        self.last_factcheck = -1e9
        self.answer_since: float | None = None  # Q&A: her question has played; the answer counts from here
        self.answered = False  # Q&A: the presenter has spoken since her question
        self.qa_quiet_since = 0.0
        self.qa_nudges = 0
        self.qa_over = False
        self.qa_asked = 0  # questions she has asked in Q&A
        self.qa_turn: asyncio.Task | None = None
        self.fallback_questions = prompts.qa_questions(config)  # only if the brain is unavailable
        self._tasks: list[asyncio.Task] = []

        output.on_finished(lambda played, interrupted: self._spawn(self._playback_finished(played, interrupted)))
        output.on_started(lambda estimated: self._spawn(self._playback_started(estimated)))

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
        return self._audible() is not None

    @property
    def brain_ok(self) -> bool:
        return bool(self.brain and self.brain.connected)

    def _utterances(self) -> list[dict]:
        return list(self.playing) + ([self._current] if self._current else [])

    def _audible(self) -> dict | None:
        """What the room hears right now: an utterance that has started playing (the output's on_started), not
        one that has only been generated. With the avatar that is ~1.4 s later; counting from generation, the
        presenter's words before they could hear her read as talking over her (live run, Sat 04:30)."""
        return next((u for u in self._utterances() if u.get("audible_at") and not u.get("finished")), None)

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

    async def note(self, text: str) -> None:
        if self.brain_ok:
            await self.brain.note(text)

    async def say(self, kind: str, cue: str, *, hold=False, max_tokens: int | None = 120, metric: str | None = None,
                  ref: float | None = None, line: str | None = None, reply=False, retried=False) -> bool:
        """One voice response. line: the brain's words (it knows what she said); reply: said within an exchange."""
        if self.engaged:
            return False
        phase = self.phase if self.phase in prompts.PHASES else "presentation"
        self._gap_pending = None
        self._requested = {"kind": kind, "hold": hold, "at": time.monotonic(), "line": line, "reply": reply,
                           "cue": cue, "max_tokens": max_tokens, "retried": retried,
                           "metric_ref": (metric, ref or self.pause_at or time.monotonic()) if metric else None}
        shared_key = self.brain is not None and self.brain.rt.headers == self.realtime.headers
        settle = (self.brain.last_done + BRAIN_SETTLE_S - time.monotonic()) if shared_key else 0.0
        if settle > 0:
            await asyncio.sleep(settle)  # the voice is reserved meanwhile (_requested), so nothing else cuts in
            if self._requested is None or self._requested.get("cue") != cue:
                return False  # reset meanwhile (abort, watchdog)
        if not await self.realtime.create_response(prompts.with_cue(self.config, phase, cue), max_tokens):
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
        pcm = bytes(frame.data)
        await self.realtime.append(pcm)  # the voice session still transcribes everything (captions, the log)
        if self.brain_ok:
            if self._audible() is not None and not self.overlap_released:
                if len(self.overlap) < OVERLAP_MAX_BYTES:
                    self.overlap.extend(pcm)
            else:
                await self.brain.append(pcm)
        self.vad.push(frame)
        if self.presenter_speaking and time.monotonic() - self.last_commit > MAX_CHUNK_S:
            slide = self.chunk_slide
            await self._commit()  # long unbroken speech: chunk it anyway
            if self.phase == "presentation":
                await self._ask_brain({"phase": "presentation", "pause_at": time.monotonic(), "slide": slide})

    async def _commit(self) -> None:
        self.last_commit = time.monotonic()
        meta = {"slide": self.chunk_slide, "pause_at": self.last_commit, "started": self.chunk_started_at}
        outcome = await self.realtime.commit()
        if outcome in ("sent", "queued"):
            self.commits.append(meta)
        elif outcome == "merged" and self.commits:
            self.commits[-1]["pause_at"] = meta["pause_at"]  # one transcript will cover both
        if self.brain_ok:
            await self.brain.commit()
        self.chunk_slide = self.slide

    async def on_speech_start(self) -> None:
        self.presenter_speaking = True
        self.silent_since = None
        self.last_speech_start = time.monotonic()
        if time.monotonic() - self.last_commit > 0.3:
            self.chunk_slide = self.slide
            self.chunk_started_at = self.last_speech_start
        if self.qa_turn:
            self.qa_turn.cancel()  # they are still answering
            self.qa_turn = None
        if self.answer_since is not None:
            self.answered = True
        u = self._audible()
        if u is not None:
            if time.monotonic() < self.hold_until:
                await self.ui_state("holding_floor")
            if u["kind"] in BARGEABLE:
                self._spawn(self._maybe_barge_in(self.last_speech_start))

    async def on_pause(self) -> None:
        self.slide_speech += max(0.0, time.monotonic() - VAD_SILENCE_S - max(self.last_speech_start, self.slide_changed_at))
        self.reply_speech += max(0.0, time.monotonic() - VAD_SILENCE_S - max(self.last_speech_start, self.last_spoke_end))
        self.presenter_speaking = False
        self.pause_at = time.monotonic()
        self.silent_since = self.pause_at - VAD_SILENCE_S
        self.qa_quiet_since = self.pause_at
        slide = self.chunk_slide
        await self._commit()  # queued by the client if a response is being generated
        if self.phase == "presentation":
            await self._maybe_reveal()  # before the brain judges this pause
            ctx = {"phase": "presentation", "pause_at": self.pause_at, "slide": slide}
            if self._in_exchange() and self.reply_speech < REPLY_START_S:
                if self.qa_turn:
                    self.qa_turn.cancel()
                self.qa_turn = self._spawn(self._ask_after(REPLY_PATIENCE_S, ctx))  # cancelled if they go on
            else:
                await self._ask_brain(ctx)
        elif self.phase == "qa":
            if self.qa_turn:
                self.qa_turn.cancel()
            self.qa_turn = self._spawn(self._qa_end_of_turn())

    async def on_slide(self, index: int) -> None:
        if index == self.slide:
            return
        self.slide = index
        self.slide_changed_at, self.slide_speech = time.monotonic(), 0.0
        self.slog.write("slide", index=index)
        summary = next((s.get("summary", "") for s in self.config.get("slides", []) if s["index"] == index), "")
        await self.realtime.add_note(f"[Context note: the presenter moved to slide {index}. {summary}]")
        await self.note(self._slide_note(index) if index in self.revealed else f"[Slide {index} is showing now.]")
        if self.reminder and not self.reminder["acked"] and index == self.last_slide:
            await self.acknowledge("slide_jump")

    async def on_transcript(self, text: str) -> None:
        """The voice session's transcript of a chunk: captions, the log, and reminder acknowledgement."""
        meta = self.commits.popleft() if self.commits else {"slide": self.slide, "pause_at": time.monotonic()}
        text = text.strip()
        if not text or text.lower().startswith(STT_PLACEHOLDER):
            return  # nothing said, or the STT service's placeholder when it fails
        lang = guess_lang(text)
        entry = self.slog.write("chunk", slide=meta["slide"], lang=lang, text=text)
        await self.ui.publish({"type": "caption", "role": "presenter", "text": text, "lang": lang, "t": entry["t"]})
        self.recent.append(f"slide {meta['slide']}: {text}")
        r = self.reminder
        if (r and not r["acked"] and meta.get("started", 0.0) >= r["issued"] - 0.5
                and (ACK_WORDS.search(text) or any(w in text for w in ACK_CJK))):  # "Yeah, I know." over her reminder
            await self.acknowledge("phrase")

    async def on_realtime_event(self, kind: str, event: dict) -> None:
        """Events from the voice session."""
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
                if u.get("at"):
                    log.info("voice: first audio %.0f ms after the request (%s)", (time.monotonic() - u["at"]) * 1000, u["kind"])
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
            if event.get("response", {}).get("status") == "failed" and not u.get("audio"):
                # Seen in the sim: "an upstream service call did not complete". Ask once more, else move on.
                self.pending_metric = None
                if u.get("cue") and not u.get("retried"):
                    log.warning("voice response for %s failed; retrying once", u["kind"])
                    self._spawn(self._retry(u))
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
                if self._current is not None:
                    self._current["text"] = text
                    if not self._current.get("line") and self._current.get("audible_at") and self.brain_ok:
                        await self.note(self._her_words(self._current))  # heard before its transcript was done
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
        """Mid-exam drop of the voice: reconnect and carry on. Its history is lost, but the brain has it."""
        await asyncio.sleep(0.5)
        try:
            if await self.realtime.ensure_connected():
                self._requested, self._current = None, None
                if self.phase != "presentation":
                    await self.realtime.update_instructions(prompts.for_phase(self.config, self.phase),
                                                            tools=[] if self.phase == "qa" else None)
                await self.realtime.add_note(f"[Context note: the connection was restored. The {self.phase} phase is under "
                                             f"way and the presenter is on slide {self.slide}. Continue the exam.]")
        except Exception as exc:
            log.error("realtime reconnect failed: %s", exc)
            await self.finish()

    async def on_brain_closed(self) -> None:
        if self.phase in ("presentation", "qa", "debrief"):
            self._spawn(self._reconnect_brain())

    async def _reconnect_brain(self) -> None:
        """Mid-exam drop of the brain: reconnect and re-seed it with what was said so far."""
        await asyncio.sleep(0.5)
        try:
            if self.brain and await self.brain.ensure_connected():
                if self.phase != "presentation":
                    await self.brain.update_instructions(self._qa_prompt())
                await self.brain.note(f"[The connection was restored. The {self.phase} is under way; slide {self.slide} "
                                      f"is showing. Recently the presenter said: {' / '.join(self.recent)}]")
        except Exception as exc:
            log.error("brain reconnect failed: %s", exc)

    # ------------------------------------------------------------------ the brain
    def _slide_note(self, index: int) -> str:
        slide = next((s for s in self.config.get("slides", []) if s["index"] == index), None)
        if not slide:
            return f"[Slide {index} is showing now.]"
        # What the slide shows and what is wrong with it, labelled apart (prompts.slide_line). Each problem counts
        # only once the presenter says it (live run, Sat 04:28: told plainly, she challenged claims not yet made).
        return (f"[Slide {index} is showing now. {prompts.slide_line(slide)}"
                + (" Each problem counts only once the presenter actually says it." if slide.get("weak_points") else "")
                + "]")

    def _qa_prompt(self) -> str:
        if self._qa_instructions is None:
            self._qa_instructions = prompts.brain(self.config, "qa")
        return self._qa_instructions

    def _repeats(self, line: str) -> bool:
        """She has made this point twice already. Short answers ("Yes, go on.") may repeat: blocking one left the
        presenter in silence each time they asked to continue (live run, Sat 04:27)."""
        key = content_set(line)
        return len(line.split()) > 5 and sum(similar(key, earlier) for earlier in self.said) >= 2

    def _in_exchange(self) -> bool:
        x = self.exchange
        return bool(x and time.monotonic() < x["until"] and x["depth"] < self.follow_ups)

    def _slide_speech(self) -> float:
        """How long the presenter has talked on the current slide, including a stretch still under way."""
        ongoing = time.monotonic() - max(self.last_speech_start, self.slide_changed_at) if self.presenter_speaking else 0.0
        return self.slide_speech + max(0.0, ongoing)

    async def _maybe_reveal(self) -> None:
        """Give the brain the current slide's content once the presenter has talked about it for a while."""
        if self.slide not in self.revealed and self._slide_speech() >= SLIDE_SETTLE_S:
            self.revealed.add(self.slide)
            await self.note(self._slide_note(self.slide))

    def _may_cut_in(self) -> bool:
        """Presentation: ask the brain at this pause? Not while she speaks, and not right after she has spoken,
        unless the presenter is replying to her."""
        now = time.monotonic()
        if self.phase != "presentation" or self.engaged or not self.brain_ok or now < self.quiet_until:
            return False
        return self._in_exchange() or now - self.last_spoke_end >= self.gap

    async def _ask_after(self, delay: float, ctx: dict) -> None:
        await asyncio.sleep(delay)
        if not self.presenter_speaking:
            await self._ask_brain(ctx)

    async def _ask_brain(self, ctx: dict, instructions: str | None = None, max_tokens: int | None = None) -> None:
        if ctx["phase"] == "presentation" and not self._may_cut_in():
            if self.phase == "presentation" and not self.engaged and self.brain_ok:
                # Only the gap or a quiet window is in the way: judge it when that ends. Dropped before, so "May I
                # continue now?" right after a time reminder went unanswered (live run, Sat 04:26).
                self._gap_pending = ctx
            return
        if not self.brain_ok:
            return
        self._gap_pending = None
        if self.brain.thinking:
            self._reask = (ctx, instructions, max_tokens)  # decide again on the newest audio, if that was silence
            return
        ctx = {**ctx, "reply": self._in_exchange()}
        await self.brain.ask(ctx, instructions, max_tokens)

    async def _ask_when_free(self, ctx: dict, instructions: str | None = None, max_tokens: int | None = None) -> bool:
        """For asks that must not be lost (first question, verdict): wait for a decision in flight."""
        for _ in range(40):
            if not self.brain_ok:
                return False
            if not self.brain.thinking:
                return await self.brain.ask(ctx, instructions, max_tokens)
            await asyncio.sleep(0.1)
        return False

    async def on_brain_decision(self, d: Decision) -> None:
        self._spawn(self._decide(d))  # never block the brain's event reader

    async def _decide(self, d: Decision) -> None:
        self.slog.write("director", action=d.action.lower(), cue=d.text, ms=d.ms, reason="higgs brain")
        since = (time.monotonic() - d.ctx["pause_at"]) * 1000 if d.ctx.get("pause_at") else 0
        log.info("brain %s (%d ms, %.0f ms after the pause): %s", d.action, d.ms, since, d.text or d.raw[:80])
        if d.ctx.get("phase") != self.phase:
            return  # asked in an earlier phase
        reask, self._reask = self._reask, None
        if d.action == "INVALID" and not d.raw and not d.ctx.get("retry"):
            # Seen in sims: the brain's response failed upstream (no text). Ask once more.
            await self._ask_brain({**d.ctx, "retry": True}, *(reask[1:] if reask else ()))
            return
        if d.action == "INVALID" and len(d.text.split()) >= 2 and not d.text.startswith("["):
            # A spoken line without its tag: seen as "Let me finish, please. You haven't answered..." after a
            # talk-over note (sims, Sat 04:55). parse() stays strict so the probes still count format slips.
            action = "CHECK" if LOOKUP.search(d.text) else "SAY"  # as parse() does for a tagged SAY
            log.info("brain: untagged line taken as %s", action)
            d = Decision(action, d.text.strip('"'), d.ms, d.ctx, d.raw)
        if d.action in ("SILENT", "INVALID") or not d.text:
            if reask:
                await self._ask_brain(*reask)  # audio that arrived during that decision
            elif self.phase == "qa" and d.ctx.get("first") and not self.engaged:
                await self._fallback_question(first=True)  # question time must start with a question
            elif self.phase == "qa" and d.ctx.get("forced") and not self.engaged:
                # Asked for a different question and gave none: 35 s of dead air in a live run (Sat 06:56).
                await self._fallback_question()
            return
        if self.engaged:
            await self.brain.forget(d)  # never heard: not part of what she said
            return
        if d.action in ("SAY", "END") and self._repeats(d.text):
            await self._blocked_repeat(d)
            return
        if self.phase == "presentation":
            if d.action == "CHECK":
                await self.check(d.text, d.ctx, d)
            else:
                await self.interject(d.text, d.ctx, d)
        elif self.phase == "qa":
            if d.action == "END" and self.qa_asked < MIN_QA_QUESTIONS and not self.qa_over:
                if d.ctx.get("forced"):
                    await self._fallback_question(first=self.qa_asked == 0)
                else:
                    await self._ask_brain({**d.ctx, "forced": True}, self._qa_prompt()
                                          + "\n\nDon't end yet: ask your next question now. Answer SAY.")
            elif d.action == "END":
                await self.enter_debrief(react=d.text)
            elif d.action == "SAY":
                self.said.append(content_set(d.text))
                self.qa_asked += 1
                self.answer_since = None  # the next answer counts from when this has played
                await self.say("qa", prompts.say_exactly(d.text), max_tokens=100, metric="answer_end_to_reply",
                               ref=d.ctx.get("pause_at"), line=d.text)

    async def _blocked_repeat(self, d: Decision) -> None:
        """She has made this point twice. Once more is fine (they asked her to repeat, live run Sat 03:44); a third
        time is nagging. The line is forgotten, as never said, and the brain is asked once more for something else:
        blocked lines left in place made it propose the same line ~15 times while the presenter's "which slide?"
        went unanswered (live run, Sat 06:17)."""
        await self.brain.forget(d)
        if d.ctx.get("forced"):
            if self.phase == "qa":
                await self._fallback_question()
            return  # asked again already: stay silent
        log.info("brain: blocked repeat, asking again")
        task = ("You have already made that point twice, so it was not said. If the presenter asked you something, "
                "answer it now. Otherwise say something new, or SILENT.") if self.phase == "presentation" else \
            "You have already asked that twice, so it was not said. Ask a different question now. Answer SAY or END."
        base = self._qa_prompt() if self.phase == "qa" else prompts.brain(self.config, "presentation")
        if self.brain_ok and not self.brain.thinking:
            await self.brain.ask({**d.ctx, "forced": True}, base + "\n\n" + task)

    async def interject(self, line: str, ctx: dict, decision: Decision | None = None) -> None:
        self.said.append(content_set(line))
        self.raised.append(line)
        slide = ctx.get("slide", self.slide)
        entry = self.slog.write("interjection", slide=slide, reason=line)
        await self.ui.publish({"type": "interjection", "slide": slide, "reason": line, "t": entry["t"]})
        if not await self.say("interjection", prompts.say_exactly(line), hold=True, max_tokens=100,
                              metric="pause_to_interjection", ref=ctx.get("pause_at"), line=line, reply=ctx.get("reply")):
            if decision:
                await self.brain.forget(decision)  # never heard

    async def check(self, claim: str, ctx: dict, decision: Decision | None = None) -> None:
        now = time.monotonic()
        if not self.factcheck_enabled or now - self.last_factcheck < FACTCHECK_SPACING_S:
            if decision:
                await self.brain.forget(decision)  # nothing was said
            return
        self.last_factcheck = now
        self.factcheck = {"claim": claim, "sources": []}
        slide = ctx.get("slide", self.slide)
        entry = self.slog.write("interjection", slide=slide, reason=f"fact-check: {claim}")
        await self.ui.publish({"type": "interjection", "slide": slide, "reason": f"fact-check: {claim}", "t": entry["t"]})
        self.slog.write("factcheck", status="searching", claim=claim)
        await self.ui.publish({"type": "factcheck", "status": "searching", "claim": claim})
        preamble = random.choice(PREAMBLES)
        await self.say("factcheck", f"Cut in and say only \"{preamble}\", then call web_search to verify this claim: "
                       f"{claim}. You must search before stating any facts; do not answer from memory.",
                       hold=True, max_tokens=None, metric="pause_to_interjection", ref=ctx.get("pause_at"))

    async def _retry(self, u: dict) -> None:
        await asyncio.sleep(0.3)
        if self.phase == "ended" or not await self.say(u["kind"], u["cue"], hold=u.get("hold", False),
                                                       max_tokens=u.get("max_tokens"), line=u.get("line"),
                                                       reply=u.get("reply", False), retried=True):
            await self._utterance_finished(u, interrupted=False)

    def _her_words(self, u: dict) -> str:
        u["told"] = True
        how = "She looked it up and told them" if u["kind"] == "factcheck_answer" else "She said"
        return f'[{how}: "{u["text"]}"]'

    # ------------------------------------------------------------------ playback
    async def _playback_started(self, estimated: bool) -> None:
        """The room starts hearing her next utterance: her floor-hold, being talked over, and the brain's sense
        of order (what the presenter said before vs while she speaks) all run from here."""
        u = next((x for x in self._utterances() if x.get("audio") and not x.get("audible_at") and not x.get("finished")),
                 None)
        if u is None:
            return
        now = time.monotonic()
        u["audible_at"] = now
        log.info("heard: %s starts %.0f ms after the request%s", u["kind"], (now - u.get("at", now)) * 1000,
                 " (estimated)" if estimated else "")
        if u.get("metric_ref"):
            name, ref = u["metric_ref"]
            await self.metric(f"{name}_heard", (now - ref) * 1000)
        if u.get("hold"):
            self.hold_until = now + HOLD_S
        if self.brain_ok:
            # Words the brain didn't write (greeting, reminders, a search result) go with it, in the past tense:
            # told she was "about to say" them, the brain repeated them as its own line (sim, Sat 05:25).
            words = "" if u.get("line") or not u.get("text") else " " + self._her_words(u)
            await self.brain.mark("[She starts speaking now. What the presenter said before this, they said "
                                  "before they could hear her.]" + words)
        self.overlap.clear()
        self.overlap_released = False
        if self.presenter_speaking and u["kind"] in BARGEABLE:
            # Already talking when she became audible: if they keep going, they are talking over her.
            await self.ui_state("holding_floor")
            self._spawn(self._maybe_barge_in(self.last_speech_start))

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
            for i, u in enumerate(finished):
                await self._utterance_finished(u, interrupted=True, played=played if i == 0 else 0.0)
        elif self.playing:
            # The avatar reports once when playback goes idle, so back-to-back utterances (a fact-check's
            # "Let me check that." and its answer) share one report: finish the oldest, plus any others
            # that should have finished playing by now.
            now = time.monotonic()
            await self._utterance_finished(self.playing.popleft(), interrupted=False)
            while self.playing and self.playing[0]["play_end"] <= now + MERGED_REPORT_SLACK_S:
                await self._utterance_finished(self.playing.popleft(), interrupted=False)

    async def _utterance_finished(self, u: dict, interrupted: bool, played: float = 0.0) -> None:
        kind, now = u["kind"], time.monotonic()
        self.last_spoke_end = now
        self.reply_speech = 0.0
        text = u.get("text") or u.get("line") or ""
        talked_over = interrupted and kind in BARGEABLE and text and played > 0
        if talked_over:
            heard = heard_part(text, played / max(u.get("audio_s", 0.0), 0.1))
            self.slog.write("director", action="talked_over", cue=heard, ms=0, reason="presenter talked over her")
            if self.brain_ok:
                await self.brain.mark(f'[The presenter talked over her, so she stopped. Of "{text}" they heard only: '
                                      f'"{heard}"]')
            # A cut-off reply still counts toward her follow-ups: otherwise being talked over again and
            # again made her re-ask the same question again and again (live run, Sat 03:06).
            depth = (self.exchange["depth"] if self.exchange else 0) + (1 if u.get("reply") and self.exchange else 0)
            self.exchange = {"until": now + EXCHANGE_S, "depth": depth}
        elif u.get("audible_at") and self.brain_ok:
            if self.overlap and not self.overlap_released:
                if self.presenter_speaking:
                    # Still talking as she finishes: they had started answering (or carried on regardless). The brain
                    # hears all of it, in order. This runs before anything else can append, so no frame jumps ahead.
                    await self.brain.append(bytes(self.overlap))
                else:
                    # They stopped before she did: trailing off, or a reflex "yeah". Not an answer.
                    log.info("dropped %.1f s of presenter audio said while she spoke", len(self.overlap) / 48_000)
            await self.brain.mark("[She has finished speaking.]")
        self.overlap.clear()
        if not talked_over and kind in ("interjection", "greeting", "factcheck_answer"):
            # The presenter's next words are a reply to her: the brain hears every pause. A reply of hers
            # that asks nothing ("Okay, go on.") closes the exchange.
            reply = u.get("reply") and self.exchange
            if reply and "?" not in text:
                self.exchange = None
            else:
                self.exchange = {"until": now + EXCHANGE_S, "depth": self.exchange["depth"] + 1 if reply else 0}
                if self.exchange["depth"] >= self.follow_ups:
                    # She has pressed as far as this character does: the point waits for the questions, and the
                    # presenter gets room to move on (live run, Sat 03:44: five lines in a row on one slide).
                    self.quiet_until = max(self.quiet_until, now + PRESSED_QUIET_S)
                    await self.note("[She has pressed this point enough for now. Let it go"
                                    + (" until the questions" if self.qa_enabled else "")
                                    + ", unless they come back to it.]")

        if kind in ("reminder", "escalation") and self.reminder and not interrupted:
            self.reminder["played_at"] = now
            self.quiet_until = now + IGNORE_AFTER_S + 1.0
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
        elif kind == "qa" and self.phase == "qa":
            # Her question has played (or the presenter cut in): the answer starts now.
            self.answer_since, self.qa_quiet_since, self.qa_nudges = now, now, 0
            self.answered = self.presenter_speaking
            if self.qa_over:
                self._spawn(self._qa_overtime())
        await self.idle_state()

    # ------------------------------------------------------------------ presentation
    async def begin(self) -> None:
        # The server closes a Realtime session after 5 idle minutes, so the ones opened at launch
        # may be gone by the time the presenter presses Start.
        await self.realtime.ensure_connected()
        if self.brain:
            try:
                await self.brain.ensure_connected()
            except Exception as exc:
                log.error("brain unavailable (%s): reminders and fixed questions only", exc)
        self.phase = "presentation"
        self.started = time.monotonic()
        # The web re-sends {type:"start"} every 2 s until its first viva.ui message: answer at once.
        await self.ui_state("listening")
        self.slog.start()
        self.slog.write("phase", phase="presentation")
        self.slog.write("slide", index=self.slide)
        await self.note(f"[The exam starts now. Slide {self.slide} is showing.]")
        self._spawn(self._greet())
        self._spawn(self._timer())
        self._spawn(self._watchdog())

    async def _greet(self) -> None:
        await asyncio.sleep(GREETING_DELAY_S)
        minutes = max(1, round(self.config.get("time_limit_s", 300) / 60))
        await self.say("greeting", f"Greet the presenter in one sentence: good afternoon, they have {minutes} minutes, "
                       "begin when ready.", max_tokens=50)

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
                    self._requested = None
                    await self.say("factcheck_answer", "Your web search did not return. In one or two short sentences, "
                                   f"say from what you know whether this claim is right, starting with the correction: {claim}",
                                   max_tokens=80)
            while self.playing and now > self.playing[0]["expected_end"]:
                u = self.playing.popleft()
                log.warning("watchdog: no playback_finished for %s; assuming it finished", u["kind"])
                await self._utterance_finished(u, interrupted=False)
            if self.brain:
                self.brain.check_stuck()
            if self.phase == "presentation":
                await self._maybe_reveal()  # during long unbroken speech too
            if self._gap_pending and not self.presenter_speaking and self._may_cut_in():
                ctx, self._gap_pending = self._gap_pending, None
                await self._ask_brain({**ctx, "pause_at": now})
            if (self.phase == "qa" and self.answer_since is not None and not self.presenter_speaking
                    and not self.engaged and now - self.qa_quiet_since >= QA_SILENCE_S and self.qa_nudges < QA_NUDGES):
                # Nothing more said: the brain decides whether to wait, rephrase or move on.
                self.qa_nudges += 1
                self.qa_quiet_since = now
                await self.note(f"[{QA_SILENCE_S * self.qa_nudges} seconds without an answer from the presenter.]")
                await self._qa_ask(now)

    async def _timer(self) -> None:
        limit = self.config.get("time_limit_s", 300)
        if limit - self.reminder_before_s > 20:
            await asyncio.sleep(max(0.0, limit - self.reminder_before_s - self.elapsed()))
            if self.phase == "presentation":
                minutes = max(1, round(self.reminder_before_s / 60))
                await self.remind("t_minus_2", f"{minutes} minute{'s' if minutes > 1 else ''} left.")
        await asyncio.sleep(max(0.0, limit - self.elapsed()))
        if self.phase == "presentation":
            await self.remind("time_up", "Time is up. Stop there, please; we move to questions." if self.qa_enabled
                              else "Time is up. Thank you, that's the end of your presentation.")

    async def remind(self, kind: str, words: str) -> None:
        await self.wait_idle(timeout=8)
        self.slog.write("reminder", reminder=kind)
        await self.ui.publish({"type": "reminder", "kind": kind, "acknowledged": None})
        if kind == "t_minus_2":
            self.reminder = {"kind": kind, "played_at": None, "escalated": False, "acked": False,
                             "issued": time.monotonic()}
        for _ in range(30):  # a web search can hold the floor for 25 s: keep trying (sim, Sat 05:25)
            if self.phase != "presentation":
                return
            if await self.say("time_up" if kind == "time_up" else "reminder", f"Give a time reminder. Say only: \"{words}\"",
                              hold=True, max_tokens=40):
                return
            await self.wait_idle(timeout=1)

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
        for _ in range(10):
            if self.phase != "presentation" or await self.say(
                    "escalation", "The presenter ignored your time reminder and kept talking. Cut in firmly and hold "
                    f"the floor. Say: \"Let me stop you there. You have under {minutes} minute{'s' if minutes > 1 else ''}. "
                    "Move to your conclusion.\"", hold=True, max_tokens=60):
                return
            await self.wait_idle(timeout=1)

    # ------------------------------------------------------------------ Q&A
    async def enter_qa(self) -> None:
        if self.phase != "presentation":
            return
        if not self.qa_enabled:
            await self.finish()  # no question time: the presentation is the exam
            return
        self.phase = "qa"
        self.reminder = None
        self.exchange = None
        self.slog.write("phase", phase="qa")
        await self.ui_state("qa")
        # Web search off: in the first live run she re-ran the presentation's fact-check three times in Q&A.
        await self.realtime.update_instructions(prompts.for_phase(self.config, "qa"), tools=[])
        if self.brain_ok:
            await self.brain.update_instructions(self._qa_prompt())
        await self.wait_idle(timeout=8)
        self._spawn(self._qa_timer())
        raised = " / ".join(f'"{line}"' for line in self.raised)
        await self.note("[The presentation is over: question time starts now. "
                        + (f"During the talk she already raised: {raised}. Don't ask those again unless the answer "
                           "was missing or wrong. " if raised else "")
                        + "Thank them in a few words, then ask your first question.]")
        if not await self._ask_when_free({"phase": "qa", "pause_at": time.monotonic(), "first": True},
                                         self._qa_prompt() + "\n\nAsk your first question now. Answer SAY."):
            await self._fallback_question(first=True)

    async def _qa_timer(self) -> None:
        await asyncio.sleep(self.config.get("qa_s", 120))
        if self.phase != "qa":
            return
        self.qa_over = True
        await self.note("[Question time is up. When they have finished their current answer, END.]")
        if self.answer_since is not None and self.answered and not self.presenter_speaking and not self.engaged:
            await self._qa_ask(time.monotonic())
        await asyncio.sleep(QA_GRACE_S)
        if self.phase == "qa":
            await self.enter_debrief()  # the exchange under way didn't finish in time

    async def _qa_overtime(self) -> None:
        """Time ran out while she was asking: give them a short window to answer, then close."""
        await asyncio.sleep(QA_GRACE_S / 2)
        if self.phase == "qa" and not self.answered and not self.engaged:
            await self.enter_debrief()

    async def _qa_end_of_turn(self) -> None:
        await asyncio.sleep(max(0.0, self.qa_patience - VAD_SILENCE_S))  # thinking time: longer than in the talk
        if self.engaged:  # e.g. the cancelled reply after a barge-in is still winding down
            await self.wait_idle(timeout=3)
        if (self.phase == "qa" and self.answer_since is not None and self.answered and not self.presenter_speaking
                and not self.engaged):
            await self._qa_ask(self.pause_at or time.monotonic())

    async def _qa_ask(self, pause_at: float) -> None:
        if not self.brain_ok:
            await self._fallback_question()
            return
        instructions = None
        if self.qa_over:
            instructions = self._qa_prompt() + "\n\nQuestion time is over now: answer with END."
        await self._ask_brain({"phase": "qa", "pause_at": pause_at}, instructions)

    async def _fallback_question(self, first=False) -> None:
        """The brain is unavailable: ask the prepared questions in order, then the verdict."""
        if not self.fallback_questions or self.qa_over:
            await self.enter_debrief()
            return
        q = self.fallback_questions.pop(0)
        self.qa_asked += 1
        lead = "Thank the presenter in at most three words, then ask" if first else \
            "React to the presenter's answer in at most one sentence, then ask"
        await self.say("qa", f"{lead}, in at most 20 words: {q}", max_tokens=80, metric="answer_end_to_reply")

    async def _maybe_barge_in(self, speech_start: float) -> None:
        """Stop her if the presenter keeps talking over her: one unbroken stretch of speech (the VAD merges gaps
        under 0.6 s) past the hold window, longer in the presentation, where she was the one who cut in."""
        grace = BARGE_IN_S if self.phase == "qa" else BARGE_IN_TALK_S
        await asyncio.sleep(max(0.0, self.hold_until - time.monotonic()) + grace)
        u = self._audible()
        if (self.phase in ("presentation", "qa") and self.presenter_speaking and self.last_speech_start == speech_start
                and u is not None and u["kind"] in BARGEABLE):
            log.info("barge-in: the presenter is talking over her (%s)", u["kind"])
            if self.brain_ok and self.overlap:
                await self.brain.append(bytes(self.overlap))  # a real talk-over: the brain hears what they said
            self.overlap.clear()
            self.overlap_released = True
            self.cancel_at = time.monotonic()
            await self.realtime.cancel()
            self.output.clear()

    # ------------------------------------------------------------------ debrief
    async def enter_debrief(self, react: str | None = None) -> None:
        if self.phase not in ("presentation", "qa"):
            return
        if not self.qa_enabled:
            await self.finish()  # no verdict either
            return
        self.phase = "debrief"
        if self.qa_turn and self.qa_turn is not asyncio.current_task():
            self.qa_turn.cancel()
        self.slog.write("phase", phase="debrief")
        await self.ui_state("debrief")
        await self.realtime.update_instructions(prompts.for_phase(self.config, "debrief"))
        await self.wait_idle(timeout=10)
        if react:
            await self.say("closing", prompts.say_exactly(react), max_tokens=60, line=react)
        # The voice gives the verdict: it heard the whole exam too. (Asked of the brain, it came back empty after
        # an upstream error once and as "Hello. Let's begin." once; the voice's verdict was good both times.)
        await self.wait_idle(timeout=10)
        await self.say("verdict", "Give your verdict in at most three sentences: one genuine strength, the biggest "
                       "weakness, and one concrete fix. Start the verdict with the word Verdict.", max_tokens=200)

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
