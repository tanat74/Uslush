"""Entry point for the Telegram Transcription Bot.

Reads configuration from environment variables, initialises all components
and starts the bot in polling or webhook mode.
"""

import asyncio
import logging
from urllib.parse import quote

from telegram.ext import Application, ApplicationBuilder

from bot.config import load_config
from bot.handlers import register_handlers
from bot.queue import DeduplicationQueue
from bot.whisper import WhisperClient
from bot.worker import run_worker

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
)
logger = logging.getLogger(__name__)


class _TokenRedactingFormatter(logging.Formatter):
    """Strip the bot token from log output, including exception tracebacks."""

    def __init__(self, token: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._secrets = [token]
        encoded = quote(token, safe="")
        if encoded != token:
            self._secrets.append(encoded)

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        for secret in self._secrets:
            formatted = formatted.replace(secret, "[REDACTED]")
        return formatted


def _install_token_redaction(token: str) -> None:
    """Rewrite root handlers so the bot token never appears in log lines."""
    formatter = _TokenRedactingFormatter(token, fmt=LOG_FORMAT)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)


def main() -> None:
    config = load_config()
    _install_token_redaction(config.bot_token)

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
