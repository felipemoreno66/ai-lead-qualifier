from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa

from lead_qualifier.infrastructure.embeddings import FakeEmbeddings
from lead_qualifier.ports.clock import SystemClock
from lead_qualifier.services.kb import KnowledgeBaseService
from tests.helpers import WORKSPACES_DIR

pytestmark = pytest.mark.integration
SLUG = "northwind-academy"
KB = WORKSPACES_DIR / SLUG / "knowledge-base"
AUTH = {"Authorization": "Bearer test-admin-token-123456"}


@pytest.fixture
def service(db) -> KnowledgeBaseService:
    return KnowledgeBaseService(db, FakeEmbeddings(), SystemClock())


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    (tmp_path / "a.md").write_text("# Alpha\n\n## Refunds\n\nFull refund within 14 days.\n")
    (tmp_path / "b.md").write_text("# Beta\n\n## Schedule\n\nEvening live sessions.\n")
    (tmp_path / "_notes.md").write_text("# Notes\n\nnot ingested\n")
    return tmp_path


async def _count(db, table: str) -> int:
    async with db.connect() as conn:
        return (await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608


async def test_ingest_is_idempotent_and_skips_notes(service, kb_dir, db):
    first = await service.ingest(SLUG, kb_dir)
    assert (first.added, first.unchanged, first.chunks) == (2, 0, 2)
    second = await service.ingest(SLUG, kb_dir)
    assert (second.added, second.updated, second.unchanged) == (0, 0, 2)
    assert await _count(db, "kb_chunks") == 2


async def test_changed_and_deleted_documents_are_synced(service, kb_dir, db):
    await service.ingest(SLUG, kb_dir)
    (kb_dir / "a.md").write_text("# Alpha\n\n## Refunds\n\nNo refunds after 7 days.\n")
    (kb_dir / "b.md").unlink()
    result = await service.ingest(SLUG, kb_dir)
    assert (result.updated, result.removed, result.chunks) == (1, 1, 1)
    hits = await service.retrieve(SLUG, "refunds after 7 days", min_similarity=0)
    assert [h.document_path for h in hits] == ["a.md"]
    assert "7 days" in hits[0].content
    assert await _count(db, "kb_documents") == 1


async def test_retrieval_ranks_threshold_and_workspace(service, db):
    await service.ingest(SLUG, KB)
    hits = await service.retrieve(SLUG, "How much does the Data & AI Course cost?", top_k=3)
    assert 1 <= len(hits) <= 3
    assert hits[0].similarity >= hits[-1].similarity
    assert hits[0].document_path.startswith("02-pricing")
    assert await service.retrieve(SLUG, "zxqv wxyz", min_similarity=0.9) == []
    assert await service.retrieve("other-workspace", "refund", min_similarity=0) == []


async def test_vectors_of_another_model_are_not_mixed(service, kb_dir, db):
    await service.ingest(SLUG, kb_dir)
    async with db.begin() as conn:
        # simulate chunks produced by a different (allowed) model
        await conn.execute(
            sa.text("UPDATE kb_chunks SET embedding_model = 'openai/text-embedding-3-small@384'")
        )
    assert await service.retrieve(SLUG, "refund", min_similarity=-1) == []
    result = await service.ingest(SLUG, kb_dir)  # same hashes, but re-embedded with this model
    assert result.updated == 2
    assert await service.retrieve(SLUG, "refund", min_similarity=-1)
    async with db.begin() as conn:
        with pytest.raises(sa.exc.IntegrityError):
            await conn.execute(sa.text("UPDATE kb_chunks SET embedding_model = 'made-up'"))


async def test_reindex_endpoint_requires_admin_and_reports(make_client, db, kb_dir):
    async with make_client(embeddings=FakeEmbeddings()) as client:
        url = f"/admin/kb/{SLUG}/reindex"
        assert (await client.post(url)).status_code == 401
        assert (await client.post(url, headers={"Authorization": "Bearer nope"})).status_code == 403
        assert (await client.post("/admin/kb/nope/reindex", headers=AUTH)).status_code == 404
        first = await client.post(url, headers=AUTH)
        assert first.status_code == 200
        assert first.json()["added"] == 7
        again = (await client.post(url, headers=AUTH)).json()
        assert (again["added"], again["unchanged"]) == (0, 7)
        forced = (await client.post(url, headers=AUTH, params={"force": "true"})).json()
        assert forced["updated"] == 7


async def test_migration_0010_steps_down_and_up(pg_base_url):
    from alembic import command

    from tests.conftest import alembic_config, create_database

    url = create_database(pg_base_url, "leadq_migration_0010")
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0009")
    eng = sa.create_engine(url)
    with eng.connect() as conn:
        names = set(sa.inspect(conn).get_table_names())
    eng.dispose()
    assert not ({"kb_documents", "kb_chunks"} & names)
    command.upgrade(cfg, "head")
