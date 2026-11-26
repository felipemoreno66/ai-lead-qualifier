"""docker-compose.public.yml: only the web port is published and the agent boots with the guards."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lead_qualifier.config import Settings

ROOT = Path(__file__).resolve().parents[4]
SECRETS = {
    "PUBLIC_URL": "https://demo.example.ts.net",
    "POSTGRES_PASSWORD": "p" * 24,
    "ADMIN_API_TOKEN": "a" * 24,
    "N8N_API_TOKEN": "b" * 24,
    "N8N_WEBHOOK_SECRET": "c" * 24,
    "IP_HASH_SECRET": "d" * 24,
}

DOCKER = shutil.which("docker") or "docker"
needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")


def render(env: dict[str, str], *extra: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in SECRETS and not k.startswith("DEMO_")}
    return subprocess.run(  # noqa: S603
        [
            DOCKER,
            "compose",
            *extra,
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.public.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env={**clean, **env},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    result = render(SECRETS, "--profile", "n8n")
    if result.returncode != 0 and "unknown flag" in result.stderr:
        pytest.skip("docker compose plugin not available")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)  # type: ignore[no-any-return]


@needs_docker
def test_the_project_has_its_own_name(config):
    assert config["name"] == "alq-demo"


@needs_docker
def test_only_the_web_and_the_mailpit_ui_are_published_on_loopback(config):
    published = {
        name: [(p["host_ip"], p["target"]) for p in svc.get("ports", [])]
        for name, svc in config["services"].items()
        if svc.get("ports")
    }
    assert published == {"web": [("127.0.0.1", 3000)], "mailpit": [("127.0.0.1", 8025)]}
    assert "n8n" not in config["services"]  # not even with COMPOSE_PROFILES=n8n
    for name in ("postgres", "agent", "demo-reset"):
        assert not config["services"][name].get("ports")


@needs_docker
def test_the_model_is_fake_and_no_key_or_real_smtp_reaches_the_containers(config):
    for name in ("agent", "demo-init", "demo-reset"):
        env = config["services"][name]["environment"]
        assert env["LLM_PROVIDER"] == "fake"
        assert env["PUBLIC_DEMO"] == "true"
        assert env["DEMO_SEED"] == "true"
    agent = config["services"]["agent"]["environment"]
    assert agent["ANTHROPIC_API_KEY"] == "" and agent["OPENAI_API_KEY"] == ""
    assert agent["SMTP_HOST"] == "mailpit" and agent["SMTP_USERNAME"] == ""
    assert agent["ORCHESTRATOR"] == "inline"


@needs_docker
def test_rate_limits_are_tighter_than_the_defaults(config):
    agent = config["services"]["agent"]["environment"]
    assert int(agent["RATE_IP_PER_MINUTE"]) < 5
    assert int(agent["RATE_IP_PER_HOUR"]) < 30
    assert int(agent["RATE_WORKSPACE_PER_HOUR"]) < 300
    assert int(agent["RATE_EMAIL_PER_DAY"]) < 3
    assert int(agent["KB_ASK_PER_HOUR"]) < 60
    web = config["services"]["web"]["environment"]
    assert web["PUBLIC_DEMO"] == "true"
    assert web["ADMIN_EMAIL"] == "" and web["ADMIN_PASSWORD_HASH"] == ""  # no operator login
    assert all(int(web[k]) > 0 for k in web if k.startswith("DEMO_LIMIT_"))


@needs_docker
def test_no_development_default_secret_is_left(config):
    rendered = json.dumps(config["services"])
    assert "local-dev-" not in rendered


@needs_docker
def test_the_agent_settings_pass_the_public_demo_guards(config):
    env = config["services"]["agent"]["environment"]
    values = {k.lower(): v for k, v in env.items() if v != ""}
    settings = Settings(_env_file=None, **values)  # type: ignore[arg-type]
    assert settings.public_demo and settings.llm_provider == "fake"


@pytest.mark.parametrize("missing", sorted(SECRETS))
@needs_docker
def test_it_refuses_to_start_without_a_required_secret(missing: str):
    env = {k: v for k, v in SECRETS.items() if k != missing}
    result = render(env)
    assert result.returncode != 0
    assert missing in result.stderr


# --- Without Docker: runs in CI everywhere -----------------------------------------------------

from tests.unit.compose_yaml import MissingVariable, load_merged, parse_env_file  # noqa: E402

FILES = ["docker-compose.yml", "docker-compose.public.yml"]
AGENT_IMAGE_SERVICES = ("agent", "demo-init", "demo-reset")


@pytest.fixture(scope="module")
def merged() -> dict[str, Any]:
    env = {**parse_env_file(ROOT / ".env.public.example"), **SECRETS}
    env = {k: v for k, v in env.items() if v != ""}
    return load_merged(ROOT, FILES, env)


@pytest.mark.parametrize("service", AGENT_IMAGE_SERVICES)
def test_every_agent_image_service_boots_with_the_public_demo_guards(merged, service: str):
    env = merged[service]["environment"]
    values = {k.lower(): v for k, v in env.items() if v != ""}
    settings = Settings(_env_file=None, **values)  # type: ignore[arg-type]
    assert settings.public_demo
    assert settings.llm_provider == "fake"
    assert settings.smtp_host == "mailpit"
    assert settings.demo_seed


def test_the_web_app_and_the_agent_share_the_admin_token(merged):
    assert merged["web"]["environment"]["ADMIN_API_TOKEN"] == SECRETS["ADMIN_API_TOKEN"]
    assert merged["agent"]["environment"]["ADMIN_API_TOKEN"] == SECRETS["ADMIN_API_TOKEN"]


def test_the_yaml_view_publishes_only_web_and_the_mailpit_ui(merged):
    assert "n8n" in merged and merged["n8n"]["profiles"] == ["never-in-public-demo"]
    published = {n: s["ports"] for n, s in merged.items() if s.get("ports")}
    assert published == {
        "web": ["127.0.0.1:3000:3000"],
        "mailpit": ["127.0.0.1:18025:8025"],
    }


@pytest.mark.parametrize("missing", sorted(SECRETS))
def test_the_yaml_view_refuses_a_missing_required_secret(missing: str):
    env = {k: v for k, v in SECRETS.items() if k != missing}
    with pytest.raises(MissingVariable, match=missing):
        load_merged(ROOT, FILES, env)
