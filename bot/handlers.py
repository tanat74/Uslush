"""Telegram message handlers for voice, video_note and video messages."""

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from bot.queue import DeduplicationQueue, TranscriptionTask

logger = logging.getLogger(__name__)


async def _handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming voice message."""
    queue: DeduplicationQueue = context.bot_data["queue"]
    msg = update.effective_message
    task = TranscriptionTask(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        file_id=msg.voice.file_id,
        media_type="voice",
        message_id=msg.message_id,
    )
    await queue.put(task)
    logger.debug("Queued voice task for user %s", task.user_id)


async def _handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming video note (circle video)."""
    queue: DeduplicationQueue = context.bot_data["queue"]
    msg = update.effective_message
    task = TranscriptionTask(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        file_id=msg.video_note.file_id,
        media_type="video_note",
        message_id=msg.message_id,
    )
    await queue.put(task)
    logger.debug("Queued video_note task for user %s", task.user_id)


async def _handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming video message."""
    queue: DeduplicationQueue = context.bot_data["queue"]
    msg = update.effective_message
    task = TranscriptionTask(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        file_id=msg.video.file_id,
        media_type="video",
        message_id=msg.message_id,
    )
    await queue.put(task)
    logger.debug("Queued video task for user %s", task.user_id)


def register_handlers(application: Application, queue: DeduplicationQueue) -> None:
    """Register all media message handlers with the application.

    Args:
        application: The python-telegram-bot Application instance.
        queue: The shared DeduplicationQueue instance.
    """
    application.bot_data["queue"] = queue

    application.add_handler(MessageHandler(filters.VOICE, _handle_voice))
    application.add_handler(MessageHandler(filters.VIDEO_NOTE, _handle_video_note))
    application.add_handler(MessageHandler(filters.VIDEO, _handle_video))
