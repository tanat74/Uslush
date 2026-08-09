"""Unit and optional integration tests for bot/whisper.py — WhisperClient."""

import pathlib

import pytest
from aioresponses import aioresponses

from bot.whisper import WhisperClient, _MEDIA_FILE_INFO

BRIDGE_URL = "http://whisper:8000"
TRANSCRIBE_URL = f"{BRIDGE_URL}/transcribe"
EXAMPLE_DIR = pathlib.Path(__file__).parent.parent / "Example"
OGG_FILE = EXAMPLE_DIR / "audio_2026-08-09_11-02-34.ogg"
MP4_FILE = EXAMPLE_DIR / "doc_2026-08-09_11-02-43.mp4"


@pytest.fixture
def client() -> WhisperClient:
    return WhisperClient(BRIDGE_URL)


# ---------------------------------------------------------------------------
# MIME/filename mapping (no network call)
# ---------------------------------------------------------------------------


def test_voice_mime_mapping():
    filename, mime = _MEDIA_FILE_INFO["voice"]
    assert filename == "audio.ogg"
    assert mime == "audio/ogg"


def test_video_note_mime_mapping():
    filename, mime = _MEDIA_FILE_INFO["video_note"]
    assert filename == "video.mp4"
    assert mime == "video/mp4"


def test_video_mime_mapping():
    filename, mime = _MEDIA_FILE_INFO["video"]
    assert filename == "video.mp4"
    assert mime == "video/mp4"


# ---------------------------------------------------------------------------
# Unit tests with mocked HTTP (aioresponses)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_success(client: WhisperClient):
    with aioresponses() as mocked:
        mocked.post(TRANSCRIBE_URL, payload={"text": "Привет, мир!"})
        result = await client.transcribe(b"fake-audio", "voice")
    assert result == "Привет, мир!"


@pytest.mark.asyncio
async def test_transcribe_video_note(client: WhisperClient):
    with aioresponses() as mocked:
        mocked.post(TRANSCRIBE_URL, payload={"text": "video note text"})
        result = await client.transcribe(b"mp4-bytes", "video_note")
    assert result == "video note text"


@pytest.mark.asyncio
async def test_transcribe_video(client: WhisperClient):
    with aioresponses() as mocked:
        mocked.post(TRANSCRIBE_URL, payload={"text": "video text"})
        result = await client.transcribe(b"mp4-bytes", "video")
    assert result == "video text"


@pytest.mark.asyncio
async def test_transcribe_http_500_raises(client: WhisperClient):
    with aioresponses() as mocked:
        mocked.post(TRANSCRIBE_URL, status=500, body="Internal Server Error")
        with pytest.raises(RuntimeError, match="Whisper bridge error 500"):
            await client.transcribe(b"audio", "voice")


@pytest.mark.asyncio
async def test_transcribe_http_422_raises(client: WhisperClient):
    with aioresponses() as mocked:
        mocked.post(TRANSCRIBE_URL, status=422, body='{"detail":"Unprocessable"}')
        with pytest.raises(RuntimeError, match="Whisper bridge error 422"):
            await client.transcribe(b"audio", "voice")


@pytest.mark.asyncio
async def test_transcribe_error_field_raises(client: WhisperClient):
    with aioresponses() as mocked:
        mocked.post(TRANSCRIBE_URL, payload={"error": "Wyoming unavailable"})
        with pytest.raises(RuntimeError, match="Whisper bridge returned error"):
            await client.transcribe(b"audio", "voice")


# ---------------------------------------------------------------------------
# Optional integration tests (require live whisper_service on :8000)
# ---------------------------------------------------------------------------


def _bridge_available() -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            return True
    except OSError:
        return False


def _example_files_available() -> bool:
    return OGG_FILE.is_file() and MP4_FILE.is_file()


integration = pytest.mark.skipif(
    not (_bridge_available() and _example_files_available()),
    reason="Live whisper bridge on :8000 and Example/ media files required",
)


@integration
@pytest.mark.asyncio
async def test_transcribe_ogg_file_integration():
    client = WhisperClient("http://127.0.0.1:8000")
    result = await client.transcribe(OGG_FILE.read_bytes(), "voice")
    assert isinstance(result, str)
    assert result.strip() != ""


@integration
@pytest.mark.asyncio
async def test_transcribe_mp4_file_integration():
    client = WhisperClient("http://127.0.0.1:8000")
    result = await client.transcribe(MP4_FILE.read_bytes(), "video")
    assert isinstance(result, str)
    assert result.strip() != ""
