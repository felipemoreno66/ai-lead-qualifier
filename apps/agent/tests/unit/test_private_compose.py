"""The private-instance override: isolation from the public demo, checked on the merged config."""

from __future__ import annotations

# ruff: noqa: S603, S607  (fixed docker/git commands, no untrusted input)
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
FILES = ["-f", "docker-compose.yml", "-f", "docker-compose.private.yml"]
SECRETS = {
    "POSTGRES_PASSWORD": "p" * 20,
    "ADMIN_API_TOKEN": "a" * 24,
    "N8N_API_TOKEN": "b" * 24,
    "N8N_WEBHOOK_SECRET": "c" * 24,
    "IP_HASH_SECRET": "d" * 24,
    "ADMIN_EMAIL": "owner@example.com",
    "ADMIN_PASSWORD_HASH": "$argon2id$v=19$m=19456,t=2,p=1$c2FsdA$aGFzaA",
    "BETTER_AUTH_SECRET": "e" * 40,
    "EMAIL_FROM": "hello@mail.example.com",
}
docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0,
    reason="docker compose is not available",
)


def compose_config(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in SECRETS}
    return subprocess.run(
        ["docker", "compose", *FILES, "config", "--format", "json"],
        cwd=ROOT,
        env={**clean, **env},
        capture_output=True,
        text=True,
    )


@docker
def test_merged_config_is_a_separate_production_instance():
    result = compose_config(SECRETS)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["name"] == "ai-lead-qualifier-private"
    services = config["services"]
    # The demo loader and Mailpit never start here (they sit behind a profile nobody enables).
    assert "demo-init" not in services and "mailpit" not in services
    agent = services["agent"]["environment"]
    assert agent["APP_ENV"] == "production"
    assert agent["ENABLED_WORKSPACES"] == "david-moreno"
    assert agent["DEMO_SEED"] == "false"
    assert agent["EMAIL_PROVIDER"] == "resend"
    web = services["web"]["environment"]
    assert web["APP_ENV"] == "production"
    # `compose config` escapes "$" as "$$" in its output
    assert web["ADMIN_PASSWORD_HASH"].replace("$$", "$").startswith("$argon2id$")
    for name, service in services.items():
        for port in service.get("ports", []):
            assert port["host_ip"] == "127.0.0.1", f"{name} must bind to localhost only"
    # No host port of the demo stack, so both can run side by side.
    published = {int(p["published"]) for s in services.values() for p in s.get("ports", [])}
    assert published.isdisjoint({3000, 8000, 5432, 8025, 1025})
    assert set(config["volumes"]) >= {"pgdata"}  # prefixed by the project name: its own database


@docker
@pytest.mark.parametrize(
    "missing",
    ["ADMIN_EMAIL", "ADMIN_PASSWORD_HASH", "BETTER_AUTH_SECRET", "EMAIL_FROM", "POSTGRES_PASSWORD"],
)
def test_the_private_instance_refuses_to_start_without_its_secrets(missing: str):
    result = compose_config({k: v for k, v in SECRETS.items() if k != missing})
    assert result.returncode != 0
    assert missing in result.stderr


def test_the_override_pins_isolation_settings_in_the_file_itself():
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))
    data = yaml.load((ROOT / "docker-compose.private.yml").read_text(), Loader)  # noqa: S506
    assert data["name"] == "ai-lead-qualifier-private"
    assert data["services"]["agent"]["environment"]["DEMO_SEED"] == "false"
    assert data["services"]["demo-init"]["profiles"] == ["demo-only"]


def test_private_env_and_data_never_reach_git():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert ".env.private.example" in tracked
    assert not [f for f in tracked if f.startswith("data/private/") or f == ".env.private"]
    ignored = subprocess.run(
        ["git", "check-ignore", ".env.private", "data/private/leads.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert ignored == [".env.private", "data/private/leads.json"]
    # The template has no values at all.
    for line in (ROOT / ".env.private.example").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            assert line.split("=", 1)[1] == "", f"value in the template: {line.split('=')[0]}"
