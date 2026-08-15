"""Unit tests for bot/handlers.py."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers import (
    MSG_FILE_TOO_BIG,
    TELEGRAM_DOWNLOAD_LIMIT,
    _handle_video,
    _handle_video_note,
    _handle_voice,
)
from bot.queue import DeduplicationQueue


def make_update(
    user_id: int,
    chat_id: int,
    file_id: str,
    media_type: str,
    file_size: int | None = 1024,
):
    """Build a minimal mock Update object for a given media type."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.effective_message.message_id = 42
    update.effective_message.reply_text = AsyncMock()

    if media_type == "voice":
        update.effective_message.voice.file_id = file_id
        update.effective_message.voice.file_size = file_size
    elif media_type == "video_note":
        update.effective_message.video_note.file_id = file_id
        update.effective_message.video_note.file_size = file_size
    elif media_type == "video":
        update.effective_message.video.file_id = file_id
        update.effective_message.video.file_size = file_size

    return update


def make_context(queue: DeduplicationQueue):
    """Build a minimal mock Context with bot_data containing the queue."""
    context = MagicMock()
    context.bot_data = {"queue": queue}
    return context


# ---------------------------------------------------------------------------
# voice handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_handler_puts_task():
    """voice message → task with media_type='voice' is put into queue."""
    queue = DeduplicationQueue()
    update = make_update(user_id=1, chat_id=100, file_id="voice_file_id", media_type="voice")
    context = make_context(queue)

    await _handle_voice(update, context)

    task = await queue.get()
    assert task.media_type == "voice"
    assert task.file_id == "voice_file_id"
    assert task.user_id == 1
    assert task.chat_id == 100


# ---------------------------------------------------------------------------
# video_note handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_note_handler_puts_task():
    """video_note message → task with media_type='video_note' is put into queue."""
    queue = DeduplicationQueue()
    update = make_update(user_id=2, chat_id=200, file_id="vnote_file_id", media_type="video_note")
    context = make_context(queue)

    await _handle_video_note(update, context)

    task = await queue.get()
    assert task.media_type == "video_note"
    assert task.file_id == "vnote_file_id"
    assert task.user_id == 2
    assert task.chat_id == 200


# ---------------------------------------------------------------------------
# video handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_handler_puts_task():
    """video message → task with media_type='video' is put into queue."""
    queue = DeduplicationQueue()
    update = make_update(user_id=3, chat_id=300, file_id="video_file_id", media_type="video")
    context = make_context(queue)

    await _handle_video(update, context)

    task = await queue.get()
    assert task.media_type == "video"
    assert task.file_id == "video_file_id"
    assert task.user_id == 3
    assert task.chat_id == 300
    update.effective_message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_handler_rejects_file_over_20mb():
    """Video larger than the Bot API download limit is not queued."""
    queue = DeduplicationQueue()
    update = make_update(
        user_id=3,
        chat_id=300,
        file_id="huge_video",
        media_type="video",
        file_size=TELEGRAM_DOWNLOAD_LIMIT + 1,
    )
    context = make_context(queue)

    await _handle_video(update, context)

    assert not queue._deque
    update.effective_message.reply_text.assert_awaited_once_with(MSG_FILE_TOO_BIG)


@pytest.mark.asyncio
async def test_video_handler_accepts_file_at_20mb_limit():
    """A file of exactly 20 MB is still within the Bot API download limit."""
    queue = DeduplicationQueue()
    update = make_update(
        user_id=3,
        chat_id=300,
        file_id="limit_video",
        media_type="video",
        file_size=TELEGRAM_DOWNLOAD_LIMIT,
    )
    context = make_context(queue)

    await _handle_video(update, context)

    task = await queue.get()
    assert task.file_id == "limit_video"
    update.effective_message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_handler_queues_when_file_size_unknown():
    """Missing file_size is not treated as oversized."""
    queue = DeduplicationQueue()
    update = make_update(
        user_id=3,
        chat_id=300,
        file_id="unknown_size",
        media_type="video",
        file_size=None,
    )
    context = make_context(queue)

    await _handle_video(update, context)

    task = await queue.get()
    assert task.file_id == "unknown_size"


@pytest.mark.asyncio
async def test_voice_handler_rejects_file_over_20mb():
    queue = DeduplicationQueue()
    update = make_update(
        user_id=1,
        chat_id=100,
        file_id="huge_voice",
        media_type="voice",
        file_size=TELEGRAM_DOWNLOAD_LIMIT + 1,
    )
    context = make_context(queue)

    await _handle_voice(update, context)

    assert not queue._deque
    update.effective_message.reply_text.assert_awaited_once_with(MSG_FILE_TOO_BIG)


# ---------------------------------------------------------------------------
# task fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_has_correct_message_id():
    """Task carries the correct message_id from the update."""
    queue = DeduplicationQueue()
    update = make_update(user_id=5, chat_id=500, file_id="f1", media_type="voice")
    update.effective_message.message_id = 99
    context = make_context(queue)

    await _handle_voice(update, context)

    task = await queue.get()
    assert task.message_id == 99
