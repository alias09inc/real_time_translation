FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml /app/
COPY src /app/src
COPY dictionary.csv /app/dictionary.csv

RUN pip install --no-cache-dir .

CMD ["real-time-translation-translate"]
