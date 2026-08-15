"""Tests for direct ffmpeg/Wyoming transcription client."""

from unittest.mock import AsyncMock

import pytest

from bot.whisper import (
    MAX_AUDIO_SEC,
    PCM_CHANNELS,
    PCM_RATE,
    PCM_WIDTH,
    AudioTooLongError,
    WhisperClient,
)


def pcm_bytes(duration_sec: float) -> bytes:
    return bytes(int(duration_sec * PCM_RATE * PCM_WIDTH * PCM_CHANNELS))


@pytest.fixture
def client() -> WhisperClient:
    return WhisperClient("wyoming.local", 10305, "ru")


@pytest.mark.asyncio
async def test_transcribe_decodes_and_sends_pcm(client: WhisperClient, monkeypatch):
    decode = AsyncMock(return_value=b"pcm-data")
    recognize = AsyncMock(return_value="Привет, мир!")
    monkeypatch.setattr(client, "_decode_to_pcm", decode)
    monkeypatch.setattr(client, "_transcribe_via_wyoming", recognize)

    result = await client.transcribe(b"telegram-media", "voice")

    assert result == "Привет, мир!"
    decode.assert_awaited_once_with(b"telegram-media")
    recognize.assert_awaited_once_with(b"pcm-data")


@pytest.mark.asyncio
async def test_transcribe_rejects_empty_input(client: WhisperClient):
    with pytest.raises(RuntimeError, match="Empty audio file"):
        await client.transcribe(b"", "voice")


@pytest.mark.asyncio
async def test_transcribe_rejects_empty_pcm(client: WhisperClient, monkeypatch):
    monkeypatch.setattr(client, "_decode_to_pcm", AsyncMock(return_value=b""))

    with pytest.raises(RuntimeError, match="ffmpeg produced no PCM output"):
        await client.transcribe(b"media", "video")


@pytest.mark.asyncio
async def test_ffmpeg_error_is_reported(client: WhisperClient, monkeypatch):
    process = AsyncMock()
    process.communicate.return_value = (b"", b"invalid input")
    process.returncode = 1
    create_process = AsyncMock(return_value=process)
    monkeypatch.setattr("bot.whisper.asyncio.create_subprocess_exec", create_process)

    with pytest.raises(RuntimeError, match="ffmpeg error: invalid input"):
        await client._decode_to_pcm(b"broken-media")


@pytest.mark.asyncio
async def test_transcribe_maps_long_audio_failure(client: WhisperClient, monkeypatch):
    long_pcm = pcm_bytes(MAX_AUDIO_SEC + 1)
    monkeypatch.setattr(client, "_decode_to_pcm", AsyncMock(return_value=long_pcm))
    monkeypatch.setattr(
        client,
        "_transcribe_via_wyoming",
        AsyncMock(side_effect=RuntimeError("connection closed")),
    )

    with pytest.raises(AudioTooLongError):
        await client.transcribe(b"media", "video")


@pytest.mark.asyncio
async def test_transcribe_keeps_error_for_short_audio(client: WhisperClient, monkeypatch):
    short_pcm = pcm_bytes(10)
    monkeypatch.setattr(client, "_decode_to_pcm", AsyncMock(return_value=short_pcm))
    monkeypatch.setattr(
        client,
        "_transcribe_via_wyoming",
        AsyncMock(side_effect=RuntimeError("connection closed")),
    )

    with pytest.raises(RuntimeError, match="connection closed"):
        await client.transcribe(b"media", "voice")
