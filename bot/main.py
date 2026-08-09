"""Entry point for the Telegram Transcription Bot.

Reads configuration from environment variables, initialises all components
and starts the bot in polling or webhook mode.
"""

import asyncio
import logging

from telegram.ext import Application, ApplicationBuilder

from bot.config import load_config
from bot.handlers import register_handlers
from bot.queue import DeduplicationQueue
from bot.whisper import WhisperClient
from bot.worker import run_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()

    queue = DeduplicationQueue()
    whisper_client = WhisperClient(
        config.wyoming_host,
        config.wyoming_port,
        config.whisper_language,
    )
    worker_task: asyncio.Task | None = None

    async def post_init(app: Application) -> None:
        nonlocal worker_task
        worker_task = asyncio.create_task(
            run_worker(queue, whisper_client, app.bot),
            name="transcription_worker",
        )
        logger.info("Transcription worker started")

    async def post_shutdown(app: Application) -> None:
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            logger.info("Transcription worker stopped")

    application: Application = (
        ApplicationBuilder()
        .token(config.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    register_handlers(application, queue)

    if config.bot_mode == "webhook":
        logger.info(
            "Starting in webhook mode: %s on port %d",
            config.webhook_url,
            config.webhook_port,
        )
        application.run_webhook(
            listen="0.0.0.0",
            port=config.webhook_port,
            webhook_url=config.webhook_url,
        )
    else:
        logger.info("Starting in polling mode")
        application.run_polling()


if __name__ == "__main__":
    main()
