import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Dict


@dataclass
class TranscriptionTask:
    user_id: int
    chat_id: int
    file_id: str
    media_type: str  # "voice" | "video_note" | "video"
    message_id: int


class DeduplicationQueue:
    """Асинхронная очередь FIFO с дедупликацией по user_id.

    Гарантирует, что для каждого пользователя в очереди находится
    не более одной задачи. При добавлении новой задачи от того же
    пользователя старая удаляется, новая добавляется в конец.

    Внутренняя реализация:
    - ``collections.deque`` — упорядоченное хранение задач
    - ``dict`` (user_id → task) — быстрый поиск задачи по пользователю
    - ``asyncio.Lock`` — защита операций put/get/remove_user
    - ``asyncio.Queue`` — сигнальный механизм (аналог семафора) для
      ожидания в get()
    """

    def __init__(self) -> None:
        self._deque: deque[TranscriptionTask] = deque()
        self._user_index: Dict[int, TranscriptionTask] = {}
        self._lock = asyncio.Lock()
        # asyncio.Queue используется как семафор без ограничения размера.
        # put() кладёт токен None; get() забирает токен, блокируясь до
        # появления задачи.
        self._signal: asyncio.Queue[None] = asyncio.Queue()

    async def put(self, task: TranscriptionTask) -> None:
        """Добавить задачу в очередь с дедупликацией по user_id.

        Если задача от того же user_id уже присутствует, старая
        удаляется из deque и dict, новая добавляется в конец.
        """
        async with self._lock:
            if task.user_id in self._user_index:
                old_task = self._user_index[task.user_id]
                self._deque.remove(old_task)
            self._deque.append(task)
            self._user_index[task.user_id] = task
        # Сигнализируем о доступности новой задачи вне lock, чтобы
        # не создавать лишней конкуренции за блокировку.
        await self._signal.put(None)

    async def get(self) -> TranscriptionTask:
        """Ждать появления задачи и вернуть первую из очереди (FIFO).

        Блокируется до тех пор, пока очередь не окажется непустой.
        """
        await self._signal.get()
        async with self._lock:
            task = self._deque.popleft()
            del self._user_index[task.user_id]
        return task

    async def remove_user(self, user_id: int) -> None:
        """Удалить задачу пользователя из очереди (если есть).

        Если задача для данного user_id отсутствует — ничего не делает.
        """
        async with self._lock:
            if user_id not in self._user_index:
                return
            task = self._user_index.pop(user_id)
            self._deque.remove(task)
        # Потребляем один токен сигнала, чтобы счётчик оставался
        # консистентным с фактическим размером deque.
        try:
            self._signal.get_nowait()
        except asyncio.QueueEmpty:
            pass
