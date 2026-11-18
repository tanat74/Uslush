FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 1000 uslush

COPY bot/ ./bot/

ENV BOT_MODE=polling

USER uslush

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, tempfile, time; from pathlib import Path; p = Path(os.environ.get('HEARTBEAT_PATH', str(Path(tempfile.gettempdir()) / 'uslush-heartbeat'))); assert time.time() - p.stat().st_mtime < 90"

CMD ["python", "-m", "bot.main"]
