FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/

ENV BOT_MODE=polling

CMD ["python", "-m", "bot.main"]
