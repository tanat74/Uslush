import pytest

from bot.config import load_config


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-secret-token")
    monkeypatch.setenv("GIGAAM_BASE_URL", "http://asr:8770")
    for key in ("BOT_MODE", "WEBHOOK_URL", "WEBHOOK_PORT", "ALLOWED_USER_IDS",
                "POLL_INTERVAL", "GIGAAM_MODEL", "GIGAAM_API_KEY", "GIGAAM_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)


def test_defaults():
    cfg = load_config()
    assert cfg.bot_mode == "polling"
    assert cfg.gigaam_base_url == "http://asr:8770"
    assert cfg.gigaam_model == "gigaam-v3-e2e-rnnt"
    assert cfg.gigaam_timeout == 300
    assert cfg.poll_interval == 60
    assert cfg.webhook_port == 8443
    assert not cfg.allowed_user_ids


def test_overrides(monkeypatch):
    values = {"BOT_MODE": "webhook", "WEBHOOK_URL": "https://example.com/bot",
              "WEBHOOK_PORT": "9000", "GIGAAM_MODEL": "custom", "GIGAAM_TIMEOUT": "45.5",
              "GIGAAM_API_KEY": "secret-key", "ALLOWED_USER_IDS": "11, 22, 22",
              "POLL_INTERVAL": "2.5"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    cfg = load_config()
    assert cfg.webhook_url == values["WEBHOOK_URL"] and cfg.webhook_port == 9000
    assert cfg.gigaam_model == "custom" and cfg.gigaam_timeout == 45.5
    assert cfg.gigaam_api_key == "secret-key"
    assert cfg.allowed_user_ids == {11, 22} and cfg.poll_interval == 2.5
    assert cfg.bot_token not in repr(cfg) and cfg.gigaam_api_key not in repr(cfg)


@pytest.mark.parametrize(("key", "value"), [
    ("BOT_TOKEN", None), ("BOT_TOKEN", " "), ("GIGAAM_BASE_URL", None),
    ("GIGAAM_BASE_URL", " "), ("GIGAAM_BASE_URL", "ftp://asr"),
    ("BOT_MODE", "unknown"), ("BOT_MODE", "webhook"), ("WEBHOOK_PORT", "bad"),
    ("POLL_INTERVAL", "-1"), ("POLL_INTERVAL", "bad"), ("ALLOWED_USER_IDS", "1,bad"),
    ("GIGAAM_TIMEOUT", "-1"), ("GIGAAM_TIMEOUT", "bad"),
])
def test_invalid_configuration(monkeypatch, key, value):
    if value is None:
        monkeypatch.delenv(key)
    else:
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit):
        load_config()
