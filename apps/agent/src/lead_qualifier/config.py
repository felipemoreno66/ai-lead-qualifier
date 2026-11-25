"""Application settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_LENGTH = 16
# Placeholder values shipped in docker-compose.yml for local use; never acceptable in production.
KNOWN_DEFAULT_PREFIX = "local-dev-"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, env_ignore_empty=True
    )

    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://leadq:leadq@localhost:5432/leadq"

    workspaces_dir: Path = Path("../../workspaces")
    migrations_dir: Path = Path("migrations")
    enabled_workspaces: str = "northwind-academy"
    allow_draft_workspaces: bool = False

    web_public_origin: str = "http://localhost:3000"
    dashboard_base_url: str = "http://localhost:3000"

    admin_api_token: str = ""
    n8n_api_token: str = ""
    n8n_webhook_secret: str = ""
    ip_hash_secret: str = ""
    trusted_proxies: str = ""

    expose_admin_api: bool = True
    orchestrator: Literal["n8n", "inline"] = "inline"
    n8n_webhook_base_url: str = "http://n8n:5678"
    dispatcher_enabled: bool = True
    outbox_poll_seconds: float = Field(default=2.0, gt=0)
    outbox_max_attempts: int = Field(default=8, ge=1)
    outbox_batch_size: int = Field(default=10, ge=1)
    outbox_lock_seconds: int = Field(default=60, ge=1)
    outbox_backoff_seconds: str = "5,30,120,600,1800,3600,7200,14400"

    rate_ip_per_minute: int = Field(default=5, ge=1)
    rate_ip_per_hour: int = Field(default=30, ge=1)
    rate_workspace_per_hour: int = Field(default=300, ge=1)
    rate_email_per_day: int = Field(default=3, ge=1)
    min_fill_seconds: float = Field(default=2.0, ge=0)
    max_body_bytes: int = Field(default=16 * 1024, ge=1024)
    duplicate_window_minutes: int = Field(default=10, ge=0)

    smtp_host: str = "localhost"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = False
    smtp_ssl: bool = False
    send_max_attempts: int = Field(default=3, ge=1)
    send_stale_minutes: int = Field(default=15, ge=1)

    llm_provider: Literal["fake", "anthropic", "bedrock", "openai"] = "fake"
    llm_model_default: str = "claude-haiku-5-5"
    llm_model_draft: str = ""
    llm_budget_usd: float = Field(default=5.0, ge=0)
    agent_run_timeout_minutes: int = Field(default=10, ge=1)
    qualify_max_runs_per_day: int = Field(default=5, ge=1)
    llm_calls_retention_days: int = Field(default=30, ge=1)
    llm_max_calls_per_lead: int = Field(default=12, ge=1)
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    aws_region: str = "us-east-1"

    embeddings_provider: Literal["fastembed", "openai", "fake"] = "fastembed"
    embeddings_cache_dir: Path = Path(".cache/fastembed")
    embeddings_warm_on_startup: bool = False
    kb_reindex_timeout_seconds: float = Field(default=900.0, gt=0)
    kb_top_k: int = Field(default=5, ge=1, le=20)
    # None = the embedding model's own default (``Embeddings.default_min_similarity``).
    kb_min_similarity: float | None = Field(default=None, ge=0, le=1)

    @field_validator("enabled_workspaces", "trusted_proxies", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _smtp_credentials_need_tls(self) -> Settings:
        if self.smtp_username and not (self.smtp_starttls or self.smtp_ssl):
            raise ValueError(
                "SMTP_USERNAME is set but neither SMTP_STARTTLS nor SMTP_SSL is on: "
                "credentials would cross the network in clear text"
            )
        return self

    @model_validator(mode="after")
    def _fill_or_require_secrets(self) -> Settings:
        names = ("admin_api_token", "n8n_api_token", "n8n_webhook_secret", "ip_hash_secret")
        for name in names:
            value: str = getattr(self, name)
            if self.app_env == "production":
                if len(value) < MIN_SECRET_LENGTH:
                    raise ValueError(
                        f"{name.upper()} must be set to at least {MIN_SECRET_LENGTH} characters "
                        "when APP_ENV=production"
                    )
                if value.startswith(KNOWN_DEFAULT_PREFIX):
                    raise ValueError(
                        f"{name.upper()} still has a development default value; generate a real "
                        "secret when APP_ENV=production"
                    )
            elif not value:
                # Ephemeral secret: fine for tests and a first local run, never for production.
                object.__setattr__(self, name, secrets.token_urlsafe(32))
        return self

    @property
    def web_origins(self) -> frozenset[str]:
        """Origin(s) of the web app (``WEB_PUBLIC_ORIGIN``), normalised without trailing slash."""
        return frozenset(
            o.strip().rstrip("/") for o in self.web_public_origin.split(",") if o.strip()
        )

    @property
    def enabled_workspace_slugs(self) -> frozenset[str]:
        return frozenset(s.strip() for s in self.enabled_workspaces.split(",") if s.strip())

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    @property
    def backoff_schedule(self) -> list[int]:
        return [int(p) for p in self.outbox_backoff_seconds.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
