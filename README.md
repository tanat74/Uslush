# Uslush — Telegram-бот для транскрипции аудио и видео

Telegram-бот принимает голосовые сообщения, видеокружки и видео, отправляет их
на распознавание в существующий сервер faster-whisper по протоколу Wyoming и
возвращает текст в чат.

Стек: **Python 3.11**, **python-telegram-bot** (async), **ffmpeg**, **Wyoming Protocol**.

## Возможности

- Приём сообщений типов `voice`, `video_note`, `video`
- Файлы больше 20 МБ отклоняются сразу: у Bot API лимит скачивания `getFile`
- Асинхронная очередь с дедупликацией: у одного пользователя в обработке не более одной задачи
- Декодирование аудио и видео через ffmpeg внутри контейнера бота
- Прямое подключение к Wyoming/faster-whisper без промежуточного HTTP-сервиса
- Режимы работы: **polling** (по умолчанию) и **webhook**
- Опциональный список разрешённых Telegram user ID
- Один Docker-образ и один контейнер приложения

## Архитектура

```text
Telegram → Handler → DeduplicationQueue → Worker → ffmpeg → Wyoming/faster-whisper
                                              └──────────→ send_message
```

Сервер Wyoming/faster-whisper не входит в этот проект и должен быть запущен
отдельно. Контейнер бота должен иметь сетевой доступ к его TCP-порту.

## Быстрый старт (Docker)

1. Создайте файл окружения и укажите токен:

```bash
cp .env.example .env
```

2. В `.env` настройте как минимум:

```env
BOT_TOKEN=your-telegram-bot-token
WYOMING_HOST=wyoming.example
WYOMING_PORT=10300
WHISPER_LANGUAGE=ru
IMAGE_NAME=ghcr.io/YOUR_GITHUB_USER/uslush
```

3. Загрузите образ и запустите единственный контейнер:

```bash
docker compose pull
docker compose up -d --no-build
```

Для локальной сборки:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

## Публикация образа в GitHub Container Registry

Workflow `.github/workflows/docker-publish.yml` запускает тесты, собирает образ
для `linux/amd64` и `linux/arm64` и публикует его как:

```text
ghcr.io/OWNER/REPOSITORY:latest
```

Для приватного пакета перед `docker compose pull` выполните:

```bash
echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
```

Токену достаточно права `read:packages`. Для публичного пакета авторизация не нужна.

## Ручной запуск

На машине должны быть установлены Python 3.11 и `ffmpeg`:

```bash
pip install -r requirements.txt
cp .env.example .env
python -m bot.main
```

## Переменные окружения

| Переменная | Обязательная | По умолчанию | Описание |
|---|---|---|---|
| `BOT_TOKEN` | Да | — | Токен Telegram-бота от BotFather |
| `WYOMING_HOST` | Да | — | Хост сервера Wyoming/faster-whisper |
| `WYOMING_PORT` | Нет | `10300` | TCP-порт Wyoming |
| `WHISPER_LANGUAGE` | Нет | `ru` | Язык распознавания |
| `ALLOWED_USER_IDS` | Нет | пусто (все) | Telegram user ID через запятую |
| `BOT_MODE` | Нет | `polling` | `polling` или `webhook` |
| `POLL_INTERVAL` | Нет | `60` | Пауза в секундах между запросами `getUpdates` |
| `FFMPEG_TIMEOUT` | Нет | `120` | Таймаут декодирования ffmpeg, секунды |
| `WYOMING_TIMEOUT` | Нет | `300` | Таймаут ответа ASR-сервера, секунды |
| `WEBHOOK_URL` | При webhook | — | Публичный HTTPS URL webhook |
| `WEBHOOK_PORT` | Нет | `8443` | Локальный порт webhook-сервера |

## Webhook-режим

```env
BOT_MODE=webhook
WEBHOOK_URL=https://example.com/bot
WEBHOOK_PORT=8443
```

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

Unit-тесты не требуют доступного Wyoming-сервера.

## Структура проекта

```text
Uslush/
├── bot/
│   ├── main.py          # Точка входа
│   ├── config.py        # Конфигурация из env
│   ├── handlers.py      # Обработчики Telegram-сообщений
│   ├── queue.py         # Очередь с дедупликацией
│   ├── worker.py        # Фоновый воркер транскрипции
│   └── whisper.py       # ffmpeg и прямой клиент Wyoming
├── tests/               # Unit-тесты
├── Dockerfile
├── docker-compose.yml
├── docker-compose.build.yml
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

## Поведение бота

- После постановки в очередь бот показывает индикатор «печатает»
- Если новое сообщение вытесняет ещё не обработанное от того же пользователя → «Предыдущее необработанное сообщение заменено этим.»
- Пустая транскрипция → «Речь не распознана.»
- Файл длиннее 180 секунд → «Файл слишком длинный для распознавания.»
- Таймаут ffmpeg или ASR → «Распознавание заняло слишком много времени. Попробуйте ещё раз.»
- ASR-сервер недоступен → «Сервер распознавания недоступен. Попробуйте позже.»
- Прочая ошибка скачивания или распознавания → «Ошибка при транскрипции. Попробуйте ещё раз.»
- Пользователь не из `ALLOWED_USER_IDS` → «Доступ запрещён.»
- Текстовые и прочие сообщения игнорируются
