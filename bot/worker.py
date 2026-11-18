"""Async worker that processes the transcription queue."""

import asyncio
import logging

from telegram.constants import ChatAction
from telegram.error import RetryAfter

from bot.queue import DeduplicationQueue, TranscriptionTask
from bot.gigaam import AsrUnavailableError, GigaAMClient, TranscriptionTimeoutError

logger = logging.getLogger(__name__)

MSG_EMPTY = "Речь не распознана."
MSG_START = "Распознаю…"
MSG_PARTIAL = "Распознавание прервано, показана только часть текста."
EDIT_INTERVAL = 2.0
MSG_ERROR = "Ошибка при транскрипции. Попробуйте ещё раз."
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


class ProgressiveReply:
    """One writer for Telegram; slow edits never block SSE consumption."""

    def __init__(self, bot, task):
        self.bot = bot
        self.task = task
        self.text = ""
        self.messages = []
        self.changed = asyncio.Event()
        self.finished = asyncio.Event()

    def append(self, delta: str):
        self.text += delta
        if self.text.strip():
            self.changed.set()

    def finish(self, text: str):
        self.text = text
        self.finished.set()
        self.changed.set()

    async def render(self, text: str):
        chunks = split_message(text)
        for i, chunk in enumerate(chunks):
            if i == len(self.messages):
                msg = await self.bot.send_message(chat_id=self.task.chat_id, text=chunk,
                                                  reply_to_message_id=self.task.message_id)
                self.messages.append((msg.message_id, chunk))
            elif self.messages[i][1] != chunk:
                mid = self.messages[i][0]
                await self.bot.edit_message_text(chat_id=self.task.chat_id, message_id=mid, text=chunk)
                self.messages[i] = (mid, chunk)
        while len(self.messages) > len(chunks):
            await self.bot.delete_message(chat_id=self.task.chat_id, message_id=self.messages[-1][0])
            self.messages.pop()

    async def run(self):
        initial = True
        while True:
            if not initial:
                await self.changed.wait()
            done = self.finished.is_set() and not initial
            text = MSG_START if initial else self.text
            if not initial:
                self.changed.clear()
            try:
                await self.render(text)
            except RetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                self.changed.set()
                continue
            if done:
                return
            if not initial:
                try:
                    async with asyncio.timeout(EDIT_INTERVAL):
                        await self.finished.wait()
                except TimeoutError:
                    pass
            initial = False


async def run_worker(
    queue: DeduplicationQueue,
    client: GigaAMClient,
    bot,
) -> None:
    """Download, transcribe and progressively publish each queued recording."""
    logger.info("Worker started")
    try:
        while True:
            task = None
            typing_task: asyncio.Task | None = None
            writer = None
            try:
                task = await queue.get()
                reply = ProgressiveReply(bot, task)
                writer = asyncio.create_task(reply.run())
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

                try:
                    tg_file = await bot.get_file(task.file_id)
                    audio_bytes = bytes(await tg_file.download_as_bytearray())
                    text = await client.transcribe(audio_bytes, task.media_type, reply.append)
                    result = text if text.strip() else MSG_EMPTY
                except Exception as exc:
                    logger.warning("Transcription failed for user %s", task.user_id, exc_info=True)
                    if reply.text.strip():
                        result = reply.text + "\n\n" + MSG_PARTIAL
                    elif isinstance(exc, TranscriptionTimeoutError):
                        result = MSG_TIMEOUT
                    elif isinstance(exc, AsrUnavailableError):
                        result = MSG_UNAVAILABLE
                    else:
                        result = MSG_ERROR
                reply.finish(result)
                await writer

            except asyncio.CancelledError:
                raise

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
                if writer is not None and not writer.done():
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)
                if typing_task is not None:
                    typing_task.cancel()
                    await asyncio.gather(typing_task, return_exceptions=True)

    except asyncio.CancelledError:
        logger.info("Worker cancelled, shutting down")
