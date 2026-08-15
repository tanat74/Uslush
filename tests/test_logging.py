"""Unit tests for bot token redaction in logs."""

import io
import logging
from urllib.parse import quote

from bot.main import _TokenRedactingFormatter, _install_token_redaction

TOKEN = "123456789:AAHsecret-bot-token"


def _record(message: str, exc_info=None) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=exc_info,
    )
    return record


def test_formatter_redacts_token_from_message():
    formatter = _TokenRedactingFormatter(TOKEN, fmt="%(message)s")
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    formatted = formatter.format(_record(url))

    assert TOKEN not in formatted
    assert "[REDACTED]" in formatted


def test_formatter_redacts_url_encoded_token():
    formatter = _TokenRedactingFormatter(TOKEN, fmt="%(message)s")
    encoded = quote(TOKEN, safe="")
    formatted = formatter.format(_record(f"request {encoded}"))

    assert TOKEN not in formatted
    assert encoded not in formatted
    assert "[REDACTED]" in formatted


def test_formatter_redacts_token_from_traceback():
    formatter = _TokenRedactingFormatter(TOKEN, fmt="%(message)s")
    try:
        raise RuntimeError(f"httpx.ConnectError: POST https://api.telegram.org/bot{TOKEN}/getMe")
    except RuntimeError:
        import sys

        formatted = formatter.format(_record("request failed", exc_info=sys.exc_info()))

    assert TOKEN not in formatted
    assert "[REDACTED]" in formatted


def test_install_token_redaction_applies_to_root_logger(monkeypatch):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [handler])

    _install_token_redaction(TOKEN)
    logging.getLogger("httpx").error(
        "HTTP Request: POST https://api.telegram.org/bot%s/getUpdates",
        TOKEN,
    )

    output = stream.getvalue()
    assert TOKEN not in output
    assert "[REDACTED]" in output
