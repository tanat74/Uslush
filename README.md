# Uslush — Telegram-бот для транскрипции аудио и видео

Telegram-бот принимает голосовые сообщения, видеокружки и видео, отправляет их
на распознавание в существующий сервер Wyoming/faster-whisper или GigaAM и
возвращает текст в чат.

Стек: **Python 3.11**, **python-telegram-bot** (async), **ffmpeg**, **Wyoming Protocol**.

## Возможности

- Приём сообщений типов `voice`, `video_note`, `video`
- Файлы больше 20 МБ отклоняются сразу: у Bot API лимит скачивания `getFile`
- Асинхронная очередь с дедупликацией: у одного пользователя в обработке не более одной задачи
- Декодирование аудио и видео через ffmpeg внутри контейнера бота в режиме Wyoming
- Постепенный вывод расшифровки GigaAM в Telegram по мере готовности сегментов
- Прямое подключение к Wyoming/faster-whisper без промежуточного HTTP-сервиса
- Режимы работы: **polling** (по умолчанию) и **webhook**
- Опциональный список разрешённых Telegram user ID
- Один Docker-образ и один контейнер приложения

## Архитектура

```text
Telegram → Handler → DeduplicationQueue → Worker → ffmpeg → Wyoming/faster-whisper
                                            ├──→ GigaAM (HTTP, multipart → SSE)
                                            └──→ Telegram (ответ и редактирование)
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

## Подключение GigaAM

Для отдельно запущенного `docker-gigaam-server` укажите в `.env`:

```env
ASR_BACKEND=gigaam
GIGAAM_BASE_URL=http://host.docker.internal:8770
GIGAAM_MODEL=gigaam-v3-e2e-rnnt
```

Адрес задаётся без `/v1`. В примере сервер работает на хосте Docker Desktop.
Для удалённого сервера подставьте его DNS-имя или IP, доступный из контейнера.
Если на сервере включена авторизация, задайте `GIGAAM_API_KEY`. После изменения
конфигурации пересоздайте контейнер: `docker compose up -d`.

Бот загружает исходный файл на `POST /v1/audio/transcriptions`. Во время обработки
ответ «Распознаю…» заменяется первым сегментом, затем обновляется примерно раз в
две секунды. Длинный текст продолжается в следующем сообщении. Короткая запись
может прийти одним сегментом. При обрыве уже полученный текст сохраняется с пометкой.
В режиме Wyoming ответ обновляется только по готовности полной расшифровки.

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
| `ASR_BACKEND` | Нет | `wyoming` | `wyoming` или `gigaam` |
| `GIGAAM_BASE_URL` | Для gigaam | — | Базовый URL без `/v1` |
| `GIGAAM_MODEL` | Нет | `gigaam-v3-e2e-rnnt` | Модель, включённая на сервере |
| `GIGAAM_API_KEY` | Нет | — | Bearer-токен сервера |
| `GIGAAM_TIMEOUT` | Нет | `300` | Сетевой таймаут, в том числе ожидание очередного блока ответа, секунды |
| `WYOMING_HOST` | Для wyoming | — | Хост сервера Wyoming/faster-whisper |
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

Unit-тесты не требуют доступных ASR-серверов или Telegram.

## Структура проекта

```text
Uslush/
├── bot/
│   ├── main.py          # Точка входа
│   ├── config.py        # Конфигурация из env
│   ├── handlers.py      # Обработчики Telegram-сообщений
│   ├── queue.py         # Очередь с дедупликацией
│   ├── worker.py        # Фоновый воркер транскрипции
│   ├── asr.py           # Общий интерфейс клиентов
│   ├── gigaam.py        # HTTP-клиент GigaAM, чтение SSE
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
- Файл длиннее 180 секунд в режиме Wyoming → «Файл слишком длинный для распознавания.»
- Таймаут ffmpeg или ASR → «Распознавание заняло слишком много времени. Попробуйте ещё раз.»
- ASR-сервер недоступен → «Сервер распознавания недоступен. Попробуйте позже.»
- Прочая ошибка скачивания или распознавания → «Ошибка при транскрипции. Попробуйте ещё раз.»
- Пользователь не из `ALLOWED_USER_IDS` → «Доступ запрещён.»
- Текстовые и прочие сообщения игнорируются
