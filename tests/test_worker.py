"""Unit tests for bot/worker.py — run_worker."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.queue import DeduplicationQueue, TranscriptionTask
from bot.worker import MSG_EMPTY, MSG_ERROR, TELEGRAM_MESSAGE_LIMIT, run_worker, split_message


def make_task(user_id: int = 1, chat_id: int = 100, file_id: str = "fid") -> TranscriptionTask:
    return TranscriptionTask(
        user_id=user_id,
        chat_id=chat_id,
        file_id=file_id,
        media_type="voice",
        message_id=1,
    )


async def run_worker_once(queue, whisper_client, bot) -> None:
    """Run worker long enough to process one task then cancel it."""
    worker_task = asyncio.create_task(run_worker(queue, whisper_client, bot))
    await asyncio.sleep(0.05)
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_sends_transcription_text():
    """Successful transcription text is sent to the user."""
    queue = DeduplicationQueue()
    task = make_task()

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))

    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    bot.send_message = AsyncMock()

    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(return_value="Привет мир")

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    bot.send_message.assert_awaited_once_with(
        chat_id=100, text="Привет мир", reply_to_message_id=1
    )


@pytest.mark.asyncio
async def test_worker_splits_long_transcription_and_replies_to_original_message():
    queue = DeduplicationQueue()
    task = make_task()
    task.message_id = 77

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))
    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(return_value="слово " * 1000)

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    assert bot.send_message.await_count == 2
    for call in bot.send_message.await_args_list:
        assert len(call.kwargs["text"]) <= TELEGRAM_MESSAGE_LIMIT
        assert call.kwargs["reply_to_message_id"] == 77


def test_split_message_hard_splits_text_without_boundaries():
    chunks = split_message("x" * (TELEGRAM_MESSAGE_LIMIT + 1))
    assert [len(chunk) for chunk in chunks] == [TELEGRAM_MESSAGE_LIMIT, 1]


# ---------------------------------------------------------------------------
# Empty transcript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_sends_empty_message_on_blank_transcript():
    """Empty transcription → MSG_EMPTY is sent."""
    queue = DeduplicationQueue()
    task = make_task()

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))

    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    bot.send_message = AsyncMock()

    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(return_value="   ")

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    bot.send_message.assert_awaited_once_with(
        chat_id=100, text=MSG_EMPTY, reply_to_message_id=1
    )


# ---------------------------------------------------------------------------
# Download error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_sends_error_on_download_failure():
    """Download error → MSG_ERROR is sent to user."""
    queue = DeduplicationQueue()
    task = make_task()

    bot = AsyncMock()
    bot.get_file = AsyncMock(side_effect=RuntimeError("Telegram error"))
    bot.send_message = AsyncMock()

    whisper = AsyncMock()

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    bot.send_message.assert_awaited_once_with(
        chat_id=100, text=MSG_ERROR, reply_to_message_id=1
    )


# ---------------------------------------------------------------------------
# Transcription error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_sends_error_on_transcribe_failure():
    """Whisper error → MSG_ERROR is sent to user."""
    queue = DeduplicationQueue()
    task = make_task()

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))

    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    bot.send_message = AsyncMock()

    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(side_effect=RuntimeError("Bridge down"))

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    bot.send_message.assert_awaited_once_with(
        chat_id=100, text=MSG_ERROR, reply_to_message_id=1
    )
