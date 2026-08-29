"""Async worker that processes the transcription queue."""

import asyncio
import logging

from telegram.constants import ChatAction

from bot.queue import DeduplicationQueue, TranscriptionTask
from bot.whisper import (
    AsrUnavailableError,
    AudioTooLongError,
    TranscriptionTimeoutError,
    WhisperClient,
)

logger = logging.getLogger(__name__)

MSG_EMPTY = "Речь не распознана."
MSG_ERROR = "Ошибка при транскрипции. Попробуйте ещё раз."
MSG_TOO_LONG = "Файл слишком длинный для распознавания."
MSG_TIMEOUT = "Распознавание заняло слишком много времени. Попробуйте ещё раз."
MSG_UNAVAILABLE = "Сервер распознавания недоступен. Попробуйте позже."
TELEGRAM_MESSAGE_LIMIT = 4096
TYPING_REFRESH_SEC = 4.0


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


async def _keep_typing(bot, chat_id: int) -> None:
    """Refresh the typing indicator until cancelled."""
    try:
        while True:
            await asyncio.sleep(TYPING_REFRESH_SEC)
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except asyncio.CancelledError:
        raise
    except Exception:
        return


async def _reply(bot, task: TranscriptionTask, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=task.chat_id,
            text=text,
            reply_to_message_id=task.message_id,
        )
    except Exception:
        pass  # best-effort reply


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
    Any other exception is logged and the loop continues so one bad
    dequeue or task cannot kill the worker.

    Args:
        queue: Shared DeduplicationQueue instance.
        whisper_client: WhisperClient pointing at the Wyoming ASR server.
        bot: python-telegram-bot Bot instance.
    """
    logger.info("Worker started")
    try:
        while True:
            task = None
            typing_task: asyncio.Task | None = None
            try:
                task = await queue.get()
                logger.debug(
                    "Processing task for user %s (media: %s)",
                    task.user_id,
                    task.media_type,
                )
                try:
                    await bot.send_chat_action(
                        chat_id=task.chat_id,
                        action=ChatAction.TYPING,
                    )
                except Exception:
                    pass
                typing_task = asyncio.create_task(
                    _keep_typing(bot, task.chat_id),
                    name=f"typing-{task.user_id}",
                )

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
                raise

            except AudioTooLongError as exc:
                logger.warning("Audio too long for user %s: %s", task and task.user_id, exc)
                if task is not None:
                    await _reply(bot, task, MSG_TOO_LONG)

            except TranscriptionTimeoutError as exc:
                logger.warning(
                    "Transcription timed out for user %s: %s",
                    task and task.user_id,
                    exc,
                )
                if task is not None:
                    await _reply(bot, task, MSG_TIMEOUT)

            except AsrUnavailableError as exc:
                logger.error("ASR unavailable for user %s: %s", task and task.user_id, exc)
                if task is not None:
                    await _reply(bot, task, MSG_UNAVAILABLE)

            except Exception as exc:
                if task is None:
                    logger.error("Failed to dequeue a transcription task: %s", exc, exc_info=True)
                else:
                    logger.error(
                        "Worker error for user %s: %s",
                        task.user_id,
                        exc,
                        exc_info=True,
                    )
                    await _reply(bot, task, MSG_ERROR)

            finally:
                if typing_task is not None:
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass

    except asyncio.CancelledError:
        logger.info("Worker cancelled, shutting down")
