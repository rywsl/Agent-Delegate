"""Runtime configuration, read once from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in _env(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    secret_key: str
    database_url: str
    data_dir: Path
    public_url: str
    mcp_public_url: str
    allow_registration: bool
    session_max_age: int
    cookie_secure: bool

    openai_api_key: str | None
    openai_base_url: str | None
    anthropic_api_key: str | None
    anthropic_base_url: str | None
    gemini_api_key: str | None
    gemini_base_url: str | None

    docker_host: str | None
    sandbox_image: str
    sandbox_network: str
    sandbox_agent_env: dict[str, str]
    sandbox_max_concurrent: int
    sandbox_memory: str
    sandbox_cpus: float
    sandbox_pids: int

    agents: list[str]
    default_agent: str
    sandboxes: list[str]
    default_sandbox: str
    harnesses: list[str]
    default_harness: str
    harness_commands: dict[str, list[str]]
    sandbox_images: dict[str, str]
    anthropic_models: list[str]
    openai_models: list[str]
    gemini_models: list[str]
    default_timeout_s: int
    max_timeout_s: int
    default_max_turns: int
    llm_request_timeout_s: int
    max_output_tokens: int
    per_user_concurrency: int
    max_attachment_bytes: int
    max_upload_bytes: int
    upload_ttl_s: int
    download_ttl_s: int
    max_patch_inline_bytes: int
    max_output_bytes: int

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "tasks"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    def models_for(self, agent: str) -> list[str]:
        return {
            "anthropic": self.anthropic_models,
            "openai": self.openai_models,
            "gemini": self.gemini_models,
        }.get(agent, [])

    def provider_api_key(self, provider: str) -> str | None:
        return {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "gemini": self.gemini_api_key,
        }.get(provider)

    def provider_base_url(self, provider: str) -> str | None:
        return {
            "openai": self.openai_base_url,
            "anthropic": self.anthropic_base_url,
            "gemini": self.gemini_base_url,
        }.get(provider)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    secret = _env("DELEGATE_SECRET_KEY")
    if not secret:
        raise RuntimeError("DELEGATE_SECRET_KEY must be set (use a long random string)")
    data_dir = Path(_env("DELEGATE_DATA_DIR", "./data")).resolve()
    public_url = _env("DELEGATE_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    return Settings(
        secret_key=secret,
        database_url=_env("DELEGATE_DATABASE_URL", f"sqlite:///{(data_dir / 'delegate.db').as_posix()}"),
        data_dir=data_dir,
        public_url=public_url,
        mcp_public_url=_env("DELEGATE_MCP_PUBLIC_URL", f"{public_url}/mcp"),
        allow_registration=_bool("DELEGATE_ALLOW_REGISTRATION", True),
        session_max_age=_int("DELEGATE_SESSION_MAX_AGE", 7 * 24 * 3600),
        cookie_secure=_bool("DELEGATE_COOKIE_SECURE", public_url.startswith("https://")),
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_base_url=_env("OPENAI_BASE_URL"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_base_url=_env("ANTHROPIC_BASE_URL"),
        gemini_api_key=_env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY"),
        gemini_base_url=_env("GEMINI_BASE_URL") or _env("GOOGLE_BASE_URL"),
        docker_host=_env("DOCKER_HOST"),
        sandbox_image=_env("SANDBOX_IMAGE", "delegate-sandbox:latest"),
        sandbox_network=_env("SANDBOX_NETWORK", "delegate_sandbox"),
        sandbox_agent_env=dict(item.split("=", 1) for item in _list("SANDBOX_AGENT_ENV", "") if "=" in item),
        sandbox_max_concurrent=_int("SANDBOX_MAX_CONCURRENT", 4),
        sandbox_memory=_env("SANDBOX_MEMORY", "4g"),
        sandbox_cpus=_float("SANDBOX_CPUS", 2.0),
        sandbox_pids=_int("SANDBOX_PIDS", 1024),
        agents=_list("DELEGATE_AGENTS", "anthropic,openai,gemini"),
        default_agent=_env("DELEGATE_DEFAULT_AGENT", "anthropic"),
        sandboxes=_list("DELEGATE_SANDBOXES", "docker"),
        default_sandbox=_env("DELEGATE_DEFAULT_SANDBOX", "docker"),
        harnesses=_list("DELEGATE_HARNESSES", "sdk,claude-code,codex,gemini,grok,pi,deepseek"),
        default_harness=_env("DELEGATE_DEFAULT_HARNESS", "sdk"),
        harness_commands=json.loads(_env("DELEGATE_HARNESS_COMMANDS", "{}")),
        sandbox_images=json.loads(_env("DELEGATE_SANDBOX_IMAGES", "{}")),
        anthropic_models=_list("DELEGATE_ANTHROPIC_MODELS", "claude-sonnet-4-5,claude-opus-4-5,claude-haiku-4-5"),
        openai_models=_list("DELEGATE_OPENAI_MODELS", "gpt-5.1-codex,gpt-5.1"),
        gemini_models=_list("DELEGATE_GEMINI_MODELS", "gemini-3-pro-preview,gemini-2.5-flash"),
        default_timeout_s=_int("DELEGATE_DEFAULT_TIMEOUT", 3600),
        max_timeout_s=_int("DELEGATE_MAX_TIMEOUT", 4 * 3600),
        default_max_turns=_int("DELEGATE_DEFAULT_MAX_TURNS", 200),
        llm_request_timeout_s=_int("DELEGATE_LLM_REQUEST_TIMEOUT", 300),
        max_output_tokens=_int("DELEGATE_MAX_OUTPUT_TOKENS", 8192),
        per_user_concurrency=_int("DELEGATE_PER_USER_CONCURRENCY", 2),
        max_attachment_bytes=_int("DELEGATE_MAX_ATTACHMENT_BYTES", 1024 * 1024),
        max_upload_bytes=_int("DELEGATE_MAX_UPLOAD_BYTES", 512 * 1024 * 1024),
        upload_ttl_s=_int("DELEGATE_UPLOAD_TTL", 24 * 3600),
        download_ttl_s=_int("DELEGATE_DOWNLOAD_TTL", 24 * 3600),
        max_patch_inline_bytes=_int("DELEGATE_MAX_PATCH_INLINE_BYTES", 16 * 1024),
        max_output_bytes=_int("DELEGATE_MAX_OUTPUT_BYTES", 512 * 1024 * 1024),
    )
