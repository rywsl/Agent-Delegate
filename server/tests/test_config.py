from __future__ import annotations


def test_ensure_data_dirs_creates_artifact_directories(env):
    """The web process must own /data/tasks before the root worker creates it."""
    from delegate.config import ensure_data_dirs, get_settings

    settings = get_settings()
    assert not settings.artifacts_dir.exists()
    ensure_data_dirs()
    assert settings.artifacts_dir.is_dir() and settings.uploads_dir.is_dir()
    ensure_data_dirs()  # idempotent


def test_ensure_data_dirs_rejects_a_read_only_directory(env, monkeypatch):
    import os

    import pytest

    from delegate import config

    settings = config.get_settings()
    settings.artifacts_dir.mkdir(parents=True)
    real_access = os.access
    monkeypatch.setattr(config.os, "access",
                        lambda path, mode: False if str(path) == str(settings.artifacts_dir) else real_access(path, mode))
    with pytest.raises(RuntimeError, match="not writable"):
        config.ensure_data_dirs()
