"""Knowledge base: kb_documents and kb_chunks with a pgvector HNSW index.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

MODELS = (
    "'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',"
    "'openai/text-embedding-3-small@384','fake-hash-384'"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "kb_documents",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_slug", sa.Text, sa.ForeignKey("workspaces.slug"), nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("content_sha256", sa.Text, nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("workspace_slug", "path", name="uq_kb_documents_workspace_path"),
    )
    op.create_table(
        "kb_chunks",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("kb_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("heading_path", sa.Text, nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("embedding_model", sa.Text, nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_kb_chunks_document_index"),
        sa.CheckConstraint(f"embedding_model IN ({MODELS})", name="ck_kb_chunks_embedding_model"),
    )
    op.execute(
        "CREATE INDEX ix_kb_chunks_embedding_hnsw ON kb_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("kb_chunks")
    op.drop_table("kb_documents")
