"""Client for docker-gigaam-server's multipart transcription and SSE endpoint."""

import json
from collections.abc import Callable

import httpx


class AsrUnavailableError(RuntimeError):
    pass


class TranscriptionTimeoutError(RuntimeError):
    pass


class GigaAMClient:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: float):
        self.url = base_url.rstrip("/") + "/v1/audio/transcriptions"
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.timeout = timeout

    async def transcribe(self, audio_bytes: bytes, media_type: str,
                         on_delta: Callable[[str], None]) -> str:
        name, mime = {
            "voice": ("voice.ogg", "audio/ogg"),
            "video": ("video.mp4", "video/mp4"),
            "video_note": ("video.mp4", "video/mp4"),
            "m4a": ("audio.m4a", "audio/mp4"),
            "audio": ("audio", "application/octet-stream"),
        }[media_type]
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", self.url, headers=self.headers,
                    data={"model": self.model, "stream": "true", "response_format": "json"},
                    files={"file": (name, audio_bytes, mime)},
                ) as response:
                    if response.status_code >= 500:
                        raise AsrUnavailableError(f"GigaAM HTTP {response.status_code}")
                    response.raise_for_status()
                    # The server emits a single JSON data line per SSE event.
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        event = json.loads(payload)
                        if "error" in event:
                            raise RuntimeError("GigaAM reported a transcription error")
                        if event.get("type") == "transcript.text.delta":
                            on_delta(event["delta"])
                        elif event.get("type") == "transcript.text.done":
                            return event["text"]
        except httpx.TimeoutException as exc:
            raise TranscriptionTimeoutError("GigaAM timed out") from exc
        except httpx.TransportError as exc:
            raise AsrUnavailableError("GigaAM connection failed") from exc
        raise RuntimeError("GigaAM stream ended without a transcript")
