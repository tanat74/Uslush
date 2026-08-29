"""Unit tests for worker death logging and heartbeat in bot/main.py."""

import asyncio
import logging

import pytest

from bot import main as bot_main


def test_on_worker_done_logs_unexpected_exception(caplog):
    async def boom():
        raise RuntimeError("worker crashed")

    async def run():
        task = asyncio.create_task(boom())
        task.add_done_callback(bot_main._on_worker_done)
        with pytest.raises(RuntimeError):
            await task

    with caplog.at_level(logging.ERROR, logger="bot.main"):
        asyncio.run(run())

    assert "Transcription worker died" in caplog.text


def test_on_worker_done_ignores_cancellation(caplog):
    async def run():
        task = asyncio.create_task(asyncio.sleep(10))
        task.add_done_callback(bot_main._on_worker_done)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    with caplog.at_level(logging.ERROR, logger="bot.main"):
        asyncio.run(run())

    assert "Transcription worker died" not in caplog.text


@pytest.mark.asyncio
async def test_heartbeat_touches_file_while_worker_runs(tmp_path, monkeypatch):
    path = tmp_path / "uslush-heartbeat"
    monkeypatch.setattr(bot_main, "HEARTBEAT_PATH", path)
    monkeypatch.setattr(bot_main, "HEARTBEAT_INTERVAL_SEC", 0.01)

    async def linger():
        await asyncio.sleep(10)

    worker = asyncio.create_task(linger())
    heartbeat = asyncio.create_task(bot_main._run_heartbeat(worker))
    try:
        for _ in range(50):
            if path.exists():
                break
            await asyncio.sleep(0.01)
        assert path.exists()
    finally:
        heartbeat.cancel()
        worker.cancel()
        for task in (heartbeat, worker):
            try:
                await task
            except asyncio.CancelledError:
                pass
