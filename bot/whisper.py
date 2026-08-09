"""HTTP client for the Whisper Wyoming Bridge service.

Sends audio bytes to the local HTTP bridge (whisper_service/main.py)
which handles ffmpeg decoding and Wyoming protocol communication.

The bridge exposes:
    POST /transcribe  — multipart upload, returns {"text": "..."}
"""

import io
import aiohttp


class WhisperClient:
    """Async HTTP client for the Whisper bridge service.

    Args:
        base_url: Base URL of the whisper_service, e.g. ``http://whisper-bridge:8000``.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def transcribe(self, audio_bytes: bytes, media_type: str) -> str:
        """Send audio to the bridge and return transcript text.

        Args:
            audio_bytes: Raw bytes of the audio/video file.
            media_type: One of ``"voice"``, ``"video"``, ``"video_note"``.

        Returns:
            Transcript text string.

        Raises:
            RuntimeError: On HTTP error or missing ``text`` field in response.
        """
        # Choose a sensible filename/mime so the bridge's ffmpeg can identify format
        filename, content_type = _MEDIA_FILE_INFO.get(
            media_type, ("audio.bin", "application/octet-stream")
        )

        url = f"{self._base_url}/transcribe"

        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field(
                "file",
                audio_bytes,
                filename=filename,
                content_type=content_type,
            )

            async with session.post(url, data=form) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise RuntimeError(
                        f"Whisper bridge error {response.status}: {body}"
                    )

                data = await response.json()

                if "error" in data:
                    raise RuntimeError(f"Whisper bridge returned error: {data['error']}")

                return data.get("text", "")


# Mapping media_type → (filename, MIME type)
_MEDIA_FILE_INFO: dict[str, tuple[str, str]] = {
    "voice":      ("audio.ogg", "audio/ogg"),
    "video":      ("video.mp4", "video/mp4"),
    "video_note": ("video.mp4", "video/mp4"),
}
