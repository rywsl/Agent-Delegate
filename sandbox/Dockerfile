# Sandbox image: one container per delegated task, running Claude Code or Codex headlessly.
FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=latest
ARG CODEX_VERSION=latest

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git ca-certificates curl wget jq ripgrep procps less unzip zip \
      python3 python3-pip python3-venv build-essential \
 && rm -rf /var/lib/apt/lists/*

# Claude Code's installer must not run from / (it would scan the whole filesystem).
WORKDIR /tmp
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" "@openai/codex@${CODEX_VERSION}" \
 && npm cache clean --force

RUN useradd -m -u 10001 -s /bin/bash agent \
 && mkdir -p /workspace /task /out /outputs \
 && chown agent:agent /workspace /task /out /outputs

COPY runner.py /opt/delegate/runner.py

USER agent
ENV HOME=/home/agent \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    NPM_CONFIG_PREFIX=/home/agent/.npm-global \
    PATH=/home/agent/.local/bin:/home/agent/.npm-global/bin:$PATH
WORKDIR /workspace

ENTRYPOINT ["python3", "-u", "/opt/delegate/runner.py"]
