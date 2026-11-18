"""Configuration module for the Telegram Transcription Bot.

Reads and validates environment variables at startup. Exits with a
descriptive error message if required variables are missing.
"""

import os
import sys
from dataclasses import dataclass, field

VALID_BOT_MODES = frozenset({"polling", "webhook"})


@dataclass
class Config:
    bot_token: str = field(repr=False)  # BOT_TOKEN (required); omitted from repr/logs
    bot_mode: str         # BOT_MODE: "polling" | "webhook" (default: "polling")
    webhook_url: str      # WEBHOOK_URL (required when bot_mode="webhook")
    webhook_port: int     # WEBHOOK_PORT (default: 8443)
    poll_interval: float  # POLL_INTERVAL seconds between getUpdates (default: 60)
    allowed_user_ids: frozenset[int]  # ALLOWED_USER_IDS; empty means allow everyone
    gigaam_base_url: str
    gigaam_model: str
    gigaam_api_key: str = field(repr=False)
    gigaam_timeout: float


def _die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        _die(f"{name} environment variable is not set or empty.")
    return value


def _parse_int(name: str, default: str) -> int:
    raw = os.environ.get(name, default).strip()
    try:
        return int(raw)
    except ValueError:
        _die(f"{name} must be an integer, got: {raw!r}")
        raise  # unreachable; keeps type checkers happy


def _parse_float(name: str, default: str, *, minimum: float | None = None) -> float:
    raw = os.environ.get(name, default).strip()
    try:
        value = float(raw)
    except ValueError:
        _die(f"{name} must be a number, got: {raw!r}")
        raise
    if minimum is not None and value < minimum:
        _die(f"{name} must be >= {minimum}, got: {value}")
    return value


def _parse_allowed_user_ids() -> frozenset[int]:
    raw = os.environ.get("ALLOWED_USER_IDS", "").strip()
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            _die(
                "ALLOWED_USER_IDS must be comma-separated integers, "
                f"got: {part!r}"
            )
    return frozenset(ids)


def load_config() -> Config:
    """Load and validate configuration from environment variables.

    Returns:
        Config: Validated configuration object.

    Raises:
        SystemExit: If required environment variables are missing.
    """
    bot_token = _require("BOT_TOKEN")

    bot_mode = os.environ.get("BOT_MODE", "polling").strip()
    if bot_mode not in VALID_BOT_MODES:
        _die(
            "BOT_MODE must be one of "
            f"{', '.join(sorted(VALID_BOT_MODES))}, got: {bot_mode!r}"
        )

    webhook_url = os.environ.get("WEBHOOK_URL", "").strip()
    if bot_mode == "webhook" and not webhook_url:
        _die("WEBHOOK_URL environment variable is required when BOT_MODE=webhook.")

    webhook_port = _parse_int("WEBHOOK_PORT", "8443")
    gigaam_url = _require("GIGAAM_BASE_URL")
    if not gigaam_url.startswith(("http://", "https://")):
        _die("GIGAAM_BASE_URL must start with http:// or https://.")
    poll_interval = _parse_float("POLL_INTERVAL", "60", minimum=0)

    return Config(
        gigaam_base_url=gigaam_url,
        gigaam_model=os.environ.get("GIGAAM_MODEL", "gigaam-v3-e2e-rnnt"),
        gigaam_api_key=os.environ.get("GIGAAM_API_KEY", "").strip(),
        gigaam_timeout=_parse_float("GIGAAM_TIMEOUT", "300", minimum=0),
        bot_token=bot_token,
        bot_mode=bot_mode,
        webhook_url=webhook_url,
        webhook_port=webhook_port,
        poll_interval=poll_interval,
        allowed_user_ids=_parse_allowed_user_ids(),
    )
