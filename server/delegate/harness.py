"""Built-in coding CLIs. Versions are never pinned; an admin update installs whatever is current."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Harness:
    id: str
    label: str
    provider: str
    npm_package: str
    binary: str
    default_models: tuple[str, ...]
    # Base URL used when the user brings a key and does not set one.
    default_base_url: str
    # Platform traffic goes through new-api. OpenAI-compatible CLIs need the /v1 prefix.
    platform_openai_v1: bool


HARNESSES: tuple[Harness, ...] = (
    Harness(
        "claude", "Claude Code", "anthropic", "@anthropic-ai/claude-code", "claude",
        ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"),
        "https://api.anthropic.com", False,
    ),
    Harness(
        "codex", "Codex", "openai", "@openai/codex", "codex",
        ("gpt-5.5-codex", "gpt-5.5"),
        "https://api.openai.com/v1", True,
    ),
    Harness(
        "gemini", "Gemini CLI", "gemini", "@google/gemini-cli", "gemini",
        ("gemini-3-pro-preview", "gemini-2.5-flash"),
        "https://generativelanguage.googleapis.com", False,
    ),
    Harness(
        "grok", "Grok", "xai", "@xai-official/grok", "grok",
        ("grok-4", "grok-4-fast"),
        "https://api.x.ai/v1", True,
    ),
    Harness(
        "pi", "Pi", "pi", "@earendil-works/pi-coding-agent", "pi",
        ("gpt-5.5", "claude-sonnet-5-5"),
        "https://api.openai.com/v1", True,
    ),
    Harness(
        "deepseek", "DeepSeek", "deepseek", "@deepseek-ai/dsh", "dsh",
        ("deepseek-v4-pro", "deepseek-v4-flash"),
        "https://api.deepseek.com", False,
    ),
)

BY_ID = {item.id: item for item in HARNESSES}
NPM_PACKAGES = tuple(item.npm_package for item in HARNESSES)
# new-api channel type ids. The admin form sends these through; the number is what new-api stores.
CHANNEL_TYPES = (
    (1, "OpenAI"),
    (14, "Anthropic"),
    (24, "Gemini"),
    (43, "DeepSeek"),
    (45, "xAI"),
)


def get(agent: str) -> Harness:
    try:
        return BY_ID[agent]
    except KeyError as exc:
        raise KeyError(f"unknown harness {agent}") from exc


def ids() -> list[str]:
    return [item.id for item in HARNESSES]
