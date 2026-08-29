"""Audio decoding and direct transcription through Wyoming."""

import asyncio
import tempfile
from pathlib import Path

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error


PCM_RATE = 16000
PCM_WIDTH = 2
PCM_CHANNELS = 1
CHUNK_SIZE = 3200
MAX_AUDIO_SEC = 180.0
DEFAULT_FFMPEG_TIMEOUT = 120.0
DEFAULT_WYOMING_TIMEOUT = 300.0


class AudioTooLongError(RuntimeError):
    """Raised when decoded audio exceeds the maximum allowed duration."""


class TranscriptionTimeoutError(RuntimeError):
    """Raised when ffmpeg or Wyoming exceeds the configured timeout."""


class AsrUnavailableError(RuntimeError):
    """Raised when the Wyoming ASR server cannot be reached."""


def pcm_duration_sec(pcm_data: bytes) -> float:
    """Return decoded PCM duration in seconds."""
    frame_bytes = PCM_RATE * PCM_WIDTH * PCM_CHANNELS
    return len(pcm_data) / frame_bytes


class WhisperClient:
    """Decode Telegram media and send it directly to a Wyoming ASR server."""

    def __init__(
        self,
        host: str,
        port: int,
        language: str = "ru",
        ffmpeg_timeout: float = DEFAULT_FFMPEG_TIMEOUT,
        wyoming_timeout: float = DEFAULT_WYOMING_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._language = language
        self._ffmpeg_timeout = ffmpeg_timeout
        self._wyoming_timeout = wyoming_timeout

    async def transcribe(self, audio_bytes: bytes, media_type: str) -> str:
        """Decode audio/video bytes and return text produced by Wyoming."""
        if not audio_bytes:
            raise RuntimeError("Empty audio file")

        pcm_data = await self._decode_to_pcm(audio_bytes)
        if not pcm_data:
            raise RuntimeError("ffmpeg produced no PCM output")
        if pcm_duration_sec(pcm_data) > MAX_AUDIO_SEC:
            raise AudioTooLongError("Audio is too long for recognition")
        try:
            async with asyncio.timeout(self._wyoming_timeout):
                return await self._transcribe_via_wyoming(pcm_data)
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise TranscriptionTimeoutError(
                "Wyoming transcription timed out"
            ) from exc
        except (OSError, ConnectionError) as exc:
            raise AsrUnavailableError(
                "Wyoming server is unavailable"
            ) from exc

    async def _decode_to_pcm(self, audio_bytes: bytes) -> bytes:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".media") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-loglevel", "error",
                "-i", tmp_path,
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ar", str(PCM_RATE),
                "-ac", str(PCM_CHANNELS),
                "pipe:1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                pcm_data, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._ffmpeg_timeout,
                )
            except TimeoutError as exc:
                process.kill()
                try:
                    await asyncio.wait_for(process.communicate(), timeout=5)
                except Exception:
                    pass
                raise TranscriptionTimeoutError("ffmpeg timed out") from exc
            if process.returncode != 0:
                message = stderr.decode(errors="replace")
                raise RuntimeError(f"ffmpeg error: {message}")
            return pcm_data
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def _transcribe_via_wyoming(self, pcm_data: bytes) -> str:
        async with AsyncTcpClient(self._host, self._port) as client:
            await client.write_event(Transcribe(language=self._language).event())
            await client.write_event(
                AudioStart(
                    rate=PCM_RATE,
                    width=PCM_WIDTH,
                    channels=PCM_CHANNELS,
                ).event()
            )

            for offset in range(0, len(pcm_data), CHUNK_SIZE):
                await client.write_event(
                    AudioChunk(
                        rate=PCM_RATE,
                        width=PCM_WIDTH,
                        channels=PCM_CHANNELS,
                        audio=pcm_data[offset:offset + CHUNK_SIZE],
                    ).event()
                )

            await client.write_event(AudioStop().event())

            while True:
                event = await client.read_event()
                if event is None:
                    raise RuntimeError(
                        "Wyoming server closed connection without sending Transcript"
                    )
                if Error.is_type(event.type):
                    error = Error.from_event(event)
                    details = f" ({error.code})" if error.code else ""
                    raise RuntimeError(
                        f"Wyoming server error{details}: {error.text}"
                    )
                if Transcript.is_type(event.type):
                    return Transcript.from_event(event).text
