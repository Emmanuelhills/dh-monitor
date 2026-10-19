"""Process-level configuration loaded from the environment (or a .env file).

Business settings an administrator can change at runtime (timezone, reminder
schedule, SES sender, ...) live in the ``application_settings`` table instead.
"""

import os
from functools import lru_cache

from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Vercel sets VERCEL=1 in every deployment: default to the serverless configuration there.
ON_VERCEL = bool(os.getenv("VERCEL"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DHM_", extra="ignore")

    environment: str = "production" if ON_VERCEL else "development"
    # Also accepts DATABASE_URL / POSTGRES_URL as set by Vercel's Neon integration.
    database_url: str = Field(
        default="postgresql+psycopg://dhm:dhm@localhost:5432/dhm",
        validation_alias=AliasChoices("DHM_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL"),
    )
    # Celery broker. Redis is recommended (redis://localhost:6379/0); PostgreSQL also works via
    # kombu's SQLAlchemy transport (sqla+postgresql+psycopg://...) when Redis is unavailable.
    broker_url: str = "redis://localhost:6379/0"

    # Fernet key (urlsafe base64, 32 bytes) used to encrypt stored secrets.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = Field(default="", repr=False)

    # Public base URL of the frontend, used for links in reminder emails.
    app_base_url: str = Field(default="http://localhost:3000", validation_alias=AliasChoices("DHM_APP_BASE_URL", "APP_BASE_URL"))
    cors_origins: list[str] = ["http://localhost:3000"]

    session_cookie_name: str = "dhm_session"
    session_ttl_hours: int = 12
    cookie_secure: bool = ON_VERCEL

    login_max_failures: int = 5
    login_failure_window_minutes: int = 15

    # External lookups
    http_timeout_seconds: float = 15.0
    lookup_min_interval_seconds: float = 2.0
    check_max_retries: int = 3

    # Email delivery
    email_max_attempts: int = 5
    email_backoff_base_seconds: int = 60

    # Run Celery tasks inline (tests / single-process development).
    celery_eager: bool = False

    # "celery": a worker + beat scheduler run the jobs (self-hosted / Docker).
    # "inline": no worker; jobs run inside requests to /api/v1/cron/run and on-demand checks run
    # immediately (serverless hosting such as Vercel).
    task_mode: Literal["celery", "inline"] = "inline" if ON_VERCEL else "celery"
    # Bearer token required by /api/v1/cron/run (Vercel Cron sends CRON_SECRET automatically).
    cron_secret: str = Field(default="", repr=False, validation_alias=AliasChoices("DHM_CRON_SECRET", "CRON_SECRET"))
    # Seconds a cron run may spend on checks before stopping (the rest run next time).
    cron_time_budget_seconds: int = 45
    # Serverless: no connection pool kept between invocations.
    serverless: bool = ON_VERCEL
    # Behind a trusted proxy (Vercel): read the client IP from X-Forwarded-For / X-Real-IP.
    trust_proxy_headers: bool = ON_VERCEL

    # First administrator, created on the first sign-in when no users exist yet.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = Field(default="", repr=False)

    @field_validator("database_url")
    @classmethod
    def _sqlalchemy_url(cls, v: str) -> str:
        # Hosted providers hand out postgres:// or postgresql:// URLs; use the psycopg 3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
