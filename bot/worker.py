"""Async worker that processes the transcription queue."""

import asyncio
import logging

from bot.queue import DeduplicationQueue
from bot.whisper import WhisperClient

logger = logging.getLogger(__name__)

MSG_EMPTY = "Речь не распознана."
MSG_ERROR = "Ошибка при транскрипции. Попробуйте ещё раз."
TELEGRAM_MESSAGE_LIMIT = 4096


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split text into Telegram-sized chunks, preferring natural boundaries."""
    chunks: list[str] = []
    remaining = text

    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at <= 0:
            split_at = limit

        chunk = remaining[:split_at].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)

    return chunks


async def run_worker(
    queue: DeduplicationQueue,
    whisper_client: WhisperClient,
    bot,
) -> None:
    """Continuously process transcription tasks from the queue.

    For each task:
      1. Download the media file from Telegram.
      2. Send bytes to WhisperClient for transcription.
      3. Reply to the user in the same chat.

    Stops cleanly on asyncio.CancelledError (e.g. SIGTERM).

    Args:
        queue: Shared DeduplicationQueue instance.
        whisper_client: WhisperClient pointing at the HTTP bridge.
        bot: python-telegram-bot Bot instance.
    """
    logger.info("Worker started")
    try:
        while True:
            task = await queue.get()
            logger.debug("Processing task for user %s (media: %s)", task.user_id, task.media_type)
            try:
                tg_file = await bot.get_file(task.file_id)
                audio_bytes = bytes(await tg_file.download_as_bytearray())

                text = await whisper_client.transcribe(audio_bytes, task.media_type)

                if not text.strip():
                    text = MSG_EMPTY

                for chunk in split_message(text):
                    await bot.send_message(
                        chat_id=task.chat_id,
                        text=chunk,
                        reply_to_message_id=task.message_id,
                    )

            except asyncio.CancelledError:
                raise  # propagate to outer try

            except Exception as exc:
                logger.error(
                    "Worker error for user %s: %s",
                    task.user_id,
                    exc,
                    exc_info=True,
                )
                try:
                    await bot.send_message(
                        chat_id=task.chat_id,
                        text=MSG_ERROR,
                        reply_to_message_id=task.message_id,
                    )
                except Exception:
                    pass  # best-effort reply

    except asyncio.CancelledError:
        logger.info("Worker cancelled, shutting down")
