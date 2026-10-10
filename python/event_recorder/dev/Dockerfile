# Development image: the production image's Python and packages, with no source in it.
# docker-compose.yml bind-mounts this checkout over /app/event_recorder, so every line
# being run is the one in the working tree. pytest is the only addition.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt pytest

ENV TZ=UTC
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
