FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DELEGATE_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml ./
COPY delegate ./delegate
COPY delegate_mcp ./delegate_mcp
RUN pip install .

RUN useradd -m -u 10002 app && mkdir -p /data && chown app:app /data
USER app
EXPOSE 8000 8001
# Same image for all three roles: delegate-web | delegate-worker | delegate-mcp
CMD ["delegate-web"]
