"""Presenter pause detection with Silero VAD (local, runs on CPU).

Calls on_speech_start() when the presenter starts talking and on_pause() once they have
been silent for min_silence seconds. Silero resamples the 24 kHz input itself.
"""

import asyncio
import logging
from typing import Awaitable, Callable

from livekit import rtc
from livekit.agents.vad import VADEventType
from livekit.plugins import silero

log = logging.getLogger("viva.vad")

_MODEL = None


def load(min_silence: float = 0.6):
    """Load the ONNX model once (takes a second); reuse it for every stream."""
    global _MODEL
    if _MODEL is None:
        _MODEL = silero.VAD.load(min_silence_duration=min_silence, activation_threshold=0.5)
    return _MODEL


class PauseDetector:
    def __init__(self, on_speech_start: Callable[[], Awaitable[None]], on_pause: Callable[[], Awaitable[None]],
                 min_silence: float = 0.6):
        self._stream = load(min_silence).stream()
        self._on_speech_start = on_speech_start
        self._on_pause = on_pause
        self.speaking = False
        self._task = asyncio.create_task(self._run())

    def push(self, frame: rtc.AudioFrame) -> None:
        self._stream.push_frame(frame)

    async def _run(self) -> None:
        async for event in self._stream:
            if event.type == VADEventType.START_OF_SPEECH:
                self.speaking = True
                await self._on_speech_start()
            elif event.type == VADEventType.END_OF_SPEECH:
                self.speaking = False
                await self._on_pause()

    async def aclose(self) -> None:
        self._task.cancel()
        await self._stream.aclose()
