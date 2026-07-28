FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ARG APP_UID=1000
ARG APP_GID=1000
RUN if [ "${APP_UID}" = "0" ] || [ "${APP_GID}" = "0" ]; then \
        echo "APP_UID and APP_GID must be non-root IDs" >&2; \
        exit 1; \
    fi && \
    if ! getent group "${APP_GID}" >/dev/null; then \
        addgroup --gid "${APP_GID}" tanban; \
    fi && \
    if getent passwd "${APP_UID}" >/dev/null; then \
        echo "APP_UID ${APP_UID} is already used in the base image" >&2; \
        exit 1; \
    fi && \
    adduser --disabled-password --gecos "" --uid "${APP_UID}" \
        --gid "${APP_GID}" tanban

RUN apt-get update && \
    apt-get install --yes --no-install-recommends mariadb-client && \
    rm -rf /var/lib/apt/lists/*

COPY requirements-lock.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install --requirement requirements-lock.txt

COPY --chown=${APP_UID}:${APP_GID} . .

RUN mkdir -p /app/logs && \
    touch /app/logs/activity.log && \
    chown -R "${APP_UID}:${APP_GID}" /app/logs

USER tanban

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
