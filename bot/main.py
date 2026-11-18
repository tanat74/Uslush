"""Entry point for the Telegram Transcription Bot.

Reads configuration from environment variables, initialises all components
and starts the bot in polling or webhook mode.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from telegram.ext import Application, ApplicationBuilder

from bot.config import load_config
from bot.handlers import register_handlers
from bot.gigaam import GigaAMClient
from bot.queue import DeduplicationQueue
from bot.whisper import WhisperClient
from bot.worker import run_worker

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
HEARTBEAT_INTERVAL_SEC = 30.0
HEARTBEAT_PATH = Path(
    os.environ.get(
        "HEARTBEAT_PATH",
        str(Path(tempfile.gettempdir()) / "uslush-heartbeat"),
    )
)

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
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


def _on_worker_done(task: asyncio.Task) -> None:
    """Log if the worker exits for any reason other than cancellation."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Transcription worker died: %s", exc, exc_info=exc)


async def _run_heartbeat(worker_task: asyncio.Task) -> None:
    """Touch a heartbeat file while the transcription worker is alive."""
    try:
        while True:
            if worker_task.done():
                logger.error("Worker task is no longer running, stopping heartbeat")
                return
            HEARTBEAT_PATH.touch()
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
    except asyncio.CancelledError:
        raise


def main() -> None:
    config = load_config()
    _install_token_redaction(config.bot_token)

    queue = DeduplicationQueue()
    if config.asr_backend == "gigaam":
        client = GigaAMClient(config.gigaam_base_url, config.gigaam_model,
                              config.gigaam_api_key, config.gigaam_timeout)
    else:
        client = WhisperClient(config.wyoming_host, config.wyoming_port, config.whisper_language,
                               ffmpeg_timeout=config.ffmpeg_timeout, wyoming_timeout=config.wyoming_timeout)
    worker_task: asyncio.Task | None = None
    heartbeat_task: asyncio.Task | None = None

    async def post_init(app: Application) -> None:
        nonlocal worker_task, heartbeat_task
        worker_task = asyncio.create_task(
            run_worker(queue, client, app.bot),
            name="transcription_worker",
        )
        worker_task.add_done_callback(_on_worker_done)
        heartbeat_task = asyncio.create_task(
            _run_heartbeat(worker_task),
            name="worker_heartbeat",
        )
        logger.info("Transcription worker started")

    async def post_shutdown(app: Application) -> None:
        for task in (heartbeat_task, worker_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
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

    register_handlers(application, queue, config.allowed_user_ids)

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
        logger.info("Starting in polling mode (poll_interval=%.1fs)", config.poll_interval)
        application.run_polling(poll_interval=config.poll_interval)


if __name__ == "__main__":
    main()
