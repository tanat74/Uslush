"""Telegram message handlers for voice, video_note and video messages."""

import logging

from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from bot.queue import DeduplicationQueue, TranscriptionTask

logger = logging.getLogger(__name__)

# Telegram Bot API getFile rejects downloads above 20 MB.
TELEGRAM_DOWNLOAD_LIMIT = 20 * 1024 * 1024
MSG_FILE_TOO_BIG = "Файл больше 20 МБ, сожмите или обрежьте."
MSG_REPLACED = "Предыдущее необработанное сообщение заменено этим."
MSG_ACCESS_DENIED = "Доступ запрещён."


def _is_too_big(file_size: int | None) -> bool:
    return file_size is not None and file_size > TELEGRAM_DOWNLOAD_LIMIT


async def _enqueue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    file_id: str,
    file_size: int | None,
    media_type: str,
) -> None:
    """Reject oversized media, otherwise put a transcription task on the queue."""
    msg: Message | None = update.effective_message
    if msg is None:
        return

    user = update.effective_user
    if user is None:
        logger.warning("Ignoring %s without effective_user", media_type)
        return

    allowed: frozenset[int] = context.bot_data.get("allowed_user_ids", frozenset())
    if allowed and user.id not in allowed:
        await msg.reply_text(MSG_ACCESS_DENIED)
        logger.warning(
            "Rejected %s from unauthorized user %s",
            media_type,
            user.id,
        )
        return

    if _is_too_big(file_size):
        await msg.reply_text(MSG_FILE_TOO_BIG)
        logger.info(
            "Rejected %s for user %s: %s bytes exceeds Bot API download limit",
            media_type,
            user.id,
            file_size,
        )
        return

    queue: DeduplicationQueue = context.bot_data["queue"]
    task = TranscriptionTask(
        user_id=user.id,
        chat_id=update.effective_chat.id,
        file_id=file_id,
        media_type=media_type,
        message_id=msg.message_id,
    )
    replaced = await queue.put(task)
    logger.debug("Queued %s task for user %s", media_type, task.user_id)

    if replaced:
        await msg.reply_text(MSG_REPLACED)

    try:
        await context.bot.send_chat_action(
            chat_id=task.chat_id,
            action=ChatAction.TYPING,
        )
    except Exception:
        logger.debug("Failed to send typing action for user %s", task.user_id)


async def _handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming voice message."""
    voice = update.effective_message.voice
    await _enqueue(
        update,
        context,
        file_id=voice.file_id,
        file_size=voice.file_size,
        media_type="voice",
    )


async def _handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming video note (circle video)."""
    video_note = update.effective_message.video_note
    await _enqueue(
        update,
        context,
        file_id=video_note.file_id,
        file_size=video_note.file_size,
        media_type="video_note",
    )


async def _handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming video message."""
    video = update.effective_message.video
    await _enqueue(
        update,
        context,
        file_id=video.file_id,
        file_size=video.file_size,
        media_type="video",
    )


def register_handlers(
    application: Application,
    queue: DeduplicationQueue,
    allowed_user_ids: frozenset[int] = frozenset(),
) -> None:
    """Register all media message handlers with the application.

    Args:
        application: The python-telegram-bot Application instance.
        queue: The shared DeduplicationQueue instance.
        allowed_user_ids: Telegram user IDs allowed to use the bot.
            An empty set means everyone is allowed.
    """
    application.bot_data["queue"] = queue
    application.bot_data["allowed_user_ids"] = allowed_user_ids

    application.add_handler(MessageHandler(filters.VOICE, _handle_voice))
    application.add_handler(MessageHandler(filters.VIDEO_NOTE, _handle_video_note))
    application.add_handler(MessageHandler(filters.VIDEO, _handle_video))
