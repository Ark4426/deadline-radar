"""Application configuration loaded from environment variables."""

import os
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Default configuration for local development and production."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-this-secret")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _as_bool(os.environ.get("SESSION_COOKIE_SECURE"))
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    DEBUG = _as_bool(os.environ.get("FLASK_DEBUG"))
    DATABASE = os.environ.get("DATABASE_PATH")
    MODEL_PATH = os.environ.get("MODEL_PATH")

    @staticmethod
    def default_database(instance_path: str) -> str:
        return str(Path(instance_path) / "deadline_radar.db")
