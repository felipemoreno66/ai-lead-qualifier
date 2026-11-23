from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings
from lead_qualifier.infrastructure.db.engine import create_engine
from lead_qualifier.ports.clock import SystemClock
from lead_qualifier.services.workspace_sync import sync_workspaces
from lead_qualifier.workspaces.loader import WorkspaceRegistry, load_workspaces
from tests.helpers import WORKSPACES_DIR

os.environ.setdefault("APP_ENV", "test")

AGENT_DIR = Path(__file__).resolve().parents[1]
IMAGE = "pgvector/pgvector:pg17"


def alembic_config(url: str) -> Config:
    cfg = Config(str(AGENT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(AGENT_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def pg_base_url() -> Iterator[str]:
    """URL of a Postgres server: TEST_DATABASE_URL, or a throwaway Testcontainers instance."""
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        yield external
        return
    try:
        from testcontainers.community.postgres import PostgresContainer

        container = PostgresContainer(IMAGE, driver="psycopg")
        container.start()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres is not available (set TEST_DATABASE_URL or start Docker): {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


def create_database(base_url: str, name: str) -> str:
    """Create an empty database next to the base one and return its URL."""
    url = make_url(base_url)
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return url.set(database=name).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def migrated_url(pg_base_url: str) -> str:
    url = create_database(pg_base_url, "leadq_test")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
async def engine(migrated_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(migrated_url)
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
def registry() -> WorkspaceRegistry:
    return load_workspaces(
        WORKSPACES_DIR,
        app_env="test",
        enabled=frozenset({"northwind-academy"}),
    )


@pytest.fixture
async def db(engine: AsyncEngine, registry: WorkspaceRegistry) -> AsyncEngine:
    """The migrated engine with every table emptied and workspaces re-synced."""
    async with engine.begin() as conn:
        await conn.execute(sa.text("SET LOCAL app.allow_spend_reset = 'on'"))
        await conn.execute(
            sa.text(
                "TRUNCATE leads, lead_events, outbox_events, rate_limit_hits, workspaces,"
                " llm_calls, llm_spend CASCADE"
            )
        )
    await sync_workspaces(engine, registry, SystemClock())
    return engine


@pytest.fixture
def make_settings(migrated_url: str):
    def _make(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "app_env": "test",
            "database_url": migrated_url,
            "workspaces_dir": WORKSPACES_DIR,
            "migrations_dir": AGENT_DIR / "migrations",
            "enabled_workspaces": "northwind-academy",
            "dispatcher_enabled": False,
            "min_fill_seconds": 0,
            "admin_api_token": "test-admin-token-123456",
            "n8n_api_token": "test-n8n-token-1234567",
            "n8n_webhook_secret": "test-webhook-secret-1234",
            "ip_hash_secret": "test-ip-hash-secret-123",
        }
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    return _make


@pytest.fixture
async def make_client(db: AsyncEngine, registry: WorkspaceRegistry, make_settings):
    """Build an httpx client bound to a fresh app over the clean test database."""
    import httpx

    from lead_qualifier.http.app import create_app

    clients: list[httpx.AsyncClient] = []

    def _make(
        clock: object | None = None,
        llm_provider: object | None = None,
        email_sender: object | None = None,
        **overrides: object,
    ) -> httpx.AsyncClient:
        settings = make_settings(**overrides)
        enabled = frozenset(settings.enabled_workspace_slugs)
        reg = load_workspaces(WORKSPACES_DIR, app_env="test", enabled=enabled)
        app = create_app(
            settings,
            engine=db,
            registry=reg,
            clock=clock,  # type: ignore[arg-type]
            llm_provider=llm_provider,  # type: ignore[arg-type]
            email_sender=email_sender,  # type: ignore[arg-type]
        )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            timeout=10,
        )
        client.app = app  # type: ignore[attr-defined]
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.app.state.checkpointer.aclose()  # type: ignore[attr-defined]
    for client in clients:
        await client.app.state.checkpointer.aclose()  # type: ignore[attr-defined]


@pytest.fixture(autouse=True, scope="session")
def _block_outbound_network() -> Iterator[None]:
    """Tests must never reach the internet (and so never a paid API): only private/loopback."""
    import ipaddress
    import socket

    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> None:
        if isinstance(address, tuple) and isinstance(address[0], str):
            if address[0] == "localhost":
                return real_connect(self, address)  # type: ignore[arg-type]
            try:
                ip = ipaddress.ip_address(address[0])
            except ValueError:
                ip = None
            if ip is None or not (ip.is_loopback or ip.is_private):
                raise RuntimeError(f"outbound network blocked in tests: {address[0]}")
        real_connect(self, address)  # type: ignore[arg-type]

    socket.socket.connect = guarded  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]


class SmtpInbox:
    """A real SMTP server on loopback that keeps what it receives (no mail ever leaves the box)."""

    def __init__(self) -> None:
        from aiosmtpd.controller import Controller

        self.messages: list[Any] = []
        inbox = self

        class Handler:
            async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
                inbox.messages.append(envelope)
                return "250 OK"

        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port: int = probe.getsockname()[1]
        self._controller = Controller(Handler(), hostname="127.0.0.1", port=self.port)

    def __enter__(self) -> SmtpInbox:
        self._controller.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._controller.stop()


@pytest.fixture
def smtp_inbox() -> Iterator[SmtpInbox]:
    with SmtpInbox() as inbox:
        yield inbox
