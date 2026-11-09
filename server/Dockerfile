FROM node:22-bookworm-slim AS console
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DELEGATE_DATA_DIR=/data

WORKDIR /app
COPY server/pyproject.toml ./
COPY server/delegate ./delegate
COPY server/delegate_mcp ./delegate_mcp
RUN pip install .

COPY --from=console /web/dist /app/web/dist

RUN useradd -m -u 10002 app && mkdir -p /data && chown app:app /data
USER app
EXPOSE 8000 8001
# Same image for all three roles: delegate-web | delegate-worker | delegate-mcp
CMD ["delegate-web"]
