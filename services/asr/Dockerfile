FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md uv.lock /app/
COPY src /app/src
COPY dictionary.csv /app/dictionary.csv

RUN pip install --no-cache-dir .

CMD ["real-time-translation-asr"]
