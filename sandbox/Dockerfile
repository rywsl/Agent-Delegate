# Sandbox image: one container per delegated task, using the official model-provider SDKs.
FROM python:3.12-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git ca-certificates curl wget jq ripgrep procps less unzip zip build-essential \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "openai>=1.0" "anthropic>=0.40" "google-genai>=1.0"

RUN useradd -m -u 10001 -s /bin/bash agent \
 && mkdir -p /workspace /task /out /outputs \
 && chown agent:agent /workspace /task /out /outputs

# Optional harnesses are deliberately excluded from the default image. Build a variant with only
# the package(s) needed by a deployment, e.g. HARNESS_PACKAGES=@anthropic-ai/claude-code.
ARG HARNESS_PACKAGES=""
RUN if [ -n "$HARNESS_PACKAGES" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends nodejs npm \
      && npm install -g $HARNESS_PACKAGES \
      && npm cache clean --force \
      && rm -rf /var/lib/apt/lists/*; \
    fi

COPY runner.py agent.py harness.py /opt/delegate/

USER agent
ENV HOME=/home/agent \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    NPM_CONFIG_PREFIX=/home/agent/.npm-global \
    PATH=/home/agent/.local/bin:/home/agent/.npm-global/bin:$PATH
WORKDIR /workspace

ENTRYPOINT ["python3", "-u", "/opt/delegate/runner.py"]
