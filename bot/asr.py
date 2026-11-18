"""Shared transcription contract: incremental text and an authoritative result."""

from collections.abc import Callable
from typing import Protocol


class Transcriber(Protocol):
    async def transcribe(
        self, audio_bytes: bytes, media_type: str, on_delta: Callable[[str], None]
    ) -> str: ...


class TranscriptionTimeoutError(RuntimeError):
    pass


class AsrUnavailableError(RuntimeError):
    pass
