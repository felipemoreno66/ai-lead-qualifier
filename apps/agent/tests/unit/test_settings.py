from __future__ import annotations

import pytest
from pydantic import ValidationError

from lead_qualifier.config import Settings

GOOD = {
    "admin_api_token": "a" * 20,
    "n8n_api_token": "b" * 20,
    "n8n_webhook_secret": "c" * 20,
    "ip_hash_secret": "d" * 20,
}
SECRETS = tuple(GOOD)


def production(**overrides: str) -> Settings:
    return Settings(app_env="production", **{**GOOD, **overrides})  # type: ignore[arg-type]


def test_production_accepts_strong_secrets():
    assert production().app_env == "production"


@pytest.mark.parametrize("name", SECRETS)
def test_production_requires_every_secret(name: str):
    with pytest.raises(ValidationError, match=name.upper()):
        production(**{name: ""})


@pytest.mark.parametrize("name", SECRETS)
def test_production_rejects_short_secrets(name: str):
    with pytest.raises(ValidationError, match="at least 16"):
        production(**{name: "short"})


@pytest.mark.parametrize("name", SECRETS)
@pytest.mark.parametrize(
    "default",
    [
        "local-dev-admin-token-change-me",
        "local-dev-n8n-token-change-me",
        "local-dev-webhook-secret-change-me",
        "local-dev-ip-hash-secret-change-me",
    ],
)
def test_production_rejects_the_known_development_defaults(name: str, default: str):
    with pytest.raises(ValidationError, match="development default"):
        production(**{name: default})


def test_development_defaults_are_fine_outside_production():
    settings = Settings(app_env="local", admin_api_token="local-dev-admin-token-change-me")
    assert settings.admin_api_token.startswith("local-dev-")


def test_empty_secrets_get_ephemeral_values_outside_production():
    settings = Settings(app_env="test")
    assert len(settings.admin_api_token) >= 16


def test_web_origins_are_normalised():
    settings = Settings(app_env="test", web_public_origin=" http://a.test/ ,http://b.test,, ")
    assert settings.web_origins == {"http://a.test", "http://b.test"}


def test_admin_api_is_exposed_by_default():
    assert Settings(app_env="test").expose_admin_api is True
