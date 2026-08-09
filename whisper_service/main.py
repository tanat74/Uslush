"""FastAPI HTTP wrapper around Wyoming Protocol (faster-whisper).

Converts multipart audio upload → PCM via ffmpeg → Wyoming → JSON transcript.

Environment variables:
    WYOMING_HOST    - Wyoming server host (default: 192.168.88.12)
    WYOMING_PORT    - Wyoming server port (default: 10305)
    WHISPER_LANGUAGE - Recognition language (default: ru)
"""

import asyncio
import os
import socket
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WYOMING_HOST = os.environ.get("WYOMING_HOST", "192.168.88.12")
WYOMING_PORT = int(os.environ.get("WYOMING_PORT", "10305"))
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "ru")

# PCM parameters expected by faster-whisper
PCM_RATE = 16000
PCM_WIDTH = 2       # bytes per sample (s16le)
PCM_CHANNELS = 1
CHUNK_SIZE = 3200   # ~100 ms of mono 16kHz 16-bit PCM

app = FastAPI(title="Whisper Wyoming HTTP Bridge")


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

async def decode_to_pcm(audio_bytes: bytes) -> bytes:
    """Decode any audio format to PCM S16LE 16kHz mono via ffmpeg."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".audio") as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        proc = await asyncio.create_subprocess_exec(
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
        pcm_data, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg error: {stderr.decode(errors='replace')}")
        return pcm_data
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Wyoming client
# ---------------------------------------------------------------------------

async def transcribe_via_wyoming(pcm_data: bytes) -> str:
    """Send PCM audio to Wyoming server and return transcript text."""
    async with AsyncTcpClient(WYOMING_HOST, WYOMING_PORT) as client:
        # 1. Request transcription
        await client.write_event(
            Transcribe(language=WHISPER_LANGUAGE).event()
        )

        # 2. Signal audio stream start
        await client.write_event(
            AudioStart(
                rate=PCM_RATE,
                width=PCM_WIDTH,
                channels=PCM_CHANNELS,
            ).event()
        )

        # 3. Send PCM in chunks
        offset = 0
        while offset < len(pcm_data):
            chunk = pcm_data[offset:offset + CHUNK_SIZE]
            await client.write_event(
                AudioChunk(
                    rate=PCM_RATE,
                    width=PCM_WIDTH,
                    channels=PCM_CHANNELS,
                    audio=chunk,
                ).event()
            )
            offset += CHUNK_SIZE

        # 4. Signal end of audio
        await client.write_event(AudioStop().event())

        # 5. Wait for Transcript event
        while True:
            event = await client.read_event()
            if event is None:
                raise RuntimeError("Wyoming server closed connection without sending Transcript")
            if Error.is_type(event.type):
                error = Error.from_event(event)
                details = f" ({error.code})" if error.code else ""
                raise RuntimeError(f"Wyoming server error{details}: {error.text}")
            if Transcript.is_type(event.type):
                transcript = Transcript.from_event(event)
                return transcript.text

    raise RuntimeError("Transcript not received")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Accept audio file, transcribe via Wyoming, return JSON with text."""
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty file")

        pcm_data = await decode_to_pcm(audio_bytes)
        if not pcm_data:
            raise HTTPException(status_code=422, detail="ffmpeg produced no PCM output")

        text = await transcribe_via_wyoming(pcm_data)
        return {"text": text}

    except HTTPException:
        raise
    except RuntimeError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Internal error: {e}"})


@app.get("/health")
async def health():
    """Health check — also verifies TCP connectivity to Wyoming server."""
    tcp_ok = False
    try:
        loop = asyncio.get_event_loop()
        conn = asyncio.open_connection(WYOMING_HOST, WYOMING_PORT)
        reader, writer = await asyncio.wait_for(conn, timeout=3.0)
        writer.close()
        await writer.wait_closed()
        tcp_ok = True
    except Exception:
        tcp_ok = False

    return {
        "status": "ok" if tcp_ok else "degraded",
        "wyoming_host": WYOMING_HOST,
        "wyoming_port": WYOMING_PORT,
        "wyoming_reachable": tcp_ok,
    }
