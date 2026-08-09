"""Configuration module for the Telegram Transcription Bot.

Reads and validates environment variables at startup. Exits with a
descriptive error message if required variables are missing.
"""

import os
import sys
from dataclasses import dataclass


@dataclass
class Config:
    bot_token: str        # BOT_TOKEN (required)
    bot_mode: str         # BOT_MODE: "polling" | "webhook" (default: "polling")
    webhook_url: str      # WEBHOOK_URL (required when bot_mode="webhook")
    webhook_port: int     # WEBHOOK_PORT (default: 8443)
    wyoming_host: str     # WYOMING_HOST (default: 192.168.88.12)
    wyoming_port: int     # WYOMING_PORT (default: 10305)
    whisper_language: str # WHISPER_LANGUAGE (default: ru)


def load_config() -> Config:
    """Load and validate configuration from environment variables.

    Returns:
        Config: Validated configuration object.

    Raises:
        SystemExit: If required environment variables are missing.
    """
    bot_token = os.environ.get("BOT_TOKEN", "").strip()
    if not bot_token:
        print("ERROR: BOT_TOKEN environment variable is not set or empty.", file=sys.stderr)
        raise SystemExit(1)

    bot_mode = os.environ.get("BOT_MODE", "polling").strip()

    webhook_url = os.environ.get("WEBHOOK_URL", "").strip()
    if bot_mode == "webhook" and not webhook_url:
        print(
            "ERROR: WEBHOOK_URL environment variable is required when BOT_MODE=webhook.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    webhook_port_str = os.environ.get("WEBHOOK_PORT", "8443").strip()
    try:
        webhook_port = int(webhook_port_str)
    except ValueError:
        print(
            f"ERROR: WEBHOOK_PORT must be an integer, got: {webhook_port_str!r}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    wyoming_host = os.environ.get("WYOMING_HOST", "192.168.88.12").strip()
    wyoming_port_str = os.environ.get("WYOMING_PORT", "10305").strip()
    try:
        wyoming_port = int(wyoming_port_str)
    except ValueError:
        print(
            f"ERROR: WYOMING_PORT must be an integer, got: {wyoming_port_str!r}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    whisper_language = os.environ.get("WHISPER_LANGUAGE", "ru").strip()

    return Config(
        bot_token=bot_token,
        bot_mode=bot_mode,
        webhook_url=webhook_url,
        webhook_port=webhook_port,
        wyoming_host=wyoming_host,
        wyoming_port=wyoming_port,
        whisper_language=whisper_language,
    )
