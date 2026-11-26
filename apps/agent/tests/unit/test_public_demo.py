"""PUBLIC_DEMO guards: fake provider only, real secrets, no real mail, schedule parsing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from lead_qualifier.config import Settings
from lead_qualifier.scripts.demo_reset import next_reset

SECRETS = {
    "admin_api_token": "a" * 20,
    "n8n_api_token": "b" * 20,
    "n8n_webhook_secret": "c" * 20,
    "ip_hash_secret": "d" * 20,
}


def public(**overrides: object) -> Settings:
    values: dict[str, object] = {"app_env": "local", "public_demo": True, "smtp_host": "mailpit"}
    return Settings(**{**values, **SECRETS, **overrides})  # type: ignore[arg-type]


def test_a_safe_public_demo_is_accepted():
    settings = public()
    assert settings.public_demo and settings.llm_provider == "fake"


@pytest.mark.parametrize("provider", ["anthropic", "bedrock", "openai"])
def test_a_real_provider_is_refused(provider: str):
    with pytest.raises(ValidationError, match="LLM_PROVIDER must be fake"):
        public(llm_provider=provider)


def test_an_llm_key_is_refused_even_with_the_fake_provider():
    with pytest.raises(ValidationError, match="no LLM API key"):
        public(anthropic_api_key="sk-ant-" + "x" * 20)
    with pytest.raises(ValidationError, match="no LLM API key"):
        public(openai_api_key="sk-" + "x" * 20)


def test_secrets_must_be_generated_not_empty_or_development_defaults():
    with pytest.raises(ValidationError, match="ADMIN_API_TOKEN must be a generated secret"):
        public(admin_api_token="")
    with pytest.raises(ValidationError, match="IP_HASH_SECRET must be a generated secret"):
        public(ip_hash_secret="local-dev-ip-hash-secret-change-me")


def test_mail_only_goes_to_the_internal_mailpit():
    with pytest.raises(ValidationError, match="SMTP_HOST must be mailpit"):
        public(smtp_host="smtp.gmail.com")
    with pytest.raises(ValidationError, match="SMTP_HOST must be mailpit"):
        public(smtp_username="u", smtp_password="p", smtp_starttls=True)


def test_n8n_and_production_are_refused():
    with pytest.raises(ValidationError, match="ORCHESTRATOR must be inline"):
        public(orchestrator="n8n")
    with pytest.raises(ValidationError, match="APP_ENV must not be production"):
        public(app_env="production")


def test_the_guards_do_not_apply_to_a_normal_instance():
    assert Settings(app_env="local", llm_provider="anthropic").public_demo is False


@pytest.mark.parametrize("bad", ["24:00", "4", "ab:cd", "12:60"])
def test_reset_time_must_be_hh_mm(bad: str):
    with pytest.raises(ValidationError, match="DEMO_RESET_AT"):
        public(demo_reset_at=bad)


def test_next_reset_is_the_next_daily_time_or_an_interval():
    now = datetime(2026, 5, 1, 3, 0, tzinfo=UTC)
    assert next_reset(now, public(demo_reset_at="04:30")) == datetime(2026, 5, 1, 4, 30, tzinfo=UTC)
    late = datetime(2026, 5, 1, 5, 0, tzinfo=UTC)
    assert next_reset(late, public(demo_reset_at="04:30")) == datetime(
        2026, 5, 2, 4, 30, tzinfo=UTC
    )
    assert next_reset(now, public(demo_reset_interval_hours=6)) == now + timedelta(hours=6)
