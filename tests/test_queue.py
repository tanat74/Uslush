"""Unit tests for DeduplicationQueue (bot/queue.py).

Covers requirements: 2.1, 2.2, 2.3, 2.4
"""

import asyncio

import pytest

from bot.queue import DeduplicationQueue, TranscriptionTask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_task(user_id: int, file_id: str = "file_a") -> TranscriptionTask:
    return TranscriptionTask(
        user_id=user_id,
        chat_id=user_id,
        file_id=file_id,
        media_type="voice",
        message_id=1,
    )


def assert_signal_matches_deque(q: DeduplicationQueue) -> None:
    assert q._signal.qsize() == len(q._deque)


# ---------------------------------------------------------------------------
# 1. Добавление одной задачи — get() возвращает её
# Validates: Requirement 2.1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_single_task_get_returns_it():
    """put() followed by get() returns the same task."""
    q = DeduplicationQueue()
    task = make_task(user_id=1)

    replaced = await q.put(task)
    assert replaced is False
    assert_signal_matches_deque(q)
    result = await q.get()

    assert result == task
    assert_signal_matches_deque(q)


# ---------------------------------------------------------------------------
# 2. Дедупликация — вторая задача от того же пользователя заменяет первую
# Validates: Requirement 2.2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deduplication_second_task_replaces_first():
    """When same user puts two tasks, only the newer one is in the queue."""
    q = DeduplicationQueue()
    task_old = make_task(user_id=1, file_id="old_file")
    task_new = make_task(user_id=1, file_id="new_file")

    assert await q.put(task_old) is False
    assert await q.put(task_new) is True
    assert_signal_matches_deque(q)
    assert q._signal.qsize() == 1

    result = await q.get()
    assert result == task_new
    assert result.file_id == "new_file"
    assert_signal_matches_deque(q)


@pytest.mark.asyncio
async def test_deduplication_does_not_leave_extra_signal_tokens():
    """A second get() after replacement must block, not pop an empty deque."""
    q = DeduplicationQueue()
    await q.put(make_task(user_id=1, file_id="old_file"))
    await q.put(make_task(user_id=1, file_id="new_file"))

    first = await q.get()
    assert first.file_id == "new_file"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.05)

    assert_signal_matches_deque(q)


# ---------------------------------------------------------------------------
# 3. Разные пользователи — задачи сохраняются в порядке FIFO
# Validates: Requirement 2.3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fifo_order_for_different_users():
    """Tasks from distinct users are returned in insertion order (FIFO)."""
    q = DeduplicationQueue()
    task1 = make_task(user_id=10)
    task2 = make_task(user_id=20)
    task3 = make_task(user_id=30)

    await q.put(task1)
    await q.put(task2)
    await q.put(task3)
    assert_signal_matches_deque(q)

    assert await q.get() == task1
    assert await q.get() == task2
    assert await q.get() == task3


# ---------------------------------------------------------------------------
# 4. get() блокируется до появления задачи (async)
# Validates: Requirement 2.4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_blocks_until_task_is_available():
    """get() suspends the caller and resumes only after put() is called."""
    q = DeduplicationQueue()
    task = make_task(user_id=42)
    results: list[TranscriptionTask] = []

    async def consumer():
        results.append(await q.get())

    # Start consumer — it should block because queue is empty
    consumer_task = asyncio.create_task(consumer())

    # Give the event loop a chance to run the consumer (it must stay blocked)
    await asyncio.sleep(0)
    assert results == [], "get() should be blocking — no result yet"

    # Now provide a task; consumer should unblock
    await q.put(task)
    await consumer_task

    assert results == [task]


@pytest.mark.asyncio
async def test_get_skips_stale_signal_tokens():
    """get() keeps waiting if a leftover token finds an empty deque."""
    q = DeduplicationQueue()
    await q._signal.put(None)

    waiter = asyncio.create_task(q.get())
    await asyncio.sleep(0)
    assert not waiter.done()

    expected = make_task(user_id=7, file_id="late")
    await q.put(expected)
    assert await waiter == expected


# ---------------------------------------------------------------------------
# 5. remove_user() удаляет задачу; после удаления очередь пуста
# Validates: Requirement 2.2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_user_empties_queue():
    """remove_user() removes the pending task; queue is empty afterwards."""
    q = DeduplicationQueue()
    task = make_task(user_id=99)

    await q.put(task)
    await q.remove_user(99)

    assert q._signal.qsize() == 0
    assert len(q._deque) == 0
    assert 99 not in q._user_index


@pytest.mark.asyncio
async def test_remove_user_nonexistent_is_noop():
    """remove_user() for an unknown user_id does not raise or corrupt state."""
    q = DeduplicationQueue()
    task = make_task(user_id=1)

    await q.put(task)
    await q.remove_user(999)  # user not in queue

    result = await q.get()
    assert result == task
