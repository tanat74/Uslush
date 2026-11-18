"""Unit tests for bot/worker.py — run_worker."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from telegram.constants import ChatAction
from telegram.error import RetryAfter

from bot.queue import DeduplicationQueue, TranscriptionTask
from bot.whisper import AsrUnavailableError, AudioTooLongError, TranscriptionTimeoutError
from bot.worker import (
    MSG_EMPTY,
    MSG_START,
    MSG_PARTIAL,
    MSG_ERROR,
    MSG_TIMEOUT,
    MSG_TOO_LONG,
    MSG_UNAVAILABLE,
    TELEGRAM_MESSAGE_LIMIT,
    run_worker,
    split_message,
)


def assert_single_reply(bot, text):
    bot.send_message.assert_awaited_once_with(chat_id=100, text=MSG_START, reply_to_message_id=1)
    bot.edit_message_text.assert_awaited_once_with(
        chat_id=100, message_id=bot.send_message.return_value.message_id, text=text
    )


def make_task(user_id: int = 1, chat_id: int = 100, file_id: str = "fid") -> TranscriptionTask:
    return TranscriptionTask(
        user_id=user_id,
        chat_id=chat_id,
        file_id=file_id,
        media_type="voice",
        message_id=1,
    )


async def run_worker_once(queue, whisper_client, bot) -> asyncio.Task:
    """Run worker long enough to process pending work then cancel it."""
    worker_task = asyncio.create_task(run_worker(queue, whisper_client, bot))
    await asyncio.sleep(0.05)
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    return worker_task


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
    bot.send_chat_action = AsyncMock()

    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(return_value="Привет мир")

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    assert_single_reply(bot, "Привет мир")
    bot.send_chat_action.assert_awaited_with(chat_id=100, action=ChatAction.TYPING)


@pytest.mark.asyncio
async def test_worker_splits_long_transcription_and_replies_to_original_message():
    queue = DeduplicationQueue()
    task = make_task()
    task.message_id = 77

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))
    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    bot.send_chat_action = AsyncMock()
    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(return_value="слово " * 1000)

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    assert bot.send_message.await_count == 2
    first = bot.edit_message_text.await_args.kwargs["text"]
    second = bot.send_message.await_args.kwargs["text"]
    assert f"{first} {second}".strip() == ("слово " * 1000).strip()
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
    bot.send_chat_action = AsyncMock()

    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(return_value="   ")

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    assert_single_reply(bot, MSG_EMPTY)


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
    bot.send_chat_action = AsyncMock()

    whisper = AsyncMock()

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    assert_single_reply(bot, MSG_ERROR)


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
    bot.send_chat_action = AsyncMock()

    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(side_effect=RuntimeError("Bridge down"))

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    assert_single_reply(bot, MSG_ERROR)


@pytest.mark.asyncio
async def test_worker_sends_too_long_message_on_long_audio_failure():
    queue = DeduplicationQueue()
    task = make_task()

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))

    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    bot.send_message = AsyncMock()
    bot.send_chat_action = AsyncMock()

    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(side_effect=AudioTooLongError("too long"))

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    assert_single_reply(bot, MSG_TOO_LONG)


@pytest.mark.asyncio
async def test_worker_sends_timeout_message():
    queue = DeduplicationQueue()
    task = make_task()

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))
    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    bot.send_chat_action = AsyncMock()
    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(side_effect=TranscriptionTimeoutError("slow"))

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    assert_single_reply(bot, MSG_TIMEOUT)


@pytest.mark.asyncio
async def test_worker_sends_unavailable_message():
    queue = DeduplicationQueue()
    task = make_task()

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))
    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    bot.send_chat_action = AsyncMock()
    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(side_effect=AsrUnavailableError("down"))

    await queue.put(task)
    await run_worker_once(queue, whisper, bot)

    assert_single_reply(bot, MSG_UNAVAILABLE)


@pytest.mark.asyncio
async def test_worker_survives_get_failure_and_processes_next_task():
    queue = DeduplicationQueue()
    good_task = make_task(file_id="ok")

    original_get = queue.get
    calls = {"n": 0}

    async def flaky_get():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("signal desync")
        return await original_get()

    queue.get = flaky_get  # type: ignore[method-assign]

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"audio"))
    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    bot.send_chat_action = AsyncMock()
    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(return_value="ок")

    await queue.put(good_task)
    worker_task = await run_worker_once(queue, whisper, bot)

    assert worker_task.cancelled() or worker_task.done()
    assert_single_reply(bot, "ок")
    assert calls["n"] >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_worker_shows_partial_before_stream_finishes(interrupted):
    queue = DeduplicationQueue()
    await queue.put(make_task())
    visible, finished = asyncio.Event(), asyncio.Event()
    bot, client = AsyncMock(), AsyncMock()
    bot.get_file.return_value.download_as_bytearray.return_value = b"audio"
    edits = []

    async def edit(*, text, **kwargs):
        edits.append(text)
        if len(edits) == 1:
            raise RetryAfter(0)
        (visible if text == "Привет" else finished).set()

    async def recognize(data, media, on_delta):
        on_delta("Привет")
        await visible.wait()
        on_delta(" мир")
        if interrupted:
            raise RuntimeError("disconnected")
        return "Привет, мир!"

    bot.edit_message_text.side_effect = edit
    client.transcribe.side_effect = recognize
    worker = asyncio.create_task(run_worker(queue, client, bot))
    try:
        await asyncio.wait_for(finished.wait(), 2)
        assert edits[-1] == ("Привет мир\n\n" + MSG_PARTIAL if interrupted else "Привет, мир!")
        assert bot.send_message.await_count == 1
    finally:
        worker.cancel()
        await worker
