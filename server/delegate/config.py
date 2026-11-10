"""Runtime configuration, read once from environment variables."""

from __future__ import annotations

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
    # --- web site ---
    secret_key: str
    database_url: str
    data_dir: Path
    public_url: str
    mcp_public_url: str
    allow_registration: bool
    session_max_age: int
    cookie_secure: bool

    # --- new-api sidecar (credentials are held by the web site only) ---
    newapi_base_url: str
    newapi_root_username: str
    newapi_root_password: str | None
    newapi_quota_per_unit: int
    newapi_user_group: str
    signup_credit_usd: float

    # --- sandbox ---
    docker_host: str | None
    sandbox_image: str
    sandbox_network: str
    sandbox_newapi_url: str
    sandbox_allowed_ips: str
    sandbox_agent_env: dict[str, str]
    sandbox_max_concurrent: int
    sandbox_memory: str
    sandbox_cpus: float
    sandbox_pids: int

    # --- task policy ---
    agents: list[str]
    default_agent: str
    claude_models: list[str]
    codex_models: list[str]
    default_budget_usd: float
    max_budget_usd: float
    min_balance_usd: float
    sandbox_usd_per_minute: float
    points_per_usd: float
    free_sandbox_minutes: float
    max_queued_tasks: int
    max_queued_per_user: int
    harness_volume: str
    gemini_models: list[str]
    grok_models: list[str]
    pi_models: list[str]
    deepseek_models: list[str]
    default_timeout_s: int
    max_timeout_s: int
    default_max_turns: int
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
            "claude": self.claude_models,
            "codex": self.codex_models,
            "gemini": self.gemini_models,
            "grok": self.grok_models,
            "pi": self.pi_models,
            "deepseek": self.deepseek_models,
        }.get(agent) or self.claude_models

    def usd_to_quota(self, usd: float) -> int:
        return int(round(usd * self.newapi_quota_per_unit))

    def quota_to_usd(self, quota: int | float | None) -> float:
        return (quota or 0) / self.newapi_quota_per_unit


def ensure_data_dirs() -> None:
    """Create the artifact directories while running as the web user.

    The worker runs as root (it needs the Docker socket) and the web site as an unprivileged user;
    whoever creates ``/data/tasks`` first owns it, and the other one can no longer add task
    directories. The web process therefore creates them at startup, before the worker runs.
    """
    s = get_settings()
    for path in (s.artifacts_dir, s.uploads_dir):
        path.mkdir(parents=True, exist_ok=True)
        if not os.access(path, os.W_OK):  # mkdir(exist_ok=True) silently accepts a foreign owner
            raise RuntimeError(
                f"{path} is not writable by this process; the data volume was probably created by "
                "the root worker. Fix it once with: docker compose exec -u root web chown -R 10002:10002 /data"
            )


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
        newapi_base_url=_env("NEWAPI_BASE_URL", "http://new-api:3000").rstrip("/"),
        newapi_root_username=_env("NEWAPI_ROOT_USERNAME", "root"),
        newapi_root_password=_env("NEWAPI_ROOT_PASSWORD"),
        newapi_quota_per_unit=_int("NEWAPI_QUOTA_PER_UNIT", 500000),
        newapi_user_group=_env("NEWAPI_USER_GROUP", "default"),
        signup_credit_usd=_float("DELEGATE_SIGNUP_CREDIT_USD", 0.0),
        docker_host=_env("DOCKER_HOST"),
        sandbox_image=_env("SANDBOX_IMAGE", "delegate-sandbox:latest"),
        sandbox_network=_env("SANDBOX_NETWORK", "delegate_sandbox"),
        sandbox_newapi_url=_env("SANDBOX_NEWAPI_URL", "http://new-api:3000").rstrip("/"),
        sandbox_allowed_ips="\n".join(_list("SANDBOX_ALLOWED_IPS", "")),
        # extra environment for the agent CLIs, e.g. "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1"
        sandbox_agent_env=dict(item.split("=", 1) for item in _list("SANDBOX_AGENT_ENV", "") if "=" in item),
        sandbox_max_concurrent=_int("SANDBOX_MAX_CONCURRENT", 4),
        sandbox_memory=_env("SANDBOX_MEMORY", "4g"),
        sandbox_cpus=_float("SANDBOX_CPUS", 2.0),
        sandbox_pids=_int("SANDBOX_PIDS", 1024),
        agents=_list("DELEGATE_AGENTS", "claude,codex,gemini,grok,pi,deepseek"),
        default_agent=_env("DELEGATE_DEFAULT_AGENT", "claude"),
        claude_models=_list("DELEGATE_CLAUDE_MODELS", "claude-sonnet-5-5,claude-opus-5-5,claude-haiku-5-5"),
        codex_models=_list("DELEGATE_CODEX_MODELS", "gpt-5.5-codex,gpt-5.5"),
        default_budget_usd=_float("DELEGATE_DEFAULT_BUDGET_USD", 5.0),
        max_budget_usd=_float("DELEGATE_MAX_BUDGET_USD", 50.0),
        min_balance_usd=_float("DELEGATE_MIN_BALANCE_USD", 0.10),
        sandbox_usd_per_minute=_float("DELEGATE_SANDBOX_USD_PER_MINUTE", 0.02),
        points_per_usd=_float("DELEGATE_POINTS_PER_USD", 100),
        free_sandbox_minutes=_float("DELEGATE_FREE_SANDBOX_MINUTES", 60),
        max_queued_tasks=_int("DELEGATE_MAX_QUEUED_TASKS", 200),
        max_queued_per_user=_int("DELEGATE_MAX_QUEUED_PER_USER", 8),
        harness_volume=_env("DELEGATE_HARNESS_VOLUME", "delegate_harness_bin") or "",
        gemini_models=_list("DELEGATE_GEMINI_MODELS", "gemini-3-pro-preview,gemini-2.5-flash"),
        grok_models=_list("DELEGATE_GROK_MODELS", "grok-4,grok-4-fast"),
        pi_models=_list("DELEGATE_PI_MODELS", "gpt-5.5,claude-sonnet-5-5"),
        deepseek_models=_list("DELEGATE_DEEPSEEK_MODELS", "deepseek-v4-pro,deepseek-v4-flash"),
        default_timeout_s=_int("DELEGATE_DEFAULT_TIMEOUT", 3600),
        max_timeout_s=_int("DELEGATE_MAX_TIMEOUT", 4 * 3600),
        default_max_turns=_int("DELEGATE_DEFAULT_MAX_TURNS", 200),
        per_user_concurrency=_int("DELEGATE_PER_USER_CONCURRENCY", 2),
        max_attachment_bytes=_int("DELEGATE_MAX_ATTACHMENT_BYTES", 1024 * 1024),
        max_upload_bytes=_int("DELEGATE_MAX_UPLOAD_BYTES", 512 * 1024 * 1024),
        upload_ttl_s=_int("DELEGATE_UPLOAD_TTL", 24 * 3600),
        download_ttl_s=_int("DELEGATE_DOWNLOAD_TTL", 24 * 3600),
        max_patch_inline_bytes=_int("DELEGATE_MAX_PATCH_INLINE_BYTES", 16 * 1024),
        max_output_bytes=_int("DELEGATE_MAX_OUTPUT_BYTES", 512 * 1024 * 1024),
    )
