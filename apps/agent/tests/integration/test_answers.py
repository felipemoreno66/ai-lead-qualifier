from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.infrastructure.embeddings import FakeEmbeddings
from tests.integration.test_admin_api import AUTH, lead_id_for, submit
from tests.integration.test_kb import KB, SLUG
from tests.integration.test_qualify import qualify, recorded

pytestmark = pytest.mark.integration
QUESTION = "How much does the Data & AI Course cost?"


async def count(db: AsyncEngine, table: str) -> int:
    async with db.connect() as conn:
        return int((await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one())  # noqa: S608


async def reindex(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(f"/admin/kb/{SLUG}/reindex", headers=AUTH)
    assert response.status_code == 200 and KB.is_dir()


async def test_a_run_answers_from_the_kb_through_draft_and_stores_citations(make_client, db):
    async with make_client(
        llm_provider=recorded(db), embeddings=FakeEmbeddings(), kb_min_similarity=0.1
    ) as client:
        await reindex(client)
        await submit(client, "kb1@example.com", looking_for=QUESTION)
        lead_id = await lead_id_for(client, "kb1@")
        assert (await qualify(client, lead_id)).json()["status"] == "pending_review"
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()

    (answer,) = detail["kb_answers"]
    assert answer["question"] == QUESTION and answer["covered"]
    assert answer["citations"], "a covered answer carries its sources"
    citation = answer["citations"][0]
    assert citation["document_path"].endswith(".md") and citation["quote"]
    async with db.connect() as conn:
        content = (
            await conn.execute(
                sa.text("SELECT content FROM kb_chunks WHERE id = CAST(:i AS uuid)"),
                {"i": citation["chunk_id"]},
            )
        ).scalar_one()
        nodes = (
            (await conn.execute(sa.text("SELECT node FROM llm_calls ORDER BY created_at")))
            .scalars()
            .all()
        )
    assert citation["quote"] in content
    assert nodes == ["extract", "qualify", "answer", "draft"]
    (message,) = detail["messages"]
    assert message["guard_warnings"] == []


async def test_a_question_the_docs_do_not_cover_gets_the_fixed_text(make_client, db):
    async with make_client(
        llm_provider=recorded(db), embeddings=FakeEmbeddings(), kb_min_similarity=0.95
    ) as client:
        await reindex(client)
        await submit(client, "kb2@example.com", looking_for="Do you sponsor visas?")
        lead_id = await lead_id_for(client, "kb2@")
        assert (await qualify(client, lead_id)).json()["status"] == "pending_review"
        detail = (await client.get(f"/admin/leads/{lead_id}", headers=AUTH)).json()
    (answer,) = detail["kb_answers"]
    assert not answer["covered"] and answer["citations"] == []
    assert answer["answer"].startswith("Not covered in our documentation")
    assert await count(db, "answer_citations") == 0


async def test_deleting_the_lead_deletes_answers_and_citations(make_client, db):
    async with make_client(
        llm_provider=recorded(db), embeddings=FakeEmbeddings(), kb_min_similarity=0.1
    ) as client:
        await reindex(client)
        await submit(client, "kb3@example.com", looking_for=QUESTION)
        lead_id = await lead_id_for(client, "kb3@")
        await qualify(client, lead_id)
        assert await count(db, "lead_answers") == 1 and await count(db, "answer_citations") >= 1
        assert (await client.delete(f"/admin/leads/{lead_id}", headers=AUTH)).status_code == 204
    assert await count(db, "lead_answers") == 0 and await count(db, "answer_citations") == 0
    assert await count(db, "kb_chunks") > 0  # the knowledge base itself stays


async def test_migration_0011_steps_down_and_up(pg_base_url):
    from alembic import command

    from tests.conftest import alembic_config, create_database

    url = create_database(pg_base_url, "leadq_migration_0011")
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0010")
    eng = sa.create_engine(url)
    with eng.connect() as conn:
        names = set(sa.inspect(conn).get_table_names())
    eng.dispose()
    assert "kb_chunks" in names and not ({"lead_answers", "answer_citations"} & names)
    command.upgrade(cfg, "head")


async def test_replacing_with_no_answers_clears_the_previous_ones(make_client, db):
    from lead_qualifier.infrastructure.db.repositories import AnswerRepository
    from lead_qualifier.ports.clock import SystemClock

    async with make_client(
        llm_provider=recorded(db), embeddings=FakeEmbeddings(), kb_min_similarity=0.1
    ) as client:
        await reindex(client)
        await submit(client, "kb4@example.com", looking_for=QUESTION)
        lead_id = await lead_id_for(client, "kb4@")
        await qualify(client, lead_id)
        assert await count(db, "lead_answers") == 1
        async with db.connect() as conn:
            run_id = (await conn.execute(sa.text("SELECT id FROM agent_runs"))).scalar_one()
        async with db.begin() as conn:
            await AnswerRepository(conn).replace_for_lead(
                uuid.UUID(lead_id), run_id, [], SystemClock().now()
            )
    assert await count(db, "lead_answers") == 0 and await count(db, "answer_citations") == 0
