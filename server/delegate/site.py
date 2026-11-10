"""Admin-editable platform settings, with environment defaults underneath."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from . import harness
from .config import get_settings
from .models import SiteSetting, User

MODELS_KEY = "models_json"
SANDBOX_PRICE_KEY = "sandbox_usd_per_minute"
SANDBOX_POINTS_KEY = "sandbox_points_per_minute"
POINTS_PER_USD_KEY = "points_per_usd"
FREE_MINUTES_KEY = "free_sandbox_minutes"
MAX_QUEUED_KEY = "max_queued_tasks"
MAX_QUEUED_USER_KEY = "max_queued_per_user"
HARNESS_UPDATED_KEY = "harness_updated_at"


def _raw(db: Session, key: str) -> str | None:
    row = db.get(SiteSetting, key)
    if row is None or row.value == "":
        return None
    return row.value


def put(db: Session, key: str, value: str) -> None:
    row = db.get(SiteSetting, key)
    if row is None:
        db.add(SiteSetting(key=key, value=value))
    else:
        row.value = value


def sandbox_usd_per_minute(db: Session) -> float:
    raw = _raw(db, SANDBOX_PRICE_KEY)
    if raw is None:
        return get_settings().sandbox_usd_per_minute
    return max(0.0, float(raw))


def points_per_usd(db: Session) -> float:
    """How many sandbox points one USD of recharge becomes. Must stay positive."""
    raw = _raw(db, POINTS_PER_USD_KEY)
    configured = get_settings().points_per_usd
    if raw is None:
        return configured if configured > 0 else 100.0
    try:
        value = float(raw)
    except ValueError:
        return configured if configured > 0 else 100.0
    return value if value > 0 else (configured if configured > 0 else 100.0)


def sandbox_points_per_minute(db: Session) -> float:
    """Points charged for each billed sandbox minute.

    Until an admin saves a points price, convert the existing USD price at the current ratio
    so a previous per-minute rate keeps the same money value.
    """
    raw = _raw(db, SANDBOX_POINTS_KEY)
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return round(sandbox_usd_per_minute(db) * points_per_usd(db), 4)


def usd_to_points(db: Session, usd: float) -> int:
    """Convert a recharge amount into whole sandbox points at the current ratio."""
    if usd == 0:
        return 0
    ratio = points_per_usd(db)
    points = int(round(abs(float(usd)) * ratio))
    if points == 0:
        points = 1
    return points if usd > 0 else -points


def free_grant_seconds(db: Session) -> int:
    raw = _raw(db, FREE_MINUTES_KEY)
    minutes = get_settings().free_sandbox_minutes if raw is None else float(raw)
    return max(0, int(round(minutes * 60)))


def queue_limits(db: Session) -> tuple[int, int]:
    s = get_settings()
    global_raw = _raw(db, MAX_QUEUED_KEY)
    user_raw = _raw(db, MAX_QUEUED_USER_KEY)
    global_max = s.max_queued_tasks if global_raw is None else int(global_raw)
    per_user = s.max_queued_per_user if user_raw is None else int(user_raw)
    return max(1, global_max), max(1, per_user)


def offered_models(db: Session, agent: str) -> list[str]:
    raw = _raw(db, MODELS_KEY)
    if raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {}
        custom = parsed.get(agent)
        if isinstance(custom, list) and custom:
            return [str(item) for item in custom if str(item).strip()]
    return get_settings().models_for(agent)


def model_map(db: Session, agents: list[str]) -> dict[str, list[str]]:
    return {agent: offered_models(db, agent) for agent in agents}


def save_model_map(db: Session, mapping: dict[str, list[str]]) -> None:
    clean = {agent: [m.strip() for m in models if m.strip()] for agent, models in mapping.items()}
    put(db, MODELS_KEY, json.dumps(clean, ensure_ascii=False))


def snapshot(db: Session) -> dict:
    s = get_settings()
    global_max, per_user = queue_limits(db)
    return {
        "sandbox_usd_per_minute": sandbox_usd_per_minute(db),
        "sandbox_points_per_minute": sandbox_points_per_minute(db),
        "points_per_usd": points_per_usd(db),
        "free_sandbox_minutes": free_grant_seconds(db) / 60,
        "max_queued_tasks": global_max,
        "max_queued_per_user": per_user,
        "sandbox_max_concurrent": s.sandbox_max_concurrent,
        "per_user_concurrency": s.per_user_concurrency,
        "models": model_map(db, s.agents),
        "harnesses": [
            {"id": item.id, "label": item.label, "provider": item.provider, "package": item.npm_package,
             "binary": item.binary}
            for item in harness.HARNESSES if item.id in s.agents
        ],
        "harness_updated_at": _raw(db, HARNESS_UPDATED_KEY),
        "channel_types": [{"id": type_id, "label": label} for type_id, label in harness.CHANNEL_TYPES],
    }


def ensure_free_seconds(db: Session, user: User) -> int:
    """Give an existing account its one-time grant the first time we look."""
    if user.sandbox_free_seconds is None:
        user.sandbox_free_seconds = free_grant_seconds(db)
        db.flush()
    return int(user.sandbox_free_seconds)
