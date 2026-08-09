# Uslush — Telegram-бот для транскрипции аудио и видео

Telegram-бот, который принимает голосовые сообщения, видеокружки и видео, отправляет их на распознавание речи и возвращает текст в чат.

Стек: **Python 3.11**, **python-telegram-bot** (async), **aiohttp**, **faster-whisper** через Wyoming Protocol.

## Возможности

- Приём сообщений типов `voice`, `video_note`, `video`
- Асинхронная очередь с дедупликацией: у одного пользователя в обработке не более одной задачи
- HTTP-бридж к faster-whisper (ffmpeg + Wyoming Protocol)
- Режимы работы: **polling** (по умолчанию) и **webhook**
- Запуск в Docker через `docker compose`

## Архитектура

```
Telegram ──► Handler ──► DeduplicationQueue ──► Worker ──► WhisperClient
                                                    │              │
                                              send_message    HTTP POST
                                                                   ▼
                                                          whisper_service
                                                          (ffmpeg → Wyoming)
```

| Компонент | Описание |
|---|---|
| `bot/` | Telegram-бот: конфиг, хендлеры, очередь, воркер, HTTP-клиент |
| `whisper_service/` | FastAPI-бридж: принимает аудио, декодирует через ffmpeg, отправляет в Wyoming |

## Быстрый старт (Docker)

1. Скопируйте файл окружения и укажите токен бота:

```bash
cp .env.example .env
# Отредактируйте BOT_TOKEN в .env
```

2. При необходимости настройте адрес Wyoming-сервера с faster-whisper (по умолчанию `192.168.88.12:10305`).

3. Укажите в `.env` префикс образов из вашего GitHub-репозитория:

```env
IMAGE_PREFIX=ghcr.io/YOUR_GITHUB_USER/uslush
```

4. Загрузите готовые образы и запустите без локальной сборки:

```bash
docker compose pull
docker compose up -d --no-build
```

Бот подключится к `whisper-bridge` по адресу `http://whisper-bridge:8000`.

## Локальная сборка

Для разработки или проверки изменений используйте дополнительный Compose-файл:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

## Публикация образов в GitHub Container Registry

Workflow `.github/workflows/docker-publish.yml` автоматически:

- запускает тесты;
- собирает образы для `linux/amd64` и `linux/arm64`;
- публикует `ghcr.io/OWNER/REPOSITORY-bot:latest`;
- публикует `ghcr.io/OWNER/REPOSITORY-whisper-bridge:latest`.

После первого push в ветку `main` откройте раздел **Packages** репозитория. Если
репозиторий или пакеты приватные, перед `docker compose pull` выполните:

```bash
echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
```

Токену достаточно права `read:packages`. Для публичных пакетов авторизация не нужна.

## Ручной локальный запуск

### 1. Whisper-бридж

```bash
cd whisper_service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2. Бот

```bash
pip install -r requirements.txt
cp .env.example .env
# Бот в контейнерной конфигурации обращается к мосту по имени whisper-bridge
python -m bot.main
```

## Переменные окружения

| Переменная | Обязательная | По умолчанию | Описание |
|---|---|---|---|
| `BOT_TOKEN` | Да | — | Токен Telegram-бота ([@BotFather](https://t.me/BotFather)) |
| `BOT_MODE` | Нет | `polling` | `polling` или `webhook` |
| `WEBHOOK_URL` | При webhook | — | Публичный HTTPS-URL для webhook |
| `WEBHOOK_PORT` | Нет | `8443` | Порт webhook-сервера |
| `WYOMING_HOST` | Нет | `192.168.88.12` | Хост Wyoming/faster-whisper (для `whisper_service`) |
| `WYOMING_PORT` | Нет | `10305` | Порт Wyoming |
| `WHISPER_LANGUAGE` | Нет | `ru` | Язык распознавания |
| `IMAGE_PREFIX` | Для готовых образов | `ghcr.io/YOUR_GITHUB_USER/uslush` | Префикс GHCR-образов без суффикса компонента |
| `IMAGE_TAG` | Нет | `latest` | Тег обоих образов |

## Webhook-режим

В `.env`:

```env
BOT_MODE=webhook
WEBHOOK_URL=https://example.com/bot
WEBHOOK_PORT=8443
```

Пример конфигурации для Docker Compose — в комментариях в `docker-compose.yml`.

> Для webhook установите расширение: `pip install "python-telegram-bot[webhooks]"`.

## Тесты

```bash
pip install -r requirements.txt
pytest
```

Unit-тесты работают без внешних сервисов. Интеграционные тесты (live whisper + файлы в `Example/`) пропускаются автоматически, если окружение недоступно.

## Структура проекта

```
Uslush/
├── bot/
│   ├── main.py          # Точка входа
│   ├── config.py        # Конфигурация из env
│   ├── handlers.py      # Обработчики Telegram-сообщений
│   ├── queue.py         # Очередь с дедупликацией
│   ├── worker.py        # Фоновый воркер транскрипции
│   └── whisper.py       # HTTP-клиент бриджа
├── whisper_service/     # FastAPI-бридж к Wyoming
├── tests/               # Unit-тесты (pytest)
├── Dockerfile
├── docker-compose.yml
├── docker-compose.build.yml
├── requirements.txt
└── .env.example
```

## Поведение бота

- Пустая транскрипция → сообщение «Речь не распознана.»
- Ошибка скачивания или распознавания → «Ошибка при транскрипции. Попробуйте ещё раз.»
- Текстовые и прочие сообщения игнорируются

## Лицензия

Уточните лицензию при публикации репозитория.
