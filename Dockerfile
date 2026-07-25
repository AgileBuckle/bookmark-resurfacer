# Pinned to a digest-stable minor version. Rebuild regularly to pick up
# base-image security patches.
FROM python:3.12-slim

# Do not run as root: a container escape or code-exec bug should not land on
# uid 0. UID 10001 is arbitrary but fixed so ./data ownership is predictable.
ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd -g "${APP_GID}" app \
 && useradd -u "${APP_UID}" -g "${APP_GID}" -M -d /app -s /usr/sbin/nologin app

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /app/data \
 && chown -R "${APP_UID}:${APP_GID}" /app/data \
 && chmod 700 /app/data

USER app

EXPOSE 8000

# --proxy-headers + --forwarded-allow-ips are required for correct scheme/host
# detection behind a reverse proxy. Trust only the proxy's address; the default
# of 127.0.0.1 is correct when the proxy shares the network namespace.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "127.0.0.1"]
