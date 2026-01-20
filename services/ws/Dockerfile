FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml /app/
COPY src /app/src

RUN pip install --no-cache-dir .

CMD ["real-time-translation-ws"]
