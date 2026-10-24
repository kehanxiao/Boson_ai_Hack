"""Where the examiner's voice goes: the avatar, the agent's own audio track, or nowhere (simulation).

All three expose the same interface:
    await capture(pcm)   queue 24 kHz 16-bit mono PCM for the current utterance
    flush()              end of an utterance (one per Realtime response)
    clear()              stop now (barge-in), dropping everything not yet played
    on_finished(cb)      cb(playback_position_s, interrupted): once per flushed utterance when it
                         has played, or once for everything when clear() interrupts
    on_started(cb)       cb(estimated): when an utterance starts to be heard in the room. The model
                         generates faster than real time and the avatar renders first, so this is
                         ~1.4 s after the first audio is captured with the avatar, ~0.1-0.2 s voice-only
                         (probes/live_room.py). Everything about "she is speaking" runs on this clock.
"""

import asyncio
import logging
import time
from typing import Callable

from livekit import rtc
from livekit.agents.voice.avatar import DataStreamAudioOutput

log = logging.getLogger("viva.output")
RATE = 24_000
Finished = Callable[[float, bool], None]
Started = Callable[[bool], None]
# If the avatar doesn't report lk.playback_started: first captured audio -> heard in the room, measured
# 1.36-1.66 s through LiveKit (probes/live_room.py, Sat 04:15).
AVATAR_START_ESTIMATE_S = 1.3


class AvatarOutput:
    def __init__(self, room: rtc.Room, avatar_identity: str):
        # wait_playback_start: the avatar may report when it actually starts playing (lk.playback_started).
        self._out = DataStreamAudioOutput(
            room, destination_identity=avatar_identity, sample_rate=RATE, wait_remote_track=rtc.TrackKind.KIND_AUDIO,
            wait_playback_start=True,
        )
        self._callbacks: list[Finished] = []
        self._started_cbs: list[Started] = []
        self._out.on("playback_finished", self._finished)
        self._out.on("playback_started", self._reported_start)
        self._segment_open = False  # audio captured since the last flush/clear
        self._pending: asyncio.TimerHandle | None = None  # the estimate, unless the avatar reports first
        self._seg_s = 0.0
        self._seg_start_estimate = 0.0
        self._end_estimate = 0.0  # when everything flushed so far should have played

    def on_finished(self, cb: Finished) -> None:
        self._callbacks = [cb]  # one exam controller at a time: a new exam replaces the old callback

    def on_started(self, cb: Started) -> None:
        self._started_cbs = [cb]

    def _finished(self, event) -> None:
        position, interrupted = getattr(event, "playback_position", 0.0), getattr(event, "interrupted", False)
        log.info("avatar playback_finished position=%.2fs interrupted=%s", position, interrupted)
        for cb in self._callbacks:
            cb(position, interrupted)

    def _reported_start(self, _event) -> None:
        if self._pending is None:
            return  # nothing waiting (a late report after the estimate fired)
        self._pending.cancel()
        self._pending = None
        log.info("avatar playback_started (reported)")
        self._fire_started(estimated=False)

    def _estimated_start(self) -> None:
        self._pending = None
        self._fire_started(estimated=True)

    def _fire_started(self, estimated: bool) -> None:
        for cb in self._started_cbs:
            cb(estimated)

    async def capture(self, pcm: bytes) -> None:
        if not self._segment_open:
            self._segment_open = True
            self._seg_s = 0.0
            loop = asyncio.get_running_loop()
            # Back to back (a fact-check's preamble, then its answer): this one starts when the last one ends.
            at = max(time.monotonic() + AVATAR_START_ESTIMATE_S, self._end_estimate)
            if self._pending:
                self._pending.cancel()
            self._pending = loop.call_later(at - time.monotonic(), self._estimated_start)
            self._seg_start_estimate = at
        self._seg_s += len(pcm) / (RATE * 2)
        await self._out.capture_frame(rtc.AudioFrame(pcm, RATE, 1, len(pcm) // 2))

    def flush(self) -> None:
        if self._segment_open:
            self._end_estimate = self._seg_start_estimate + self._seg_s
        self._segment_open = False
        self._out.flush()

    def clear(self) -> None:
        if self._pending:
            self._pending.cancel()
            self._pending = None
        self._segment_open = False
        self._end_estimate = 0.0
        self._out.clear_buffer()


class _Playback:
    """Real-time playback bookkeeping: when each flushed utterance will have finished playing."""

    def __init__(self):
        self.callbacks: list[Finished] = []
        self.started_cbs: list[Started] = []
        self.delay = 0.0  # simulated output latency (the avatar's rendering) before an utterance is heard
        self.play_end = 0.0  # when everything flushed so far will have played
        self.seg_start: float | None = None
        self.seg_s = 0.0
        self.tasks: list[asyncio.Task] = []
        self.current_start: float | None = None  # start of the utterance playing now

    def add(self, seconds: float) -> None:
        if self.seg_start is None:
            self.seg_start = max(time.monotonic() + self.delay, self.play_end)
            self.seg_s = 0.0
            start = self.seg_start

            async def started():
                await asyncio.sleep(max(0.0, start - time.monotonic()))  # after the utterances before it
                for cb in self.started_cbs:
                    cb(False)
            self.tasks.append(asyncio.create_task(started()))
        self.seg_s += seconds

    def flush(self) -> None:
        if self.seg_start is None:
            return
        start, end = self.seg_start, self.seg_start + self.seg_s
        self.play_end, self.seg_start = end, None

        async def finish():
            await asyncio.sleep(max(0.0, start - time.monotonic()))  # earlier utterances play first
            self.current_start = start
            await asyncio.sleep(max(0.0, end - time.monotonic()))
            self._fire(end - start, False)
        self.tasks.append(asyncio.create_task(finish()))

    def clear(self) -> None:
        now = time.monotonic()
        busy = self.play_end > now or self.seg_start is not None
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
        played = max(0.0, now - self.current_start) if self.current_start else 0.0
        self.play_end, self.seg_start, self.current_start = now, None, None
        if busy:
            self._fire(played, True)

    def _fire(self, played: float, interrupted: bool) -> None:
        for cb in self.callbacks:
            cb(played, interrupted)


class VoiceOutput:
    """VIVA_AVATAR=0: the agent publishes the examiner's voice as its own audio track."""

    def __init__(self, room: rtc.Room):
        self.room = room
        # A large queue so capture() never blocks the Realtime reader while audio plays out.
        self.source = rtc.AudioSource(RATE, 1, queue_size_ms=120_000)
        self._playback = _Playback()

    async def start(self) -> None:
        track = rtc.LocalAudioTrack.create_audio_track("examiner", self.source)
        await self.room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))

    def on_finished(self, cb: Finished) -> None:
        self._playback.callbacks = [cb]  # one exam controller at a time

    def on_started(self, cb: Started) -> None:
        self._playback.started_cbs = [cb]

    async def capture(self, pcm: bytes) -> None:
        self._playback.add(len(pcm) / (RATE * 2))
        await self.source.capture_frame(rtc.AudioFrame(pcm, RATE, 1, len(pcm) // 2))

    def flush(self) -> None:
        self._playback.flush()

    def clear(self) -> None:
        self.source.clear_queue()
        self._playback.clear()


class SimulatedOutput:
    """Headless runs: 'plays' audio in real time so timing-dependent logic behaves as it would live.
    delay: seconds before an utterance is heard, e.g. 1.3 to behave like the avatar."""

    def __init__(self, delay: float = 0.0):
        self._playback = _Playback()
        self._playback.delay = delay

    def on_finished(self, cb: Finished) -> None:
        self._playback.callbacks = [cb]  # one exam controller at a time

    def on_started(self, cb: Started) -> None:
        self._playback.started_cbs = [cb]

    async def capture(self, pcm: bytes) -> None:
        self._playback.add(len(pcm) / (RATE * 2))

    def flush(self) -> None:
        self._playback.flush()

    def clear(self) -> None:
        self._playback.clear()
