"""Unit tests for bot/handlers.py."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.constants import ChatAction

from bot.handlers import (
    MSG_ACCESS_DENIED,
    MSG_FILE_TOO_BIG,
    MSG_REPLACED,
    TELEGRAM_DOWNLOAD_LIMIT,
    _handle_audio_file,
    _handle_video,
    _handle_video_note,
    _handle_voice,
)
from bot.queue import DeduplicationQueue


def make_update(
    user_id: int | None,
    chat_id: int,
    file_id: str,
    media_type: str,
    file_size: int | None = 1024,
):
    """Build a minimal mock Update object for a given media type."""
    update = MagicMock()
    if user_id is None:
        update.effective_user = None
    else:
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


def make_context(queue: DeduplicationQueue, allowed_user_ids: frozenset[int] = frozenset()):
    """Build a minimal mock Context with bot_data containing the queue."""
    context = MagicMock()
    context.bot_data = {"queue": queue, "allowed_user_ids": allowed_user_ids}
    context.bot.send_chat_action = AsyncMock()
    return context


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,name,mime,expected", [
    ("audio", "запись.m4a", "audio/mp4", "m4a"),
    ("document", "запись.M4A", "application/octet-stream", "m4a"),
    ("document", None, "audio/x-m4a", "m4a"),
    ("audio", "запись.mp3", "audio/mpeg", "attachment"),
    ("document", "recording.webm", "application/octet-stream", "attachment"),
    ("document", None, None, "attachment"),
    ("document", "notes.pdf", "application/pdf", "attachment"),
])
async def test_audio_attachment(kind, name, mime, expected):
    queue = DeduplicationQueue()
    update = make_update(1, 100, "recording", kind)
    msg = update.effective_message
    msg.audio = msg.document = None
    setattr(msg, kind, MagicMock(file_id="recording", file_size=123, file_name=name, mime_type=mime))
    await _handle_audio_file(update, make_context(queue))
    task = queue._deque[0]
    assert (task.file_id, task.media_type) == ("recording", expected)


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
    context.bot.send_chat_action.assert_awaited_once_with(
        chat_id=100, action=ChatAction.TYPING
    )
    update.effective_message.reply_text.assert_not_awaited()


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
    context.bot.send_chat_action.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_voice_handler_notifies_when_previous_task_is_replaced():
    queue = DeduplicationQueue()
    context = make_context(queue)
    first = make_update(user_id=1, chat_id=100, file_id="old", media_type="voice")
    second = make_update(user_id=1, chat_id=100, file_id="new", media_type="voice")

    await _handle_voice(first, context)
    await _handle_voice(second, context)

    first.effective_message.reply_text.assert_not_awaited()
    second.effective_message.reply_text.assert_awaited_once_with(MSG_REPLACED)
    task = await queue.get()
    assert task.file_id == "new"


@pytest.mark.asyncio
async def test_voice_handler_rejects_unauthorized_user():
    queue = DeduplicationQueue()
    update = make_update(user_id=99, chat_id=100, file_id="voice", media_type="voice")
    context = make_context(queue, allowed_user_ids=frozenset({1}))

    await _handle_voice(update, context)

    assert not queue._deque
    update.effective_message.reply_text.assert_awaited_once_with(MSG_ACCESS_DENIED)
    context.bot.send_chat_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_handler_allows_listed_user():
    queue = DeduplicationQueue()
    update = make_update(user_id=1, chat_id=100, file_id="voice", media_type="voice")
    context = make_context(queue, allowed_user_ids=frozenset({1, 2}))

    await _handle_voice(update, context)

    task = await queue.get()
    assert task.user_id == 1
    update.effective_message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_handler_ignores_missing_effective_user():
    queue = DeduplicationQueue()
    update = make_update(user_id=None, chat_id=100, file_id="voice", media_type="voice")
    context = make_context(queue)

    await _handle_voice(update, context)

    assert not queue._deque
    update.effective_message.reply_text.assert_not_awaited()
    context.bot.send_chat_action.assert_not_awaited()
