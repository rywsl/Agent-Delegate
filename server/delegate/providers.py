from __future__ import annotations

from sqlalchemy.orm import Session

from .config import get_settings
from .models import ProviderConfig
from .security import decrypt

SUPPORTED_PROVIDERS = ("anthropic", "openai", "gemini")


class ProviderError(RuntimeError):
    pass


def credentials(session: Session, provider: str) -> dict[str, str | None]:
    if provider not in SUPPORTED_PROVIDERS:
        raise ProviderError(f"unsupported model provider: {provider}")
    settings = get_settings()
    config = session.get(ProviderConfig, provider)
    if config is not None and not config.enabled:
        raise ProviderError(f"model provider {provider} is disabled by the administrator")
    api_key = decrypt(config.api_key_enc) if config and config.api_key_enc else settings.provider_api_key(provider)
    if not api_key:
        raise ProviderError(f"no API key configured for {provider}; configure it in the admin console")
    base_url = (config.base_url.strip() if config else "") or settings.provider_base_url(provider)
    return {"api_key": api_key, "base_url": base_url.rstrip("/") if base_url else None}
