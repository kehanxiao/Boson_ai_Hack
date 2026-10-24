"""Where the examiner's voice goes: the avatar, the agent's own audio track, or nowhere (simulation).

All three expose the same interface:
    await capture(pcm)   queue 24 kHz 16-bit mono PCM for the current utterance
    flush()              end of an utterance (one per Realtime response)
    clear()              stop now (barge-in), dropping everything not yet played
    on_finished(cb)      cb(playback_position_s, interrupted): once per flushed utterance when it
                         has played, or once for everything when clear() interrupts
"""

import asyncio
import time
from typing import Callable

from livekit import rtc
from livekit.agents.voice.avatar import DataStreamAudioOutput

RATE = 24_000
Finished = Callable[[float, bool], None]


class AvatarOutput:
    def __init__(self, room: rtc.Room, avatar_identity: str):
        self._out = DataStreamAudioOutput(
            room, destination_identity=avatar_identity, sample_rate=RATE, wait_remote_track=rtc.TrackKind.KIND_AUDIO
        )
        self._callbacks: list[Finished] = []
        self._out.on("playback_finished", self._finished)

    def on_finished(self, cb: Finished) -> None:
        self._callbacks.append(cb)

    def _finished(self, event) -> None:
        for cb in self._callbacks:
            cb(getattr(event, "playback_position", 0.0), getattr(event, "interrupted", False))

    async def capture(self, pcm: bytes) -> None:
        await self._out.capture_frame(rtc.AudioFrame(pcm, RATE, 1, len(pcm) // 2))

    def flush(self) -> None:
        self._out.flush()

    def clear(self) -> None:
        self._out.clear_buffer()


class _Playback:
    """Real-time playback bookkeeping: when each flushed utterance will have finished playing."""

    def __init__(self):
        self.callbacks: list[Finished] = []
        self.play_end = 0.0  # when everything flushed so far will have played
        self.seg_start: float | None = None
        self.seg_s = 0.0
        self.tasks: list[asyncio.Task] = []
        self.current_start: float | None = None  # start of the utterance playing now

    def add(self, seconds: float) -> None:
        if self.seg_start is None:
            self.seg_start = max(time.monotonic(), self.play_end)
            self.seg_s = 0.0
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
        self._playback.callbacks.append(cb)

    async def capture(self, pcm: bytes) -> None:
        self._playback.add(len(pcm) / (RATE * 2))
        await self.source.capture_frame(rtc.AudioFrame(pcm, RATE, 1, len(pcm) // 2))

    def flush(self) -> None:
        self._playback.flush()

    def clear(self) -> None:
        self.source.clear_queue()
        self._playback.clear()


class SimulatedOutput:
    """Headless runs: 'plays' audio in real time so timing-dependent logic behaves as it would live."""

    def __init__(self):
        self._playback = _Playback()

    def on_finished(self, cb: Finished) -> None:
        self._playback.callbacks.append(cb)

    async def capture(self, pcm: bytes) -> None:
        self._playback.add(len(pcm) / (RATE * 2))

    def flush(self) -> None:
        self._playback.flush()

    def clear(self) -> None:
        self._playback.clear()
