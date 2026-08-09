"""Unit tests for bot/config.py — Config dataclass and load_config()."""

import pytest

from bot.config import Config, load_config


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

BASE_ENV = {
    "BOT_TOKEN": "test-token-123",
}


# ---------------------------------------------------------------------------
# Successful load
# ---------------------------------------------------------------------------


def test_load_config_success(monkeypatch):
    """load_config() returns a Config with all required fields set."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("BOT_MODE", raising=False)
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    monkeypatch.delenv("WEBHOOK_PORT", raising=False)

    cfg = load_config()

    assert isinstance(cfg, Config)
    assert cfg.bot_token == "test-token-123"


def test_load_config_default_bot_mode(monkeypatch):
    """BOT_MODE defaults to 'polling' when not set."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("BOT_MODE", raising=False)

    cfg = load_config()

    assert cfg.bot_mode == "polling"


def test_load_config_default_webhook_port(monkeypatch):
    """WEBHOOK_PORT defaults to 8443 when not set."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("WEBHOOK_PORT", raising=False)

    cfg = load_config()

    assert cfg.webhook_port == 8443


# ---------------------------------------------------------------------------
# Missing / empty required variables
# ---------------------------------------------------------------------------


def test_load_config_missing_bot_token(monkeypatch):
    """SystemExit is raised when BOT_TOKEN is absent."""
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_empty_bot_token(monkeypatch):
    """SystemExit is raised when BOT_TOKEN is an empty string."""
    monkeypatch.setenv("BOT_TOKEN", "   ")

    with pytest.raises(SystemExit):
        load_config()


# ---------------------------------------------------------------------------
# Webhook mode validation
# ---------------------------------------------------------------------------


def test_load_config_webhook_mode_requires_webhook_url(monkeypatch):
    """SystemExit is raised when BOT_MODE=webhook but WEBHOOK_URL is absent."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_webhook_mode_empty_webhook_url(monkeypatch):
    """SystemExit is raised when BOT_MODE=webhook and WEBHOOK_URL is empty."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("WEBHOOK_URL", "   ")

    with pytest.raises(SystemExit):
        load_config()


def test_load_config_webhook_mode_success(monkeypatch):
    """load_config() succeeds for BOT_MODE=webhook with all required vars."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("WEBHOOK_URL", "https://example.com/bot")
    monkeypatch.setenv("WEBHOOK_PORT", "8443")

    cfg = load_config()

    assert cfg.bot_mode == "webhook"
    assert cfg.webhook_url == "https://example.com/bot"
    assert cfg.webhook_port == 8443


def test_load_config_polling_mode_no_webhook_url_required(monkeypatch):
    """WEBHOOK_URL is not required in polling mode."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
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
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("WEBHOOK_PORT", "9000")

    cfg = load_config()

    assert cfg.webhook_port == 9000


def test_load_config_invalid_webhook_port(monkeypatch):
    """SystemExit is raised when WEBHOOK_PORT is not a valid integer."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("WEBHOOK_PORT", "not-a-number")

    with pytest.raises(SystemExit):
        load_config()
