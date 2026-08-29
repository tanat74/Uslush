"""Unit tests for bot/config.py — Config dataclass and load_config()."""

import pytest

from bot.config import Config, load_config


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

BASE_ENV = {
    "BOT_TOKEN": "test-token-123",
    "WYOMING_HOST": "wyoming.example",
}


def _apply_base(monkeypatch) -> None:
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    for key in (
        "BOT_MODE",
        "WEBHOOK_URL",
        "WEBHOOK_PORT",
        "POLL_INTERVAL",
        "WYOMING_PORT",
        "WHISPER_LANGUAGE",
        "ALLOWED_USER_IDS",
        "FFMPEG_TIMEOUT",
        "WYOMING_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Successful load
# ---------------------------------------------------------------------------


def test_load_config_success(monkeypatch):
    """load_config() returns a Config with all required fields set."""
    _apply_base(monkeypatch)

    cfg = load_config()

    assert isinstance(cfg, Config)
    assert cfg.bot_token == "test-token-123"
    assert "test-token-123" not in repr(cfg)
    assert cfg.wyoming_host == "wyoming.example"
    assert cfg.wyoming_port == 10300
    assert cfg.whisper_language == "ru"
    assert cfg.poll_interval == 60.0
    assert cfg.allowed_user_ids == frozenset()
    assert cfg.ffmpeg_timeout == 120.0
    assert cfg.wyoming_timeout == 300.0


def test_load_config_custom_wyoming(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token-123")
    monkeypatch.setenv("WYOMING_HOST", "wyoming.example")
    monkeypatch.setenv("WYOMING_PORT", "12000")
    monkeypatch.setenv("WHISPER_LANGUAGE", "en")

    cfg = load_config()

    assert cfg.wyoming_host == "wyoming.example"
    assert cfg.wyoming_port == 12000
    assert cfg.whisper_language == "en"


def test_load_config_invalid_wyoming_port(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token-123")
    monkeypatch.setenv("WYOMING_HOST", "wyoming.example")
    monkeypatch.setenv("WYOMING_PORT", "not-a-number")

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_missing_wyoming_host(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token-123")
    monkeypatch.delenv("WYOMING_HOST", raising=False)

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_empty_wyoming_host(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token-123")
    monkeypatch.setenv("WYOMING_HOST", "   ")

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_default_bot_mode(monkeypatch):
    """BOT_MODE defaults to 'polling' when not set."""
    _apply_base(monkeypatch)

    cfg = load_config()

    assert cfg.bot_mode == "polling"


def test_load_config_invalid_bot_mode(monkeypatch):
    _apply_base(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "poll")

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_default_webhook_port(monkeypatch):
    """WEBHOOK_PORT defaults to 8443 when not set."""
    _apply_base(monkeypatch)

    cfg = load_config()

    assert cfg.webhook_port == 8443


# ---------------------------------------------------------------------------
# Missing / empty required variables
# ---------------------------------------------------------------------------


def test_load_config_missing_bot_token(monkeypatch):
    """SystemExit is raised when BOT_TOKEN is absent."""
    monkeypatch.setenv("WYOMING_HOST", "wyoming.example")
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_empty_bot_token(monkeypatch):
    """SystemExit is raised when BOT_TOKEN is an empty string."""
    monkeypatch.setenv("BOT_TOKEN", "   ")
    monkeypatch.setenv("WYOMING_HOST", "wyoming.example")

    with pytest.raises(SystemExit):
        load_config()


# ---------------------------------------------------------------------------
# Webhook mode validation
# ---------------------------------------------------------------------------


def test_load_config_webhook_mode_requires_webhook_url(monkeypatch):
    """SystemExit is raised when BOT_MODE=webhook but WEBHOOK_URL is absent."""
    _apply_base(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_webhook_mode_empty_webhook_url(monkeypatch):
    """SystemExit is raised when BOT_MODE=webhook and WEBHOOK_URL is empty."""
    _apply_base(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("WEBHOOK_URL", "   ")

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_webhook_mode_success(monkeypatch):
    """load_config() succeeds for BOT_MODE=webhook with all required vars."""
    _apply_base(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("WEBHOOK_URL", "https://example.com/bot")
    monkeypatch.setenv("WEBHOOK_PORT", "8443")

    cfg = load_config()

    assert cfg.bot_mode == "webhook"
    assert cfg.webhook_url == "https://example.com/bot"
    assert cfg.webhook_port == 8443


def test_load_config_polling_mode_no_webhook_url_required(monkeypatch):
    """WEBHOOK_URL is not required in polling mode."""
    _apply_base(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "polling")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)

    cfg = load_config()

    assert cfg.bot_mode == "polling"
    assert cfg.webhook_url == ""


# ---------------------------------------------------------------------------
# webhook_port type coercion
# ---------------------------------------------------------------------------


def test_load_config_custom_webhook_port(monkeypatch):
    """WEBHOOK_PORT is parsed as an integer."""
    _apply_base(monkeypatch)
    monkeypatch.setenv("WEBHOOK_PORT", "9000")

    cfg = load_config()

    assert cfg.webhook_port == 9000


def test_load_config_invalid_webhook_port(monkeypatch):
    """SystemExit is raised when WEBHOOK_PORT is not a valid integer."""
    _apply_base(monkeypatch)
    monkeypatch.setenv("WEBHOOK_PORT", "not-a-number")

    with pytest.raises(SystemExit):
        load_config()


# ---------------------------------------------------------------------------
# POLL_INTERVAL
# ---------------------------------------------------------------------------


def test_load_config_default_poll_interval(monkeypatch):
    """POLL_INTERVAL defaults to 60 seconds when not set."""
    _apply_base(monkeypatch)

    cfg = load_config()

    assert cfg.poll_interval == 60.0


def test_load_config_custom_poll_interval(monkeypatch):
    """POLL_INTERVAL is parsed as a float."""
    _apply_base(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL", "15.5")

    cfg = load_config()

    assert cfg.poll_interval == 15.5


def test_load_config_invalid_poll_interval(monkeypatch):
    """SystemExit is raised when POLL_INTERVAL is not a number."""
    _apply_base(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL", "not-a-number")

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_negative_poll_interval(monkeypatch):
    """SystemExit is raised when POLL_INTERVAL is negative."""
    _apply_base(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL", "-1")

    with pytest.raises(SystemExit):
        load_config()


# ---------------------------------------------------------------------------
# ALLOWED_USER_IDS and timeouts
# ---------------------------------------------------------------------------


def test_load_config_allowed_user_ids(monkeypatch):
    _apply_base(monkeypatch)
    monkeypatch.setenv("ALLOWED_USER_IDS", "11, 22, 22, 33")

    cfg = load_config()

    assert cfg.allowed_user_ids == frozenset({11, 22, 33})


def test_load_config_invalid_allowed_user_ids(monkeypatch):
    _apply_base(monkeypatch)
    monkeypatch.setenv("ALLOWED_USER_IDS", "11, not-an-id")

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_custom_timeouts(monkeypatch):
    _apply_base(monkeypatch)
    monkeypatch.setenv("FFMPEG_TIMEOUT", "15")
    monkeypatch.setenv("WYOMING_TIMEOUT", "45.5")

    cfg = load_config()

    assert cfg.ffmpeg_timeout == 15.0
    assert cfg.wyoming_timeout == 45.5


def test_load_config_invalid_ffmpeg_timeout(monkeypatch):
    _apply_base(monkeypatch)
    monkeypatch.setenv("FFMPEG_TIMEOUT", "slow")

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_negative_wyoming_timeout(monkeypatch):
    _apply_base(monkeypatch)
    monkeypatch.setenv("WYOMING_TIMEOUT", "-3")

    with pytest.raises(SystemExit):
        load_config()
