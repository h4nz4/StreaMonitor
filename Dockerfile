# syntax=docker/dockerfile:1

FROM python:3.14-alpine3.23

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV PYCURL_SSL_LIBRARY=openssl \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apk add --no-cache ffmpeg libcurl

WORKDIR /app

RUN apk add --no-cache --virtual .build-deps build-base curl-dev

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen \
    && apk del .build-deps

COPY *.py ./
COPY streamonitor ./streamonitor

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 5000
CMD ["python", "Downloader.py"]
